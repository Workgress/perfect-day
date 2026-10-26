from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import app


async def test_openapi_available() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/openapi.json")

    assert response.status_code == 200
    assert "/api/v1/health" in response.json()["paths"]


async def test_cors_allows_frontend_origin() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.options(
            "/api/v1/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


async def test_cors_rejects_unknown_origin() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.options(
            "/api/v1/health",
            headers={
                "Origin": "http://evil.example",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert "access-control-allow-origin" not in response.headers


def test_cors_origins_parsed_from_env(monkeypatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", '["https://a.example","https://b.example"]')

    assert Settings().cors_origins == ["https://a.example", "https://b.example"]
