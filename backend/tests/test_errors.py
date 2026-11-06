from collections.abc import AsyncIterator
from typing import Annotated

import pytest
from fastapi import FastAPI, HTTPException, Query
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, Field, field_validator

from app.core.errors import AppError
from app.main import create_app


class Credentials(BaseModel):
    password: str = Field(min_length=8)


class RequestBody(BaseModel):
    credentials: list[Credentials]


class CustomValidationBody(BaseModel):
    token: str

    @field_validator("token")
    @classmethod
    def reject_token(cls, value: str) -> str:
        raise ValueError(f"secret token: {value}")


@pytest.fixture
def error_app() -> FastAPI:
    app = create_app()
    app.debug = False

    @app.get("/test/domain-error")
    async def domain_error() -> None:
        raise AppError(
            409,
            "ONBOARDING_REQUIRED",
            "Завершите настройку профиля",
            details={"next_step": "profile"},
        )

    @app.get("/test/http-error/{status_code}")
    async def http_error(status_code: int) -> None:
        raise HTTPException(status_code, detail="private implementation detail")

    @app.get("/test/rate-limit")
    async def rate_limit() -> None:
        raise AppError(
            429,
            "RATE_LIMIT_EXCEEDED",
            "Повторите запрос позже",
            headers={"Retry-After": "60"},
        )

    @app.get("/test/challenge")
    async def challenge(header_name: str = "WWW-Authenticate") -> None:
        raise HTTPException(401, headers={header_name: 'Bearer realm="api"'})

    @app.post("/test/validation")
    async def validation(body: RequestBody, count: Annotated[int, Query(gt=0)]) -> None:
        return None

    @app.post("/test/custom-validation")
    async def custom_validation(body: CustomValidationBody) -> None:
        return None

    @app.get("/test/unexpected")
    async def unexpected() -> None:
        raise RuntimeError("database password: private-secret")

    return app


@pytest.fixture
async def client(error_app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=error_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_domain_error_preserves_public_contract(client: AsyncClient) -> None:
    response = await client.get("/test/domain-error")

    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "ONBOARDING_REQUIRED",
            "message": "Завершите настройку профиля",
            "details": {"next_step": "profile"},
        }
    }


@pytest.mark.parametrize(
    ("status_code", "code"),
    [
        (400, "BAD_REQUEST"),
        (401, "AUTHENTICATION_REQUIRED"),
        (403, "FORBIDDEN"),
        (404, "NOT_FOUND"),
        (409, "CONFLICT"),
        (429, "RATE_LIMIT_EXCEEDED"),
        (503, "SERVICE_UNAVAILABLE"),
    ],
)
async def test_http_errors_use_public_messages(
    client: AsyncClient,
    status_code: int,
    code: str,
) -> None:
    response = await client.get(f"/test/http-error/{status_code}")

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["details"] == {}
    assert "private implementation detail" not in response.text
    if status_code == 401:
        assert response.headers["www-authenticate"] == "Bearer"


async def test_missing_route_uses_error_envelope(client: AsyncClient) -> None:
    response = await client.get("/missing-route")

    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "NOT_FOUND", "message": "Ресурс не найден", "details": {}}
    }


async def test_method_not_allowed_preserves_allow_header(client: AsyncClient) -> None:
    response = await client.post("/api/v1/health")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "METHOD_NOT_ALLOWED"
    assert "GET" in response.headers["allow"]


@pytest.mark.parametrize("header_name", ["WWW-Authenticate", "www-authenticate"])
async def test_error_headers_are_preserved(client: AsyncClient, header_name: str) -> None:
    limited = await client.get("/test/rate-limit")
    challenge = await client.get("/test/challenge", params={"header_name": header_name})

    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "60"
    assert challenge.status_code == 401
    assert challenge.headers["www-authenticate"] == 'Bearer realm="api"'


async def test_validation_errors_have_safe_field_details(client: AsyncClient) -> None:
    response = await client.post(
        "/test/validation?count=not-a-number",
        json={"credentials": [{"password": "secret"}]},
    )

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "VALIDATION_ERROR",
            "message": "Ошибка проверки данных",
            "details": {
                "fields": [
                    {
                        "field": "query.count",
                        "code": "int_parsing",
                        "message": "Ожидается целое число",
                    },
                    {
                        "field": "body.credentials.0.password",
                        "code": "string_too_short",
                        "message": "Слишком короткая строка",
                    },
                ]
            },
        }
    }
    assert "secret" not in response.text
    assert "not-a-number" not in response.text


async def test_custom_validation_does_not_expose_input_or_context(client: AsyncClient) -> None:
    response = await client.post("/test/custom-validation", json={"token": "private-token"})

    assert response.status_code == 422
    assert response.json()["error"]["details"]["fields"] == [
        {
            "field": "body.token",
            "code": "value_error",
            "message": "Некорректное значение",
        }
    ]
    assert "private-token" not in response.text
    assert "secret token" not in response.text


async def test_invalid_json_is_reported_without_echoing_body(client: AsyncClient) -> None:
    response = await client.post(
        "/test/validation?count=1",
        content='{"credentials": "private-secret"',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["details"]["fields"][0]["code"] == "json_invalid"
    assert "private-secret" not in response.text


async def test_unexpected_errors_do_not_expose_exception(client: AsyncClient) -> None:
    response = await client.get("/test/unexpected")

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "INTERNAL_ERROR",
            "message": "Внутренняя ошибка сервера",
            "details": {},
        }
    }


async def test_openapi_describes_custom_validation_response(client: AsyncClient) -> None:
    response = await client.get("/openapi.json")
    schema = response.json()
    responses = schema["paths"]["/test/validation"]["post"]["responses"]

    assert response.status_code == 200
    assert responses["422"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse"
    }
    assert schema["components"]["schemas"]["ErrorBody"]["required"] == ["code", "message"]
