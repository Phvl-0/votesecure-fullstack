from sqlalchemy import Column, String, Boolean, DateTime
from sqlalchemy.sql import func
from database import Base

class UserModel(Base):
    __tablename__ = "users"

    # Columns mapped directly to PostgreSQL table fields
    id = Column(String, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default="voter")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
