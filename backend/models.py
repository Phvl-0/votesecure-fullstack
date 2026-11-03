from sqlalchemy import Column, String, Boolean, DateTime, Text, ForeignKey, UniqueConstraint
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


class ElectionModel(Base):
    __tablename__ = "elections"

    id = Column(String, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(Text)
    start_date = Column(DateTime(timezone=True), nullable=False)
    end_date = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class CandidateModel(Base):
    __tablename__ = "candidates"

    id = Column(String, primary_key=True, index=True)
    election_id = Column(String, ForeignKey("elections.id", ondelete="CASCADE"), index=True, nullable=False)
    name = Column(String, nullable=False)
    party = Column(String)
    bio = Column(Text)
    image = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class VoteReceiptModel(Base):
    """Who has voted in which election. Says nothing about what was chosen."""
    __tablename__ = "vote_receipts"
    __table_args__ = (
        UniqueConstraint("election_id", "user_id", name="uq_one_receipt_per_election"),
    )

    id = Column(String, primary_key=True, index=True)
    election_id = Column(String, ForeignKey("elections.id", ondelete="CASCADE"), index=True, nullable=False)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class BallotModel(Base):
    """What was chosen. Deliberately no user and no timestamp, so it cannot be matched to a receipt."""
    __tablename__ = "ballots"

    id = Column(String, primary_key=True, index=True)
    election_id = Column(String, ForeignKey("elections.id", ondelete="CASCADE"), index=True, nullable=False)
    candidate_id = Column(String, ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False)


class AuditLogModel(Base):
    __tablename__ = "audit_logs"

    id = Column(String, primary_key=True, index=True)
    # No foreign key on purpose: the trail must outlive the user it describes.
    user_id = Column(String, index=True, nullable=False)
    action = Column(String, index=True, nullable=False)
    details = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
