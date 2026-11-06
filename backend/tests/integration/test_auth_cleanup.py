import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.core.security import generate_token, hash_token
from app.db.session import create_sessionmaker
from app.modules.auth.models import AuthSession, EmailToken, EmailTokenPurpose, RefreshToken
from app.modules.users.models import User
from app.workers import auth_cleanup
from app.workers.celery_app import celery_app
from tests.integration.test_auth import alembic_config as alembic_config
from tests.integration.test_auth import auth_api as auth_api
from tests.integration.test_auth import engine as engine
from tests.integration.test_auth import migrated_url as migrated_url
from tests.integration.test_sessions import SessionsAPI
from tests.integration.test_sessions import sessions_api as sessions_api

pytestmark = pytest.mark.docker


async def test_cleanup_removes_only_expired_auth_and_preserves_refresh_history(
    sessions_api: SessionsAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = sessions_api.api
    now = datetime.now(UTC)
    created = now - timedelta(days=2)
    sessionmaker = create_sessionmaker(api.engine)
    async with sessionmaker() as session, session.begin():
        devices = [
            AuthSession(
                user_id=sessions_api.initial.user_id,
                created_at=created,
                last_used_at=created,
                expires_at=expiry,
                revoked_at=now if revoked else None,
            )
            for expiry, revoked in (
                (now - timedelta(days=1), False),
                (now, False),
                (now + timedelta(days=1), False),
                (now + timedelta(days=1), True),
            )
        ]
        session.add_all(devices)
        await session.flush()
        for device in devices:
            used = RefreshToken(
                session_id=device.id,
                token_hash=hash_token(generate_token()),
                created_at=created,
                expires_at=device.expires_at,
                used_at=created + timedelta(hours=1),
            )
            current = RefreshToken(
                session_id=device.id,
                token_hash=hash_token(generate_token()),
                created_at=created + timedelta(hours=1),
                expires_at=device.expires_at,
            )
            session.add_all([used, current])
            await session.flush()
            used.replaced_by_id = current.id
        session.add_all(
            EmailToken(
                user_id=sessions_api.initial.user_id,
                purpose=EmailTokenPurpose.RESET_PASSWORD,
                token_hash=hash_token(generate_token()),
                created_at=created,
                expires_at=expiry,
                used_at=now if used else None,
            )
            for expiry, used in ((now, False), (now + timedelta(hours=1), True))
        )
    async with sessionmaker() as session:
        assert await auth_cleanup.delete_expired_auth(session, now) == {
            "sessions": 2,
            "email_tokens": 1,
        }
    async with api.engine.connect() as connection:
        for device in devices[:2]:
            assert (
                await connection.scalar(
                    select(func.count())
                    .select_from(RefreshToken)
                    .where(RefreshToken.session_id == device.id)
                )
                == 0
            )
        for device in devices[2:]:
            assert (
                await connection.scalar(
                    select(func.count())
                    .select_from(RefreshToken)
                    .where(RefreshToken.session_id == device.id)
                )
                == 2
            )
        assert (
            await connection.scalar(select(User.id).where(User.id == sessions_api.initial.user_id))
            == sessions_api.initial.user_id
        )
    assert (await sessions_api.protected(sessions_api.initial)).status_code == 200
    settings = api.settings.model_copy(
        update={"database_url": api.engine.url.render_as_string(hide_password=False)}
    )
    monkeypatch.setattr(auth_cleanup, "get_settings", lambda: settings)
    assert await asyncio.to_thread(auth_cleanup.cleanup_expired_auth.run) == {
        "sessions": 0,
        "email_tokens": 0,
    }
    assert celery_app.conf.beat_schedule["auth-cleanup-expired"] == {
        "task": "auth.cleanup_expired",
        "schedule": 3600.0,
    }
    assert "app.workers.auth_cleanup" in celery_app.conf.include
