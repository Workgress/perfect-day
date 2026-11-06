import base64
import hashlib
from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import Mock
from uuid import uuid4

import jwt
import pytest
from pydantic import SecretStr

from app.core import security
from app.core.config import Env, Settings
from app.core.security import (
    InvalidAccessTokenError,
    PasswordPolicyError,
    create_access_token,
    decode_access_token,
    generate_token,
    hash_password,
    hash_token,
    validate_password,
    verify_password,
)

TEST_SECRET = "auth-tests-secret-with-at-least-32-bytes-and-48-bytes-for-hs384"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None, env=Env.TEST, jwt_secret=SecretStr(TEST_SECRET), access_ttl_min=15
    )


@pytest.mark.parametrize("password", ["a1short", "abcdefgh", "12345678", "a1" + "x" * 127])
async def test_hash_rejects_invalid_passwords(password: str) -> None:
    with pytest.raises(PasswordPolicyError):
        await hash_password(password)


@pytest.mark.parametrize("password", ["Valid123", "Пароль123", "a1" + "x" * 126, " space123 "])
def test_password_policy_accepts_boundaries_and_preserves_input(password: str) -> None:
    assert validate_password(password) == password


async def test_password_hashes_are_salted_and_verifiable() -> None:
    first = await hash_password("Valid123")
    second = await hash_password("Valid123")

    assert first.startswith("$argon2id$")
    assert first != second
    assert "Valid123" not in first
    assert await verify_password("Valid123", first)
    assert not await verify_password("Wrong123", first)
    assert not await verify_password("valid123", first)


async def test_password_whitespace_is_significant() -> None:
    hashed = await hash_password(" space123 ")

    assert await verify_password(" space123 ", hashed)
    assert not await verify_password("space123", hashed)


@pytest.mark.parametrize("hashed", ["not-a-hash", "$argon2id$broken", ""])
async def test_invalid_hash_does_not_raise(hashed: str) -> None:
    assert not await verify_password("Valid123", hashed)


async def test_oversized_password_is_rejected_before_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verifier = Mock(side_effect=AssertionError("Expensive verification must not run"))
    monkeypatch.setattr(security._password_hash, "verify", verifier)

    assert not await verify_password("x" * 129, "unused")
    verifier.assert_not_called()


async def test_password_work_runs_outside_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio
    import threading

    loop_thread = threading.get_ident()

    def hash_in_thread(password: str) -> str:
        assert threading.get_ident() != loop_thread
        with pytest.raises(RuntimeError):
            asyncio.get_running_loop()
        return "hashed"

    def verify_in_thread(password: str, hashed: str) -> bool:
        assert threading.get_ident() != loop_thread
        return True

    monkeypatch.setattr(security._password_hash, "hash", hash_in_thread)
    monkeypatch.setattr(security._password_hash, "verify", verify_in_thread)

    assert await hash_password("Valid123") == "hashed"
    assert await verify_password("Valid123", "hashed")


def test_opaque_tokens_have_256_bits_and_hashes_do_not_store_plaintext() -> None:
    token = generate_token()
    second = generate_token()
    digest = hash_token(token)

    assert token != second
    assert len(base64.urlsafe_b64decode(token + "=")) == 32
    assert digest == hashlib.sha256(token.encode()).hexdigest()
    assert len(digest) == 64
    assert digest != token
    assert hash_token(token + " ") != digest


def test_jwt_round_trip_and_lifetime(settings: Settings) -> None:
    user_id, session_id = uuid4(), uuid4()
    now = datetime.now(UTC)
    token = create_access_token(user_id, session_id, settings, now=now)
    claims = decode_access_token(token, settings)

    assert claims.sub == user_id
    assert claims.sid == session_id
    assert claims.iat == int(now.timestamp())
    assert claims.exp - claims.iat == 900


def test_jwt_respects_configured_lifetime(settings: Settings) -> None:
    settings.access_ttl_min = 5
    claims = decode_access_token(create_access_token(uuid4(), uuid4(), settings), settings)

    assert claims.exp - claims.iat == 300


def test_jwt_normalizes_timezone(settings: Settings) -> None:
    now = datetime.now(timezone(timedelta(hours=5)))
    claims = decode_access_token(create_access_token(uuid4(), uuid4(), settings, now=now), settings)

    assert claims.iat == int(now.astimezone(UTC).timestamp())


def test_jwt_rejects_naive_issuance_time(settings: Settings) -> None:
    with pytest.raises(ValueError, match="часовой пояс"):
        create_access_token(uuid4(), uuid4(), settings, now=datetime(2026, 11, 4))


@pytest.mark.parametrize("offset", [timedelta(days=-1), timedelta(hours=1)])
def test_jwt_rejects_expired_or_future_tokens(settings: Settings, offset: timedelta) -> None:
    token = create_access_token(uuid4(), uuid4(), settings, now=datetime.now(UTC) + offset)

    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(token, settings)


def test_jwt_rejects_wrong_secret(settings: Settings) -> None:
    token = create_access_token(uuid4(), uuid4(), settings)
    settings.jwt_secret = SecretStr("a-different-test-secret-with-32-bytes")

    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(token, settings)


def test_jwt_rejects_modified_payload(settings: Settings) -> None:
    token = create_access_token(uuid4(), uuid4(), settings)
    header, _payload, signature = token.split(".")
    replacement = base64.urlsafe_b64encode(b'{"sub":"attacker"}').rstrip(b"=").decode()

    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(f"{header}.{replacement}.{signature}", settings)


@pytest.mark.parametrize("algorithm", ["none", "HS384"])
def test_jwt_rejects_unapproved_algorithm(settings: Settings, algorithm: str) -> None:
    now = int(datetime.now(UTC).timestamp())
    payload = {"sub": str(uuid4()), "sid": str(uuid4()), "iat": now, "exp": now + 900}
    token = jwt.encode(payload, "" if algorithm == "none" else TEST_SECRET, algorithm=algorithm)

    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(token, settings)


@pytest.mark.parametrize("missing", ["sub", "sid", "iat", "exp"])
def test_jwt_requires_all_claims(settings: Settings, missing: str) -> None:
    now = int(datetime.now(UTC).timestamp())
    payload = {"sub": str(uuid4()), "sid": str(uuid4()), "iat": now, "exp": now + 900}
    del payload[missing]
    token = jwt.encode(payload, TEST_SECRET, algorithm="HS256")

    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(token, settings)


@pytest.mark.parametrize(
    ("claim", "value"),
    [("sub", "not-a-uuid"), ("sid", "not-a-uuid"), ("sid", None), ("iat", "1"), ("iat", True)],
)
def test_jwt_rejects_invalid_claim_types(settings: Settings, claim: str, value: object) -> None:
    now = int(datetime.now(UTC).timestamp())
    payload = {"sub": str(uuid4()), "sid": str(uuid4()), "iat": now, "exp": now + 900}
    payload[claim] = value
    token = jwt.encode(payload, TEST_SECRET, algorithm="HS256")

    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(token, settings)


def test_jwt_rejects_expiration_before_issuance(settings: Settings) -> None:
    now = int(datetime.now(UTC).timestamp())
    token = jwt.encode(
        {"sub": str(uuid4()), "sid": str(uuid4()), "iat": now + 1, "exp": now},
        TEST_SECRET,
        algorithm="HS256",
    )

    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(token, settings)


@pytest.mark.parametrize("token", ["", "not-a-jwt", "a.b.c"])
def test_malformed_jwt_uses_safe_error(settings: Settings, token: str) -> None:
    with pytest.raises(InvalidAccessTokenError, match="Недействительный access-токен"):
        decode_access_token(token, settings)


def test_jwt_functions_require_configured_secret(settings: Settings) -> None:
    settings.jwt_secret = None

    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        create_access_token(uuid4(), uuid4(), settings)
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        decode_access_token("unused", settings)
