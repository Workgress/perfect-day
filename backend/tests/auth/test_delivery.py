from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock

import pytest
from celery.exceptions import Retry
from kombu.exceptions import OperationalError

from app.core.config import Env, Settings
from app.modules.auth.delivery import (
    CeleryPasswordResetPublisher,
    CeleryVerificationPublisher,
    VerificationPublishError,
)
from app.workers import email as email_worker


@pytest.mark.parametrize("reset", [False, True])
async def test_publisher_masks_arguments_and_does_not_store_results(
    monkeypatch: pytest.MonkeyPatch,
    reset: bool,
) -> None:
    publish = Mock()
    task = email_worker.send_password_reset_email if reset else email_worker.send_verification_email
    publisher = CeleryPasswordResetPublisher() if reset else CeleryVerificationPublisher()
    monkeypatch.setattr(task, "apply_async", publish)
    expires_at = datetime.now(UTC) + timedelta(hours=24)

    await publisher.publish("user@example.com", "private-token", expires_at)

    options = publish.call_args.kwargs
    assert options["args"] == ["user@example.com", "private-token"]
    assert options["expires"] == expires_at
    assert options["ignore_result"]
    assert not options["retry"]
    assert "private-token" not in options["argsrepr"]
    assert "user@example.com" not in options["argsrepr"]


@pytest.mark.parametrize("reset", [False, True])
async def test_publisher_hides_broker_connection_details(
    monkeypatch: pytest.MonkeyPatch, reset: bool
) -> None:
    task = email_worker.send_password_reset_email if reset else email_worker.send_verification_email
    publisher = CeleryPasswordResetPublisher() if reset else CeleryVerificationPublisher()
    monkeypatch.setattr(
        task,
        "apply_async",
        Mock(side_effect=OperationalError("private-host")),
    )

    with pytest.raises(VerificationPublishError) as error:
        await publisher.publish(
            "user@example.com", "private-token", datetime.now(UTC) + timedelta(hours=24)
        )

    assert "private-host" not in str(error.value)


@pytest.mark.parametrize("reset", [False, True])
async def test_email_uses_frontend_fragment_and_russian_template(
    monkeypatch: pytest.MonkeyPatch,
    reset: bool,
) -> None:
    settings = Settings(_env_file=None, env=Env.TEST)
    mailer = Mock()
    mailer.send_message = AsyncMock()
    factory = Mock(return_value=mailer)
    monkeypatch.setattr(email_worker, "get_settings", lambda: settings)
    monkeypatch.setattr(email_worker, "FastMail", factory)

    sender = (
        email_worker.send_password_reset_message
        if reset
        else email_worker.send_verification_message
    )
    await sender("user@example.com", "private-token")

    message = mailer.send_message.call_args.args[0]
    assert message.template_body["reset_url" if reset else "verification_url"] == (
        f"http://localhost:5173/{'reset-password' if reset else 'verify-email'}#token=private-token"
    )
    assert ("Сброс пароля" if reset else "Подтвердите email") in message.subject
    assert mailer.send_message.call_args.kwargs["template_name"] == (
        "reset_password.html" if reset else "verify_email.html"
    )
    assert factory.call_args.args[0].MAIL_DEBUG == 0
    assert factory.call_args.args[0].VALIDATE_CERTS


@pytest.mark.parametrize("reset", [False, True])
def test_email_retry_keeps_arguments_hidden(monkeypatch: pytest.MonkeyPatch, reset: bool) -> None:
    sender = AsyncMock(side_effect=ValueError("private-token private-email@example.com"))
    retry = Mock(side_effect=Retry())
    task = email_worker.send_password_reset_email if reset else email_worker.send_verification_email
    name = "send_password_reset_message" if reset else "send_verification_message"
    monkeypatch.setattr(email_worker, name, sender)
    monkeypatch.setattr(task, "retry", retry)

    with pytest.raises(Retry):
        task.run("private-email@example.com", "private-token")

    options = retry.call_args.kwargs
    assert options["max_retries"] == 3
    assert "private-token" not in options["argsrepr"]
    assert "private-email@example.com" not in options["argsrepr"]
    assert str(options["exc"]) == (
        "Не удалось отправить письмо сброса пароля"
        if reset
        else "Не удалось отправить письмо подтверждения"
    )
    assert options["exc"].__suppress_context__
    assert task.ignore_result
    assert not task.store_errors_even_if_ignored
