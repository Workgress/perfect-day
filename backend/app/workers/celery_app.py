from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "perfect_day",
    broker=settings.redis_dsn(settings.redis_broker_db),
    backend=settings.redis_dsn(settings.redis_result_db),
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    result_expires=3600,
    broker_connection_retry_on_startup=True,
)


@celery_app.task(name="ping")
def ping() -> str:
    return "pong"
