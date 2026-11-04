from datetime import UTC, datetime

from fastapi import Response

from app.core.config import Settings

REFRESH_COOKIE_NAME = "refresh_token"


def set_refresh_cookie(
    response: Response,
    token: str,
    expires_at: datetime,
    settings: Settings,
) -> None:
    max_age = max(int((expires_at - datetime.now(UTC)).total_seconds()), 0)
    response.set_cookie(
        REFRESH_COOKIE_NAME,
        token,
        max_age=max_age,
        expires=expires_at,
        path=f"{settings.api_prefix}/auth",
        secure=settings.secure_refresh_cookie,
        httponly=True,
        samesite="strict",
    )
    response.headers["Cache-Control"] = "no-store"
