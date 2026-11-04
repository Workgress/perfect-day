from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import generate_token, hash_token
from app.modules.auth.models import AuthSession, EmailToken, EmailTokenPurpose, RefreshToken
from app.modules.users.models import User
from tests.db.factories import make_user

pytestmark = pytest.mark.docker

NOW = datetime(2026, 11, 4, 8, tzinfo=UTC)


async def make_auth_session(
    session: AsyncSession,
    user: User,
    **overrides: Any,
) -> AuthSession:
    fields: dict[str, Any] = {
        "user_id": user.id,
        "created_at": NOW,
        "last_used_at": NOW,
        "expires_at": NOW + timedelta(days=30),
    }
    fields.update(overrides)
    result = AuthSession(**fields)
    session.add(result)
    await session.flush()
    return result


async def make_refresh_token(
    session: AsyncSession,
    device: AuthSession,
    **overrides: Any,
) -> RefreshToken:
    fields: dict[str, Any] = {
        "session_id": device.id,
        "token_hash": hash_token(generate_token()),
        "created_at": NOW,
        "expires_at": device.expires_at,
    }
    fields.update(overrides)
    result = RefreshToken(**fields)
    session.add(result)
    await session.flush()
    return result


async def make_email_token(
    session: AsyncSession,
    user: User,
    **overrides: Any,
) -> EmailToken:
    fields: dict[str, Any] = {
        "user_id": user.id,
        "purpose": EmailTokenPurpose.VERIFY_EMAIL,
        "token_hash": hash_token(generate_token()),
        "created_at": NOW,
        "expires_at": NOW + timedelta(hours=24),
    }
    fields.update(overrides)
    result = EmailToken(**fields)
    session.add(result)
    await session.flush()
    return result


async def test_session_metadata_and_server_defaults(session: AsyncSession) -> None:
    user = await make_user(session)
    device = AuthSession(user_id=user.id, expires_at=datetime.now(UTC) + timedelta(days=30))
    session.add(device)
    await session.flush()
    await session.refresh(device)

    assert device.id is not None
    assert device.created_at.tzinfo is not None
    assert device.created_at == device.last_used_at
    assert device.revoked_at is None
    assert device.ip is None
    assert device.user_agent is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"expires_at": NOW},
        {"last_used_at": NOW - timedelta(seconds=1)},
        {"revoked_at": NOW - timedelta(seconds=1)},
    ],
)
async def test_session_rejects_invalid_times(
    session: AsyncSession,
    overrides: dict[str, datetime],
) -> None:
    user = await make_user(session)

    with pytest.raises(IntegrityError):
        await make_auth_session(session, user, **overrides)


async def test_only_one_unused_refresh_per_session(session: AsyncSession) -> None:
    user = await make_user(session)
    device = await make_auth_session(session, user)
    await make_refresh_token(session, device)

    with pytest.raises(IntegrityError):
        await make_refresh_token(session, device)


async def test_refresh_hashes_unique_across_sessions(session: AsyncSession) -> None:
    user = await make_user(session)
    first = await make_auth_session(session, user)
    second = await make_auth_session(session, user)
    token = await make_refresh_token(session, first)

    with pytest.raises(IntegrityError):
        await make_refresh_token(session, second, token_hash=token.token_hash)


@pytest.mark.parametrize("digest", ["plaintext-refresh-token", "A" * 64, "a" * 63, ""])
async def test_refresh_hash_must_be_lowercase_sha256(session: AsyncSession, digest: str) -> None:
    user = await make_user(session)
    device = await make_auth_session(session, user)

    with pytest.raises(IntegrityError):
        await make_refresh_token(session, device, token_hash=digest)


async def test_rotation_preserves_device_id_and_used_token_history(session: AsyncSession) -> None:
    user = await make_user(session)
    device = await make_auth_session(session, user)
    original_id = device.id
    old = await make_refresh_token(session, device)
    old.used_at = NOW + timedelta(minutes=1)
    await session.flush()
    new = await make_refresh_token(session, device, created_at=old.used_at)
    old.replaced_by_id = new.id
    device.last_used_at = old.used_at
    await session.flush()

    history = (await session.scalars(select(RefreshToken))).all()
    active = (
        await session.scalars(select(RefreshToken).where(RefreshToken.used_at.is_(None)))
    ).all()

    assert len(history) == 2
    assert active == [new]
    assert device.id == original_id
    assert old.replaced_by_id == new.id
    assert new.expires_at == device.expires_at


@pytest.mark.parametrize("field", ["expires_at", "used_at"])
async def test_refresh_rejects_invalid_times(session: AsyncSession, field: str) -> None:
    user = await make_user(session)
    device = await make_auth_session(session, user)

    with pytest.raises(IntegrityError):
        await make_refresh_token(session, device, **{field: NOW - timedelta(seconds=1)})


async def test_refresh_cannot_replace_itself(session: AsyncSession) -> None:
    user = await make_user(session)
    device = await make_auth_session(session, user)
    token = await make_refresh_token(session, device)
    token.used_at = NOW
    token.replaced_by_id = token.id

    with pytest.raises(IntegrityError):
        await session.flush()


async def test_replacement_requires_used_predecessor(session: AsyncSession) -> None:
    user = await make_user(session)
    device = await make_auth_session(session, user)
    old = await make_refresh_token(session, device, used_at=NOW)
    new = await make_refresh_token(session, device)
    old.replaced_by_id = new.id
    old.used_at = None

    with pytest.raises(IntegrityError):
        await session.flush()


async def test_email_token_purposes_coexist(session: AsyncSession) -> None:
    user = await make_user(session)
    verification = await make_email_token(session, user)
    reset = await make_email_token(session, user, purpose=EmailTokenPurpose.RESET_PASSWORD)

    assert verification.purpose is EmailTokenPurpose.VERIFY_EMAIL
    assert reset.purpose is EmailTokenPurpose.RESET_PASSWORD
    assert verification.token_hash != reset.token_hash
    assert verification.used_at is None


async def test_email_hash_unique_across_purposes(session: AsyncSession) -> None:
    user = await make_user(session)
    token = await make_email_token(session, user)

    with pytest.raises(IntegrityError):
        await make_email_token(
            session,
            user,
            purpose=EmailTokenPurpose.RESET_PASSWORD,
            token_hash=token.token_hash,
        )


@pytest.mark.parametrize("digest", ["plaintext-email-token", "A" * 64, "a" * 63, ""])
async def test_email_hash_must_be_lowercase_sha256(session: AsyncSession, digest: str) -> None:
    user = await make_user(session)

    with pytest.raises(IntegrityError):
        await make_email_token(session, user, token_hash=digest)


@pytest.mark.parametrize("field", ["expires_at", "used_at"])
async def test_email_token_rejects_invalid_times(session: AsyncSession, field: str) -> None:
    user = await make_user(session)

    with pytest.raises(IntegrityError):
        await make_email_token(session, user, **{field: NOW - timedelta(seconds=1)})


async def test_deleting_session_cascades_rotation_history(session: AsyncSession) -> None:
    user = await make_user(session)
    device = await make_auth_session(session, user)
    old = await make_refresh_token(session, device, used_at=NOW)
    new = await make_refresh_token(session, device)
    old.replaced_by_id = new.id
    await session.flush()
    await session.execute(delete(AuthSession).where(AuthSession.id == device.id))

    assert await session.scalar(select(func.count()).select_from(RefreshToken)) == 0


async def test_deleting_user_cascades_all_auth_data(session: AsyncSession) -> None:
    user = await make_user(session)
    device = await make_auth_session(session, user)
    await make_refresh_token(session, device)
    await make_email_token(session, user)
    await make_email_token(session, user, purpose=EmailTokenPurpose.RESET_PASSWORD)
    await session.execute(delete(User).where(User.id == user.id))

    for model in (AuthSession, RefreshToken, EmailToken):
        assert await session.scalar(select(func.count()).select_from(model)) == 0
