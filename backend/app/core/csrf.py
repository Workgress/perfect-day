from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Depends, Request

from app.core.config import Settings, get_settings
from app.core.errors import AppError


def require_trusted_origin(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    origin = request.headers.get("origin")
    if origin is None:
        referer = request.headers.get("referer", "")
        try:
            parsed = urlsplit(referer)
            origin = f"{parsed.scheme}://{parsed.netloc}"
        except ValueError:
            origin = ""
    if origin not in settings.cors_origins:
        raise AppError(403, "CSRF_ORIGIN_DENIED", "Источник запроса не разрешён")
