import asyncio
from datetime import UTC, datetime

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import create_engine, create_sessionmaker
from app.modules.auth.models import AuthSession, EmailToken
from app.workers.celery_app import celery_app


async def delete_expired_auth(session: AsyncSession, now: datetime) -> dict[str, int]:
    async with session.begin():
        sessions = await session.execute(
            delete(AuthSession).where(AuthSession.expires_at <= now).returning(AuthSession.id)
        )
        tokens = await session.execute(
            delete(EmailToken).where(EmailToken.expires_at <= now).returning(EmailToken.id)
        )
        return {"sessions": len(sessions.all()), "email_tokens": len(tokens.all())}


async def run_auth_cleanup() -> dict[str, int]:
    engine = create_engine(get_settings())
    try:
        async with create_sessionmaker(engine)() as session:
            return await delete_expired_auth(session, datetime.now(UTC))
    finally:
        await engine.dispose()


@celery_app.task(name="auth.cleanup_expired", ignore_result=True)
def cleanup_expired_auth() -> dict[str, int]:
    return asyncio.run(run_auth_cleanup())
