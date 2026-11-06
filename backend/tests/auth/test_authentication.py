from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import uuid4

import pytest
from fastapi import Depends
from httpx import ASGITransport, AsyncClient

from app.core.errors import AppError
from app.core.security import get_current_user, validate_authentication_state
from app.main import create_app
from app.modules.auth.models import AuthSession
from app.modules.users.models import User


@pytest.mark.parametrize(
    ("state", "status"),
    [
        ("user-missing", 401),
        ("session-missing", 401),
        ("foreign-session", 401),
        ("inactive", 401),
        ("deleted", 401),
        ("revoked", 401),
        ("expired", 401),
        ("unverified", 403),
    ],
)
def test_authentication_rejects_invalid_user_or_session(state: str, status: int) -> None:
    now = datetime.now(UTC)
    user = User(id=uuid4(), email="user@example.com", password_hash="hash")
    user.is_active = state != "inactive"
    user.is_email_verified = state != "unverified"
    user.deleted_at = now if state == "deleted" else None
    device = AuthSession(
        id=uuid4(),
        user_id=uuid4() if state == "foreign-session" else user.id,
        expires_at=now if state == "expired" else now + timedelta(days=30),
        revoked_at=now if state == "revoked" else None,
    )

    with pytest.raises(AppError) as error:
        validate_authentication_state(
            None if state == "user-missing" else user,
            None if state == "session-missing" else device,
            now,
        )

    assert error.value.status_code == status


async def test_current_user_can_be_overridden_by_other_modules_without_database() -> None:
    app = create_app()
    user = User(id=uuid4(), email="user@example.com", password_hash="hash")
    app.dependency_overrides[get_current_user] = lambda: user

    @app.get("/test/current-user")
    async def current_user(user: Annotated[User, Depends(get_current_user)]) -> dict[str, str]:
        return {"id": str(user.id)}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/test/current-user")

    assert response.status_code == 200
    assert response.json() == {"id": str(user.id)}


async def test_openapi_describes_form_login_and_bearer_only_protected_routes() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        schema = (await client.get("/openapi.json")).json()

    paths = schema["paths"]
    assert (
        "application/x-www-form-urlencoded"
        in paths["/api/v1/auth/login"]["post"]["requestBody"]["content"]
    )
    assert paths["/api/v1/auth/sessions"]["get"]["security"] == [{"OAuth2PasswordBearer": []}]
    assert paths["/api/v1/auth/logout-all"]["post"]["security"] == [{"OAuth2PasswordBearer": []}]
    assert "security" not in paths["/api/v1/auth/refresh"]["post"]
    assert (
        schema["components"]["securitySchemes"]["OAuth2PasswordBearer"]["flows"]["password"][
            "tokenUrl"
        ]
        == "/api/v1/auth/login"
    )
    assert set(schema["components"]["schemas"]["TokenResponse"]["properties"]) == {
        "access_token",
        "token_type",
        "expires_in",
    }

    routes = {
        ("post", "register"): 202,
        ("post", "resend-verification"): 202,
        ("post", "verify-email"): 200,
        ("post", "login"): 200,
        ("post", "refresh"): 200,
        ("post", "logout"): 204,
        ("post", "logout-all"): 204,
        ("get", "sessions"): 200,
        ("delete", "sessions/{session_id}"): 204,
        ("post", "password/forgot"): 202,
        ("post", "password/reset"): 204,
        ("post", "password/change"): 204,
    }
    protected = {"sessions", "sessions/{session_id}", "logout-all", "password/change"}
    for (method, path), status in routes.items():
        operation = paths[f"/api/v1/auth/{path}"][method]
        assert str(status) in operation["responses"]
        if status == 204:
            assert "content" not in operation["responses"]["204"]
        assert operation.get("security", []) == (
            [{"OAuth2PasswordBearer": []}] if path in protected else []
        )
        for error_status in (400, 401, 403, 422, 429, 503):
            assert operation["responses"][str(error_status)]["content"]["application/json"][
                "schema"
            ] == {"$ref": "#/components/schemas/ErrorResponse"}
    refresh = paths["/api/v1/auth/refresh"]["post"]
    assert "requestBody" not in refresh
    assert any(
        parameter["name"] == "refresh_token" and parameter["in"] == "cookie"
        for parameter in refresh["parameters"]
    )
    for path in ("password/forgot", "password/reset", "password/change"):
        assert set(paths[f"/api/v1/auth/{path}"]["post"]["requestBody"]["content"]) == {
            "application/json"
        }


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "login"),
        ("GET", "sessions"),
        ("DELETE", f"sessions/{uuid4()}"),
        ("POST", "password/change"),
    ],
)
async def test_browser_can_preflight_auth_requests_with_credentials(method: str, path: str) -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.options(
            f"/api/v1/auth/{path}",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": method,
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert response.headers["access-control-allow-credentials"] == "true"
    assert method in response.headers["access-control-allow-methods"]
    assert "origin" in response.headers["vary"].lower()
