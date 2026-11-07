from typing import Annotated
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.db.session import create_sessionmaker, get_session
from app.modules.users.models import User
from tests.db.factories import make_user

pytestmark = pytest.mark.docker


async def test_request_exception_rolls_back_uncommitted_user(engine: AsyncEngine) -> None:
    app = FastAPI()
    app.state.sessionmaker = create_sessionmaker(engine)
    email = f"rollback-{uuid4()}@example.ru"
    request_session: AsyncSession | None = None

    @app.post("/users")
    async def create_user(session: Annotated[AsyncSession, Depends(get_session)]) -> None:
        nonlocal request_session
        request_session = session
        await make_user(session, email=email)
        raise RuntimeError("request failed")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with pytest.raises(RuntimeError, match="request failed"):
            await client.post("/users")

    assert request_session is not None
    assert not request_session.in_transaction()

    async with app.state.sessionmaker() as session:
        result = await session.execute(select(User).where(User.email == email))

    assert result.scalar_one_or_none() is None
