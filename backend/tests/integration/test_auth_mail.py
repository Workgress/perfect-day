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

from app.modules.auth.delivery import CeleryVerificationPublisher, get_verification_publisher
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

    results: Redis = Redis.from_url(f"{redis_url}/5")
    try:
        assert [key async for key in results.scan_iter("celery-task-meta-*")] == []
    finally:
        await results.aclose()
