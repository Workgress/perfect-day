import asyncio
from pathlib import Path
from urllib.parse import urlencode

from fastapi_mail import ConnectionConfig, FastMail, MessageSchema

from app.core.config import get_settings
from app.workers.celery_app import celery_app

TEMPLATE_FOLDER = Path(__file__).resolve().parent / "templates"


class MailDeliveryError(Exception):
    pass


async def send_token_message(email: str, token: str, *, password_reset: bool = False) -> None:
    settings = get_settings()
    configuration = ConnectionConfig.model_validate(
        {
            "MAIL_USERNAME": settings.smtp_username,
            "MAIL_PASSWORD": settings.smtp_password,
            "MAIL_FROM": settings.smtp_from,
            "MAIL_FROM_NAME": settings.app_name,
            "MAIL_PORT": settings.smtp_port,
            "MAIL_SERVER": settings.smtp_host,
            "MAIL_STARTTLS": settings.smtp_starttls,
            "MAIL_SSL_TLS": settings.smtp_ssl_tls,
            "USE_CREDENTIALS": bool(settings.smtp_username),
            "VALIDATE_CERTS": True,
            "MAIL_DEBUG": 0,
            "TIMEOUT": 10,
            "TEMPLATE_FOLDER": TEMPLATE_FOLDER,
        }
    )
    path = "reset-password" if password_reset else "verify-email"
    link = f"{str(settings.frontend_url).rstrip('/')}/{path}#{urlencode({'token': token})}"
    message = MessageSchema.model_validate(
        {
            "subject": (
                "Сброс пароля — Идеальный День"
                if password_reset
                else "Подтвердите email — Идеальный День"
            ),
            "recipients": [email],
            "subtype": "html",
            "template_body": {
                "verification_url": link,
                "reset_url": link,
                "hours": settings.email_verification_ttl_hours,
                "minutes": settings.password_reset_ttl_min,
            },
        }
    )
    template = "reset_password.html" if password_reset else "verify_email.html"
    await FastMail(configuration).send_message(message, template_name=template)


async def send_verification_message(email: str, token: str) -> None:
    await send_token_message(email, token)


async def send_password_reset_message(email: str, token: str) -> None:
    await send_token_message(email, token, password_reset=True)


@celery_app.task(
    name="auth.send_verification_email",
    ignore_result=True,
    store_errors_even_if_ignored=False,
    autoretry_for=(MailDeliveryError,),
    retry_kwargs={
        "max_retries": 3,
        "argsrepr": "(<скрыто>, <скрыто>)",
        "kwargsrepr": "{}",
    },
    retry_backoff=5,
    retry_backoff_max=60,
    retry_jitter=True,
)
def send_verification_email(email: str, token: str) -> None:
    try:
        asyncio.run(send_verification_message(email, token))
    except Exception:
        raise MailDeliveryError("Не удалось отправить письмо подтверждения") from None


@celery_app.task(
    name="auth.send_password_reset_email",
    ignore_result=True,
    store_errors_even_if_ignored=False,
    autoretry_for=(MailDeliveryError,),
    retry_kwargs={"max_retries": 3, "argsrepr": "(<скрыто>, <скрыто>)", "kwargsrepr": "{}"},
    retry_backoff=5,
    retry_backoff_max=60,
    retry_jitter=True,
)
def send_password_reset_email(email: str, token: str) -> None:
    try:
        asyncio.run(send_password_reset_message(email, token))
    except Exception:
        raise MailDeliveryError("Не удалось отправить письмо сброса пароля") from None
