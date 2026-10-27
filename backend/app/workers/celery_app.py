from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "perfect_day",
    broker=settings.redis_dsn(settings.redis_broker_db),
    backend=settings.redis_dsn(settings.redis_result_db),
)
