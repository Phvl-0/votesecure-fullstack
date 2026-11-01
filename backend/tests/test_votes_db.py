import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from database import Base
from models import CandidateModel, ElectionModel, UserModel, VoteModel


def uid():
    return str(uuid.uuid4())


async def seed(session, user_id, election_id, candidate_id):
    """Add one election with one candidate, and one user if it is new."""
    now = datetime.now(timezone.utc)
    if user_id:
        session.add(UserModel(id=user_id, email=f"{user_id}@example.com", hashed_password="not-a-real-hash"))
    session.add(ElectionModel(id=election_id, title="Test election", start_date=now, end_date=now + timedelta(days=1)))
    await session.commit()
    session.add(CandidateModel(id=candidate_id, election_id=election_id, name="Candidate"))
    await session.commit()


def vote(election_id, candidate_id, user_id):
    return VoteModel(id=uid(), election_id=election_id, candidate_id=candidate_id, user_id=user_id)


async def run_with_session(scenario):
    # Own engine, no pooled connections: nothing is shared with the app's event loop.
    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await scenario(async_sessionmaker(engine, expire_on_commit=False))
    finally:
        await engine.dispose()


def test_database_refuses_a_second_vote_in_the_same_election():
    async def scenario(Session):
        user_id, election_id, cand_a, cand_b = uid(), uid(), uid(), uid()
        async with Session() as s:
            await seed(s, user_id, election_id, cand_a)
            s.add(CandidateModel(id=cand_b, election_id=election_id, name="Other"))
            await s.commit()
        async with Session() as s:
            s.add(vote(election_id, cand_a, user_id))
            await s.commit()
        async with Session() as s:
            s.add(vote(election_id, cand_b, user_id))
            with pytest.raises(IntegrityError):
                await s.commit()

    asyncio.run(run_with_session(scenario))


def test_same_person_may_vote_in_a_different_election():
    async def scenario(Session):
        user_id = uid()
        first = (uid(), uid())
        second = (uid(), uid())
        async with Session() as s:
            await seed(s, user_id, first[0], first[1])
        async with Session() as s:
            await seed(s, None, second[0], second[1])
        async with Session() as s:
            s.add(vote(first[0], first[1], user_id))
            s.add(vote(second[0], second[1], user_id))
            await s.commit()

    asyncio.run(run_with_session(scenario))
