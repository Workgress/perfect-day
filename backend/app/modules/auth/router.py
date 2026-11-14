from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, Request, Response
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.core.csrf import require_trusted_origin
from app.core.errors import AppError, ErrorResponse
from app.core.security import AuthContext, get_auth_context
from app.modules.auth.cookies import REFRESH_COOKIE_NAME, clear_refresh_cookie, set_refresh_cookie
from app.modules.auth.dependencies import (
    client_ip,
    get_auth_service,
    limit_change_password,
    limit_forgot_password,
    limit_login,
    limit_logout,
    limit_refresh,
    limit_registration,
    limit_resend,
    limit_reset_password,
    limit_verification,
)
from app.modules.auth.schemas import (
    ChangePasswordRequest,
    EmailRequest,
    MessageResponse,
    RegisterRequest,
    ResetPasswordRequest,
    SessionResponse,
    SessionsResponse,
    TokenResponse,
    VerifyEmailRequest,
)
from app.modules.auth.service import AuthService

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
)

NEUTRAL_MESSAGE = "Если действие доступно для указанного адреса, письмо будет отправлено"


@router.post(
    "/register",
    status_code=202,
    response_model=MessageResponse,
    responses={
        409: {"model": ErrorResponse, "description": "Аккаунт с этой почтой уже существует"}
    },
    dependencies=[Depends(require_trusted_origin), Depends(limit_registration)],
    summary="Регистрация с подтверждением email",
    description=(
        "Создаёт учётную запись и ставит письмо в очередь. "
        "Занятый email возвращает 409 EMAIL_ALREADY_EXISTS. "
        "Требуется доверенный Origin или Referer."
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
    dependencies=[Depends(require_trusted_origin), Depends(limit_resend)],
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
    dependencies=[Depends(require_trusted_origin), Depends(limit_verification)],
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


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(require_trusted_origin), Depends(limit_login)],
    summary="Вход по email и паролю",
    description=(
        "OAuth2 form: username содержит email. Доступно после подтверждения email. "
        "Access возвращается в JSON, refresh — только в httpOnly cookie. "
        "Требуется доверенный Origin или Referer."
    ),
)
async def login(
    request: Request,
    response: Response,
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    settings: Annotated[Settings, Depends(get_settings)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    try:
        email = str(EmailRequest.model_validate({"email": form.username}).email)
    except ValidationError:
        raise AppError(401, "INVALID_CREDENTIALS", "Неверный email или пароль") from None
    issued = await service.login(
        email, form.password, client_ip(request), request.headers.get("user-agent")
    )
    set_refresh_cookie(response, issued.refresh_token, issued.expires_at, settings)
    return TokenResponse(access_token=issued.access_token, expires_in=issued.expires_in)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    dependencies=[Depends(require_trusted_origin), Depends(limit_refresh)],
    summary="Обновление access и ротация refresh",
    description=(
        "Принимает refresh только из cookie. Повторное использование заменённого токена "
        "отзывает всю сессию. Общий срок сессии не продлевается. "
        "Требуется доверенный Origin или Referer."
    ),
)
async def refresh(
    request: Request,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
    service: Annotated[AuthService, Depends(get_auth_service)],
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE_NAME)] = None,
) -> TokenResponse:
    try:
        issued = await service.refresh(
            refresh_token, client_ip(request), request.headers.get("user-agent")
        )
    except AppError as error:
        if error.body.code == "INVALID_REFRESH_TOKEN":
            cleared = Response()
            clear_refresh_cookie(cleared, settings)
            error.headers = {
                **(error.headers or {}),
                "Set-Cookie": cleared.headers["set-cookie"],
                "Cache-Control": "no-store",
            }
        raise
    set_refresh_cookie(response, issued.refresh_token, issued.expires_at, settings)
    return TokenResponse(access_token=issued.access_token, expires_in=issued.expires_in)


@router.post(
    "/logout",
    status_code=204,
    dependencies=[Depends(require_trusted_origin), Depends(limit_logout)],
    summary="Выход с текущего устройства",
    description=(
        "Отзывает сессию по refresh-cookie. Повторный выход допустим. "
        "Требуется доверенный источник."
    ),
)
async def logout(
    settings: Annotated[Settings, Depends(get_settings)],
    service: Annotated[AuthService, Depends(get_auth_service)],
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE_NAME)] = None,
) -> Response:
    await service.logout(refresh_token)
    response = Response(status_code=204)
    clear_refresh_cookie(response, settings)
    return response


@router.post("/logout-all", status_code=204, summary="Выход со всех устройств")
async def logout_all(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    settings: Annotated[Settings, Depends(get_settings)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> Response:
    await service.logout_all(context)
    response = Response(status_code=204)
    clear_refresh_cookie(response, settings)
    return response


@router.get("/sessions", response_model=SessionsResponse, summary="Список активных устройств")
async def sessions(
    response: Response,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> SessionsResponse:
    devices = await service.sessions(context)
    response.headers["Cache-Control"] = "no-store"
    return SessionsResponse(
        items=[
            SessionResponse(
                id=device.id,
                created_at=device.created_at,
                expires_at=device.expires_at,
                last_used_at=device.last_used_at,
                ip=device.ip,
                user_agent=device.user_agent,
                is_current=device.id == context.session_id,
            )
            for device in devices
        ]
    )


@router.delete("/sessions/{session_id}", status_code=204, summary="Отзыв выбранного устройства")
async def revoke_session(
    session_id: UUID,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    settings: Annotated[Settings, Depends(get_settings)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> Response:
    is_current = await service.revoke_session(context, session_id)
    response = Response(status_code=204, headers={"Cache-Control": "no-store"})
    if is_current:
        clear_refresh_cookie(response, settings)
    return response


@router.post(
    "/password/forgot",
    status_code=202,
    response_model=MessageResponse,
    dependencies=[Depends(require_trusted_origin), Depends(limit_forgot_password)],
    summary="Запрос письма сброса пароля",
)
async def forgot_password(
    body: EmailRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> MessageResponse:
    await service.forgot_password(str(body.email))
    return MessageResponse(message=NEUTRAL_MESSAGE)


@router.post(
    "/password/reset",
    status_code=204,
    dependencies=[Depends(require_trusted_origin), Depends(limit_reset_password)],
    summary="Сброс пароля и отзыв всех сессий",
)
async def reset_password(
    body: ResetPasswordRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> Response:
    await service.reset_password(
        body.token.get_secret_value(), body.new_password.get_secret_value()
    )
    response = Response(status_code=204)
    clear_refresh_cookie(response, settings)
    return response


@router.post(
    "/password/change",
    status_code=204,
    dependencies=[Depends(limit_change_password)],
    summary="Смена пароля и отзыв всех сессий",
)
async def change_password(
    body: ChangePasswordRequest,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    settings: Annotated[Settings, Depends(get_settings)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> Response:
    await service.change_password(
        context, body.old_password.get_secret_value(), body.new_password.get_secret_value()
    )
    response = Response(status_code=204)
    clear_refresh_cookie(response, settings)
    return response
