import asyncio
from collections.abc import Iterator
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

import pytest
from celery.contrib.testing.worker import start_worker
from httpx import AsyncClient
from redis.asyncio import Redis
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import HttpWaitStrategy

from app.modules.auth.delivery import (
    CeleryPasswordResetPublisher,
    CeleryVerificationPublisher,
    get_password_reset_publisher,
    get_verification_publisher,
)
from app.workers import email as email_module
from app.workers.celery_app import celery_app
from tests.integration.test_auth import AuthAPI
from tests.integration.test_auth import alembic_config as alembic_config
from tests.integration.test_auth import auth_api as auth_api
from tests.integration.test_auth import engine as engine
from tests.integration.test_auth import migrated_url as migrated_url

pytestmark = pytest.mark.docker


@dataclass
class Mailpit:
    host: str
    smtp_port: int
    http_url: str


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self.links.extend(value for key, value in attrs if key == "href" and value is not None)


@pytest.fixture
def mailpit() -> Iterator[Mailpit]:
    container = (
        DockerContainer("axllent/mailpit:latest")
        .with_exposed_ports(1025, 8025)
        .waiting_for(HttpWaitStrategy(8025).with_startup_timeout(30))
    )
    with container:
        host = container.get_container_host_ip()
        yield Mailpit(
            host,
            int(container.get_exposed_port(1025)),
            f"http://{host}:{container.get_exposed_port(8025)}",
        )


@pytest.fixture
def mail_worker(
    auth_api: AuthAPI,
    mailpit: Mailpit,
    redis_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    auth_api.settings.smtp_host = mailpit.host
    auth_api.settings.smtp_port = mailpit.smtp_port
    auth_api.app.dependency_overrides[get_verification_publisher] = CeleryVerificationPublisher
    auth_api.app.dependency_overrides[get_password_reset_publisher] = CeleryPasswordResetPublisher
    monkeypatch.setattr(email_module, "get_settings", lambda: auth_api.settings)
    monkeypatch.setattr(celery_app.conf, "broker_url", f"{redis_url}/4")
    monkeypatch.setattr(celery_app.conf, "result_backend", f"{redis_url}/5")
    with start_worker(
        celery_app,
        pool="solo",
        loglevel="ERROR",
        perform_ping_check=False,
        shutdown_timeout=15,
    ):
        yield


@pytest.mark.usefixtures("mail_worker")
async def test_registration_email_travels_through_celery_and_smtp(
    auth_api: AuthAPI,
    mailpit: Mailpit,
    redis_url: str,
) -> None:
    registration = await auth_api.register()
    assert registration.status_code == 202
    assert "set-cookie" not in registration.headers

    deadline = asyncio.get_running_loop().time() + 15
    async with AsyncClient(base_url=mailpit.http_url, timeout=3) as client:
        while True:
            message = await client.get("/view/latest.html")
            if message.status_code == 200:
                break
            assert asyncio.get_running_loop().time() < deadline, "Письмо не доставлено в Mailpit"
            await asyncio.sleep(0.2)

    assert "Добро пожаловать" in message.text
    assert "Подтвердить email" in message.text
    parser = LinkParser()
    parser.feed(message.text)
    link = next(link for link in parser.links if "/verify-email#" in link)
    parsed = urlsplit(link)
    assert parsed.scheme == "http"
    assert parsed.netloc == "localhost:5173"
    assert parsed.query == ""
    token = parse_qs(parsed.fragment)["token"][0]

    confirmation = await auth_api.verify(token)
    assert confirmation.status_code == 200
    assert confirmation.json()["token_type"] == "bearer"
    assert "refresh_token=" in confirmation.headers["set-cookie"]
    assert (await auth_api.verify(token)).status_code == 400

    forgot = await auth_api.client.post(
        "/api/v1/auth/password/forgot", json={"email": auth_api.email}
    )
    assert forgot.status_code == 202
    deadline = asyncio.get_running_loop().time() + 15
    async with AsyncClient(base_url=mailpit.http_url, timeout=3) as client:
        while True:
            message = await client.get("/view/latest.html")
            if message.status_code == 200 and "/reset-password#" in message.text:
                break
            assert asyncio.get_running_loop().time() < deadline, "Письмо сброса не доставлено"
            await asyncio.sleep(0.2)
    assert "Задать новый пароль" in message.text
    parser = LinkParser()
    parser.feed(message.text)
    link = next(link for link in parser.links if "/reset-password#" in link)
    parsed = urlsplit(link)
    assert parsed.netloc == "localhost:5173"
    assert parsed.query == ""
    reset_token = parse_qs(parsed.fragment)["token"][0]
    reset_body = {"token": reset_token, "new_password": "Changed456"}
    reset = await auth_api.client.post("/api/v1/auth/password/reset", json=reset_body)
    assert reset.status_code == 204
    assert (
        await auth_api.client.post("/api/v1/auth/password/reset", json=reset_body)
    ).status_code == 400
    assert (
        await auth_api.client.post(
            "/api/v1/auth/login", data={"username": auth_api.email, "password": "Changed456"}
        )
    ).status_code == 200

    results: Redis = Redis.from_url(f"{redis_url}/5")
    try:
        assert [key async for key in results.scan_iter("celery-task-meta-*")] == []
    finally:
        await results.aclose()
