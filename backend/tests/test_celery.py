from app.workers.celery_app import celery_app, ping


def test_ping_task_runs_locally() -> None:
    assert ping.apply().get() == "pong"


def test_worker_settings() -> None:
    conf = celery_app.conf
    assert conf.task_acks_late is True
    assert conf.worker_prefetch_multiplier == 1
    assert conf.result_expires == 3600
    assert conf.broker_url.endswith("/1")
    assert conf.result_backend.endswith("/2")
