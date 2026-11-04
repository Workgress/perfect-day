import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Env, Settings


@pytest.fixture(autouse=True)
def clean_auth_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "JWT_SECRET",
        "ACCESS_TTL_MIN",
        "REFRESH_TTL_DAYS",
        "EMAIL_VERIFICATION_TTL_HOURS",
        "PASSWORD_RESET_TTL_MIN",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DEBUG", "false")


@pytest.mark.parametrize("env", [Env.LOCAL, Env.TEST])
def test_secret_optional_only_for_local_and_test(env: Env) -> None:
    assert Settings(_env_file=None, env=env).jwt_secret is None


@pytest.mark.parametrize("env", [Env.STAGING, Env.PRODUCTION])
def test_deployed_environment_requires_secret(env: Env) -> None:
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        Settings(_env_file=None, env=env)


@pytest.mark.parametrize("value", ["", "   "])
def test_blank_secret_is_unconfigured(value: str) -> None:
    assert Settings(_env_file=None, env=Env.LOCAL, jwt_secret=value).jwt_secret is None


def test_short_secret_rejected_without_echoing_value() -> None:
    secret = "short-secret"

    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, env=Env.TEST, jwt_secret=SecretStr(secret))

    assert secret not in str(error.value)


def test_secret_is_masked_in_settings_representation() -> None:
    secret = "valid-test-secret-that-has-32-bytes"
    settings = Settings(_env_file=None, env=Env.PRODUCTION, jwt_secret=SecretStr(secret))

    assert secret not in repr(settings)
    assert secret not in settings.model_dump_json()


@pytest.mark.parametrize(
    "name",
    [
        "access_ttl_min",
        "refresh_ttl_days",
        "email_verification_ttl_hours",
        "password_reset_ttl_min",
    ],
)
@pytest.mark.parametrize("value", [0, -1])
def test_token_lifetimes_must_be_positive(name: str, value: int) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, env=Env.TEST, **{name: value})


def test_auth_settings_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "valid-test-secret-that-has-32-bytes")
    monkeypatch.setenv("ACCESS_TTL_MIN", "10")
    monkeypatch.setenv("REFRESH_TTL_DAYS", "14")
    settings = Settings(_env_file=None, env=Env.TEST)

    assert settings.jwt_secret is not None
    assert settings.access_ttl_min == 10
    assert settings.refresh_ttl_days == 14
    assert settings.email_verification_ttl_hours == 24
    assert settings.password_reset_ttl_min == 60
