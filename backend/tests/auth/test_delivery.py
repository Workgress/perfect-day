from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock

import pytest
from celery.exceptions import Retry
from kombu.exceptions import OperationalError

from app.core.config import Env, Settings
from app.modules.auth.delivery import CeleryVerificationPublisher, VerificationPublishError
from app.workers import email as email_worker


async def test_publisher_masks_arguments_and_does_not_store_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publish = Mock()
    monkeypatch.setattr(email_worker.send_verification_email, "apply_async", publish)
    expires_at = datetime.now(UTC) + timedelta(hours=24)

    await CeleryVerificationPublisher().publish("user@example.com", "private-token", expires_at)

    options = publish.call_args.kwargs
    assert options["args"] == ["user@example.com", "private-token"]
    assert options["expires"] == expires_at
    assert options["ignore_result"]
    assert not options["retry"]
    assert "private-token" not in options["argsrepr"]
    assert "user@example.com" not in options["argsrepr"]


async def test_publisher_hides_broker_connection_details(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        email_worker.send_verification_email,
        "apply_async",
        Mock(side_effect=OperationalError("private-host")),
    )

    with pytest.raises(VerificationPublishError) as error:
        await CeleryVerificationPublisher().publish(
            "user@example.com", "private-token", datetime.now(UTC) + timedelta(hours=24)
        )

    assert "private-host" not in str(error.value)


async def test_email_uses_frontend_fragment_and_russian_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(_env_file=None, env=Env.TEST)
    mailer = Mock()
    mailer.send_message = AsyncMock()
    factory = Mock(return_value=mailer)
    monkeypatch.setattr(email_worker, "get_settings", lambda: settings)
    monkeypatch.setattr(email_worker, "FastMail", factory)

    await email_worker.send_verification_message("user@example.com", "private-token")

    message = mailer.send_message.call_args.args[0]
    assert message.template_body["verification_url"] == (
        "http://localhost:5173/verify-email#token=private-token"
    )
    assert "Подтвердите email" in message.subject
    assert mailer.send_message.call_args.kwargs["template_name"] == "verify_email.html"
    assert factory.call_args.args[0].MAIL_DEBUG == 0
    assert factory.call_args.args[0].VALIDATE_CERTS


def test_email_retry_keeps_arguments_hidden(monkeypatch: pytest.MonkeyPatch) -> None:
    sender = AsyncMock(side_effect=ValueError("private-token private-email@example.com"))
    retry = Mock(side_effect=Retry())
    monkeypatch.setattr(email_worker, "send_verification_message", sender)
    monkeypatch.setattr(email_worker.send_verification_email, "retry", retry)

    with pytest.raises(Retry):
        email_worker.send_verification_email.run("private-email@example.com", "private-token")

    options = retry.call_args.kwargs
    assert options["max_retries"] == 3
    assert "private-token" not in options["argsrepr"]
    assert "private-email@example.com" not in options["argsrepr"]
    assert str(options["exc"]) == "Не удалось отправить письмо подтверждения"
    assert options["exc"].__suppress_context__
    assert email_worker.send_verification_email.ignore_result
    assert not email_worker.send_verification_email.store_errors_even_if_ignored
