import uuid
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
import jwt
from jwt import PyJWTError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

# Local module imports
from security import verify_password, hash_password
from database import engine, Base, get_db
from models import UserModel, ElectionModel, CandidateModel

# 1. LIFESPAN MANAGEMENT (Replaces deprecated @app.on_event)
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Runs on server startup before handling requests
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Runs on server shutdown (if needed)

# 2. APP & SECURITY CONFIGURATION
app = FastAPI(lifespan=lifespan)
security = HTTPBearer()

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise ValueError("SECRET_KEY environment variable is not set")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# 3. REQUEST SCHEMAS
class LoginRequest(BaseModel):
    email: str
    password: str

class UserCreate(BaseModel):
    email: str
    password: str

# 4. TOKEN HELPER & AUTH DEPENDENCY
def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        user_role: str = payload.get("role")
        email: str = payload.get("email")
        
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token payload"
            )
            
        return {"user_id": user_id, "role": user_role, "email": email}

    except PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token signature invalid or expired",
            headers={"WWW-Authenticate": "Bearer"},
        )

# 5. API ROUTES
def require_role(*allowed_roles: str):
    """Only let users whose token role is in allowed_roles through."""
    def checker(current_user: dict = Depends(get_current_user)) -> dict:
        if current_user.get("role") not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to do this",
            )
        return current_user
    return checker

@app.post("/register")
async def register_user(user_data: UserCreate, db: AsyncSession = Depends(get_db)):
    # Check if email exists in PostgreSQL
    result = await db.execute(select(UserModel).where(UserModel.email == user_data.email))
    existing_user = result.scalars().first()
    
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Create and save user record
    new_user = UserModel(
        id=str(uuid.uuid4()),
        email=user_data.email,
        hashed_password=hash_password(user_data.password),
        role="voter"
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    
    return {"message": "User registered successfully", "user_id": new_user.id}

@app.post("/login")
async def login(credentials: LoginRequest, db: AsyncSession = Depends(get_db)):
    # Query database for user by email
    result = await db.execute(select(UserModel).where(UserModel.email == credentials.email))
    user = result.scalars().first()
    
    if not user or not verify_password(credentials.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Invalid credentials"
        )
    
    jwt_claims = {
        "sub": user.id,
        "role": user.role,
        "email": user.email
    }
    
    access_token = create_access_token(data=jwt_claims)
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/me")
def get_user_profile(current_user: dict = Depends(get_current_user)):
    return {"status": "authenticated", "profile": current_user}


@app.get("/admin/users")
async def list_users(
    admin: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(UserModel))
    users = result.scalars().all()
    return [
        {"id": u.id, "email": u.email, "role": u.role, "is_active": u.is_active}
        for u in users
    ]


# 6. ELECTIONS
class ElectionCreate(BaseModel):
    title: str
    description: str | None = None
    start_date: datetime
    end_date: datetime


def election_status(start_date: datetime, end_date: datetime) -> str:
    """Decided by the server's clock, never by the browser's."""
    now = datetime.now(timezone.utc)
    if now < start_date:
        return "upcoming"
    if now <= end_date:
        return "active"
    return "ended"


def election_to_dict(election: ElectionModel, candidates: list) -> dict:
    return {
        "id": election.id,
        "title": election.title,
        "description": election.description,
        "start_date": election.start_date,
        "end_date": election.end_date,
        "status": election_status(election.start_date, election.end_date),
        "candidates": [
            {"id": c.id, "name": c.name, "party": c.party, "bio": c.bio, "image": c.image}
            for c in candidates
        ],
    }


@app.get("/elections")
async def list_elections(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ElectionModel).order_by(ElectionModel.created_at.desc()))
    elections = result.scalars().all()
    by_election = {e.id: [] for e in elections}
    if by_election:
        cand_result = await db.execute(
            select(CandidateModel).where(CandidateModel.election_id.in_(list(by_election)))
        )
        for c in cand_result.scalars().all():
            by_election[c.election_id].append(c)
    return [election_to_dict(e, by_election[e.id]) for e in elections]


@app.post("/elections", status_code=status.HTTP_201_CREATED)
async def create_election(
    data: ElectionCreate,
    admin: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    title = data.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Title is required")
    if data.start_date.tzinfo is None or data.end_date.tzinfo is None:
        raise HTTPException(status_code=422, detail="Dates must include a timezone")
    if data.end_date <= data.start_date:
        raise HTTPException(status_code=422, detail="End date must be after the start date")
    election = ElectionModel(
        id=str(uuid.uuid4()),
        title=title,
        description=data.description,
        start_date=data.start_date,
        end_date=data.end_date,
    )
    db.add(election)
    await db.commit()
    await db.refresh(election)
    return election_to_dict(election, [])
