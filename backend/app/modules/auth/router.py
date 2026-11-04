from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from app.core.config import Settings, get_settings
from app.core.csrf import require_trusted_origin
from app.modules.auth.cookies import set_refresh_cookie
from app.modules.auth.dependencies import (
    client_ip,
    get_auth_service,
    limit_registration,
    limit_resend,
    limit_verification,
)
from app.modules.auth.schemas import (
    EmailRequest,
    MessageResponse,
    RegisterRequest,
    TokenResponse,
    VerifyEmailRequest,
)
from app.modules.auth.service import AuthService

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
    dependencies=[Depends(require_trusted_origin)],
)

NEUTRAL_MESSAGE = "Если действие доступно для указанного адреса, письмо будет отправлено"


@router.post(
    "/register",
    status_code=202,
    response_model=MessageResponse,
    dependencies=[Depends(limit_registration)],
    summary="Регистрация с подтверждением email",
    description=(
        "Создаёт учётную запись и ставит письмо в очередь. "
        "Ответ не раскрывает наличие адреса. Требуется доверенный Origin или Referer."
    ),
)
async def register(
    body: RegisterRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> MessageResponse:
    await service.register(str(body.email), body.password.get_secret_value())
    return MessageResponse(message=NEUTRAL_MESSAGE)


@router.post(
    "/resend-verification",
    status_code=202,
    response_model=MessageResponse,
    dependencies=[Depends(limit_resend)],
    summary="Повторная отправка подтверждения email",
    description=(
        "Аннулирует предыдущую ссылку. Доступно не чаще одного раза в 60 секунд на адрес. "
        "Требуется доверенный Origin или Referer."
    ),
)
async def resend_verification(
    body: EmailRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> MessageResponse:
    await service.resend_verification(str(body.email))
    return MessageResponse(message=NEUTRAL_MESSAGE)


@router.post(
    "/verify-email",
    response_model=TokenResponse,
    dependencies=[Depends(limit_verification)],
    summary="Подтверждение email и создание сессии",
    description=(
        "Принимает токен из письма один раз, возвращает access и устанавливает httpOnly "
        "refresh-cookie. Требуется доверенный Origin или Referer."
    ),
    responses={
        200: {
            "headers": {
                "Set-Cookie": {
                    "description": "Host-only refresh-cookie с HttpOnly и SameSite=Strict",
                    "schema": {"type": "string"},
                },
                "Cache-Control": {"schema": {"type": "string", "const": "no-store"}},
            }
        }
    },
)
async def verify_email(
    body: VerifyEmailRequest,
    request: Request,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    issued = await service.verify_email(
        body.token.get_secret_value(), client_ip(request), request.headers.get("user-agent")
    )
    set_refresh_cookie(response, issued.refresh_token, issued.expires_at, settings)
    return TokenResponse(access_token=issued.access_token, expires_in=issued.expires_in)
