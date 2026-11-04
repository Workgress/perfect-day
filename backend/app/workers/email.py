import asyncio
from pathlib import Path
from urllib.parse import urlencode

from fastapi_mail import ConnectionConfig, FastMail, MessageSchema

from app.core.config import get_settings
from app.workers.celery_app import celery_app

TEMPLATE_FOLDER = Path(__file__).resolve().parent / "templates"


class MailDeliveryError(Exception):
    pass


async def send_verification_message(email: str, token: str) -> None:
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
    verification_url = (
        f"{str(settings.frontend_url).rstrip('/')}/verify-email#{urlencode({'token': token})}"
    )
    message = MessageSchema.model_validate(
        {
            "subject": "Подтвердите email — Идеальный День",
            "recipients": [email],
            "subtype": "html",
            "template_body": {
                "verification_url": verification_url,
                "hours": settings.email_verification_ttl_hours,
            },
        }
    )
    await FastMail(configuration).send_message(message, template_name="verify_email.html")


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
