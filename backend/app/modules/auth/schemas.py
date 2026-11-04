from typing import Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    field_validator,
)

from app.core.security import validate_password


class EmailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    email: EmailStr = Field(description="Email пользователя", examples=["user@example.com"])

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()


class RegisterRequest(EmailRequest):
    password: SecretStr = Field(
        min_length=8,
        max_length=128,
        description="Пароль: от 8 до 128 символов, минимум одна буква и одна цифра",
    )

    @field_validator("password")
    @classmethod
    def check_password(cls, value: SecretStr) -> SecretStr:
        validate_password(value.get_secret_value())
        return value


class VerifyEmailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    token: SecretStr = Field(
        min_length=1, max_length=256, description="Одноразовый токен из письма подтверждения"
    )


class TokenResponse(BaseModel):
    access_token: str = Field(min_length=1)
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(default=900, gt=0)


class MessageResponse(BaseModel):
    message: str


class SessionResponse(BaseModel):
    id: UUID
    created_at: AwareDatetime
    expires_at: AwareDatetime
    last_used_at: AwareDatetime
    ip: str | None
    user_agent: str | None
    is_current: bool


class SessionsResponse(BaseModel):
    items: list[SessionResponse]
