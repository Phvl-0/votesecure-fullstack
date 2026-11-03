import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from database import Base
from models import BallotModel, ElectionModel, UserModel, VoteReceiptModel


def uid():
    return str(uuid.uuid4())


async def seed(session, user_id, election_id):
    """Add one election, and one user if it is new."""
    now = datetime.now(timezone.utc)
    if user_id:
        session.add(UserModel(id=user_id, email=f"{user_id}@example.com", hashed_password="not-a-real-hash"))
    session.add(ElectionModel(id=election_id, title="Test election", start_date=now, end_date=now + timedelta(days=1)))
    await session.commit()


def receipt(election_id, user_id):
    return VoteReceiptModel(id=uid(), election_id=election_id, user_id=user_id)


async def run_with_session(scenario):
    # Own engine, no pooled connections: nothing is shared with the app's event loop.
    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await scenario(async_sessionmaker(engine, expire_on_commit=False))
    finally:
        await engine.dispose()


def test_database_refuses_a_second_receipt_in_the_same_election():
    async def scenario(Session):
        user_id, election_id = uid(), uid()
        async with Session() as s:
            await seed(s, user_id, election_id)
        async with Session() as s:
            s.add(receipt(election_id, user_id))
            await s.commit()
        async with Session() as s:
            s.add(receipt(election_id, user_id))
            with pytest.raises(IntegrityError):
                await s.commit()

    asyncio.run(run_with_session(scenario))


def test_same_person_may_get_a_receipt_in_a_different_election():
    async def scenario(Session):
        user_id, first, second = uid(), uid(), uid()
        async with Session() as s:
            await seed(s, user_id, first)
        async with Session() as s:
            await seed(s, None, second)
        async with Session() as s:
            s.add(receipt(first, user_id))
            s.add(receipt(second, user_id))
            await s.commit()

    asyncio.run(run_with_session(scenario))


def test_ballots_table_keeps_no_trace_of_who_cast_them():
    # Secrecy by design: no user column and no timestamp on a ballot.
    assert {c.name for c in BallotModel.__table__.columns} == {"id", "election_id", "candidate_id"}
