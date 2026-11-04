from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field


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
