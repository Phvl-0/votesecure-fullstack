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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql import func

# Local module imports
from security import verify_password, hash_password
from database import engine, Base, get_db
from models import UserModel, ElectionModel, CandidateModel, VoteModel

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


# 7. CANDIDATES AND ELECTION REMOVAL
class CandidateCreate(BaseModel):
    name: str
    party: str | None = None
    bio: str | None = None
    image: str | None = None


@app.post("/elections/{election_id}/candidates", status_code=status.HTTP_201_CREATED)
async def add_candidate(
    election_id: str,
    data: CandidateCreate,
    admin: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    election = await db.get(ElectionModel, election_id)
    if election is None:
        raise HTTPException(status_code=404, detail="Election not found")
    if election_status(election.start_date, election.end_date) != "upcoming":
        raise HTTPException(status_code=409, detail="Candidates can only be changed before the election starts")
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Name is required")
    candidate = CandidateModel(
        id=str(uuid.uuid4()),
        election_id=election_id,
        name=name,
        party=data.party,
        bio=data.bio,
        image=data.image,
    )
    db.add(candidate)
    await db.commit()
    await db.refresh(candidate)
    return {
        "id": candidate.id,
        "election_id": candidate.election_id,
        "name": candidate.name,
        "party": candidate.party,
        "bio": candidate.bio,
        "image": candidate.image,
    }


@app.delete("/candidates/{candidate_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_candidate(
    candidate_id: str,
    admin: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    candidate = await db.get(CandidateModel, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    election = await db.get(ElectionModel, candidate.election_id)
    if election_status(election.start_date, election.end_date) != "upcoming":
        raise HTTPException(status_code=409, detail="Candidates can only be changed before the election starts")
    await db.delete(candidate)
    await db.commit()


@app.delete("/elections/{election_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_election(
    election_id: str,
    admin: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    election = await db.get(ElectionModel, election_id)
    if election is None:
        raise HTTPException(status_code=404, detail="Election not found")
    await db.delete(election)
    await db.commit()


# 8. VOTING
class VoteCreate(BaseModel):
    candidate_id: str


@app.post("/elections/{election_id}/votes", status_code=status.HTTP_201_CREATED)
async def cast_vote(
    election_id: str,
    data: VoteCreate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    election = await db.get(ElectionModel, election_id)
    if election is None:
        raise HTTPException(status_code=404, detail="Election not found")
    if election_status(election.start_date, election.end_date) != "active":
        raise HTTPException(status_code=409, detail="Voting is not open for this election")
    candidate = await db.get(CandidateModel, data.candidate_id)
    if candidate is None or candidate.election_id != election_id:
        raise HTTPException(status_code=422, detail="Candidate does not belong to this election")
    user = await db.get(UserModel, current_user["user_id"])
    if user is None:
        raise HTTPException(status_code=401, detail="Unknown user")
    vote = VoteModel(
        id=str(uuid.uuid4()),
        election_id=election_id,
        candidate_id=data.candidate_id,
        user_id=user.id,
    )
    db.add(vote)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="You have already voted in this election")
    return {"id": vote.id, "election_id": election_id}


@app.get("/elections/{election_id}/my-vote")
async def my_vote(
    election_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    election = await db.get(ElectionModel, election_id)
    if election is None:
        raise HTTPException(status_code=404, detail="Election not found")
    result = await db.execute(
        select(VoteModel.id).where(
            VoteModel.election_id == election_id,
            VoteModel.user_id == current_user["user_id"],
        )
    )
    return {"has_voted": result.first() is not None}


# 9. RESULTS
@app.get("/results")
async def get_results(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Tallies for elections that have started, counted from the votes themselves."""
    elections = (await db.execute(select(ElectionModel))).scalars().all()
    visible = [e for e in elections if election_status(e.start_date, e.end_date) != "upcoming"]
    if not visible:
        return []
    ids = [e.id for e in visible]
    count_rows = await db.execute(
        select(VoteModel.candidate_id, func.count(VoteModel.id))
        .where(VoteModel.election_id.in_(ids))
        .group_by(VoteModel.candidate_id)
    )
    counts = {candidate_id: n for candidate_id, n in count_rows.all()}
    cand_result = await db.execute(
        select(CandidateModel)
        .where(CandidateModel.election_id.in_(ids))
        .order_by(CandidateModel.created_at)
    )
    by_election = {election_id: [] for election_id in ids}
    for c in cand_result.scalars().all():
        by_election[c.election_id].append(c)
    results = []
    for e in visible:
        rows = [
            {
                "candidate_id": c.id,
                "candidate_name": c.name,
                "party": c.party,
                "vote_count": counts.get(c.id, 0),
            }
            for c in by_election[e.id]
        ]
        results.append({
            "id": e.id,
            "title": e.title,
            "end_date": e.end_date,
            "status": election_status(e.start_date, e.end_date),
            "total_votes": sum(r["vote_count"] for r in rows),
            "results": rows,
        })
    results.sort(key=lambda r: r["status"] == "ended")
    return results


# 10. MY VOTES
@app.get("/me/votes")
async def my_votes(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The caller's own voting history, taken from the token, never from the request."""
    rows = await db.execute(
        select(VoteModel, ElectionModel, CandidateModel)
        .join(ElectionModel, ElectionModel.id == VoteModel.election_id)
        .join(CandidateModel, CandidateModel.id == VoteModel.candidate_id)
        .where(VoteModel.user_id == current_user["user_id"])
        .order_by(VoteModel.created_at.desc())
    )
    return [
        {
            "id": vote.id,
            "created_at": vote.created_at,
            "election_id": vote.election_id,
            "candidate_id": vote.candidate_id,
            "elections": {
                "title": election.title,
                "status": election_status(election.start_date, election.end_date),
            },
            "candidates": {"name": candidate.name},
        }
        for vote, election, candidate in rows.all()
    ]
