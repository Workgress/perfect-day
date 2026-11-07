from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, JsonValue
from starlette.exceptions import HTTPException


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, JsonValue] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody


class AppError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, JsonValue] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = ErrorBody(code=code, message=message, details=details or {})
        self.headers = headers


HTTP_ERRORS: dict[int, tuple[str, str]] = {
    400: ("BAD_REQUEST", "Некорректный запрос"),
    401: ("AUTHENTICATION_REQUIRED", "Необходима аутентификация"),
    403: ("FORBIDDEN", "Доступ запрещён"),
    404: ("NOT_FOUND", "Ресурс не найден"),
    405: ("METHOD_NOT_ALLOWED", "Метод запроса не поддерживается"),
    409: ("CONFLICT", "Конфликт данных"),
    415: ("UNSUPPORTED_MEDIA_TYPE", "Формат данных не поддерживается"),
    422: ("VALIDATION_ERROR", "Ошибка проверки данных"),
    429: ("RATE_LIMIT_EXCEEDED", "Превышен лимит запросов"),
    500: ("INTERNAL_ERROR", "Внутренняя ошибка сервера"),
    503: ("SERVICE_UNAVAILABLE", "Сервис временно недоступен"),
}

VALIDATION_MESSAGES = {
    "missing": "Обязательное поле",
    "json_invalid": "Некорректный JSON",
    "string_type": "Ожидается строка",
    "string_too_short": "Слишком короткая строка",
    "string_too_long": "Слишком длинная строка",
    "string_pattern_mismatch": "Строка не соответствует допустимому формату",
    "int_parsing": "Ожидается целое число",
    "int_type": "Ожидается целое число",
    "float_parsing": "Ожидается число",
    "float_type": "Ожидается число",
    "bool_parsing": "Ожидается логическое значение",
    "bool_type": "Ожидается логическое значение",
    "uuid_parsing": "Некорректный UUID",
    "uuid_type": "Ожидается UUID",
    "date_type": "Ожидается дата",
    "date_parsing": "Некорректная дата",
    "date_from_datetime_parsing": "Некорректная дата",
    "datetime_type": "Ожидаются дата и время",
    "datetime_parsing": "Некорректные дата и время",
    "datetime_from_date_parsing": "Некорректные дата и время",
    "timezone_aware": "Необходимо указать часовой пояс",
    "enum": "Недопустимое значение",
    "literal_error": "Недопустимое значение",
    "greater_than": "Значение должно быть больше допустимой границы",
    "greater_than_equal": "Значение меньше допустимого минимума",
    "less_than": "Значение должно быть меньше допустимой границы",
    "less_than_equal": "Значение превышает допустимый максимум",
    "list_type": "Ожидается список",
    "dict_type": "Ожидается объект",
    "model_attributes_type": "Ожидается объект",
    "extra_forbidden": "Неизвестное поле",
}

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status_code: {"model": ErrorResponse, "description": message}
    for status_code, (_, message) in HTTP_ERRORS.items()
}


def _response(
    status_code: int,
    body: ErrorBody,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    response = JSONResponse(
        status_code=status_code,
        content=ErrorResponse(error=body).model_dump(mode="json"),
        headers=headers,
    )
    if status_code == 401:
        response.headers.setdefault("WWW-Authenticate", "Bearer")
    return response


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return _response(exc.status_code, exc.body, exc.headers)


async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
    code, message = HTTP_ERRORS.get(exc.status_code, ("HTTP_ERROR", "Ошибка HTTP-запроса"))
    return _response(exc.status_code, ErrorBody(code=code, message=message), exc.headers)


async def validation_error_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    fields: list[JsonValue] = [
        {
            "field": ".".join(str(part) for part in error["loc"]),
            "code": error["type"],
            "message": VALIDATION_MESSAGES.get(error["type"], "Некорректное значение"),
        }
        for error in exc.errors()
    ]
    return _response(
        422,
        ErrorBody(
            code="VALIDATION_ERROR",
            message="Ошибка проверки данных",
            details={"fields": fields},
        ),
    )


async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    code, message = HTTP_ERRORS[500]
    return _response(500, ErrorBody(code=code, message=message))


def register_error_handlers(app: FastAPI) -> None:
    app.exception_handler(AppError)(app_error_handler)
    app.exception_handler(HTTPException)(http_error_handler)
    app.exception_handler(RequestValidationError)(validation_error_handler)
    app.exception_handler(Exception)(unexpected_error_handler)
