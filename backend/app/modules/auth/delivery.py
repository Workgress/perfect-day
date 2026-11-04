from datetime import datetime
from typing import Protocol

from kombu.exceptions import KombuError
from starlette.concurrency import run_in_threadpool

from app.workers.email import send_verification_email


class VerificationPublishError(Exception):
    pass


class VerificationPublisher(Protocol):
    async def publish(self, email: str, token: str, expires_at: datetime) -> None: ...


class CeleryVerificationPublisher:
    async def publish(self, email: str, token: str, expires_at: datetime) -> None:
        try:
            await run_in_threadpool(
                send_verification_email.apply_async,
                args=[email, token],
                argsrepr="(<скрыто>, <скрыто>)",
                kwargsrepr="{}",
                expires=expires_at,
                retry=False,
                ignore_result=True,
            )
        except (KombuError, OSError):
            raise VerificationPublishError("Очередь отправки временно недоступна") from None


def get_verification_publisher() -> VerificationPublisher:
    return CeleryVerificationPublisher()
