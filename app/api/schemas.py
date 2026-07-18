"""Request and response shapes for the chat API."""

import re

from pydantic import BaseModel, field_validator

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ChatRequest(BaseModel):
    message: str

    @field_validator("message")
    @classmethod
    def _strip_and_require_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message must not be empty")
        return value


class ContactRequest(BaseModel):
    name: str
    email: str

    @field_validator("name")
    @classmethod
    def _require_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be empty")
        return value

    @field_validator("email")
    @classmethod
    def _require_valid_email(cls, value: str) -> str:
        value = value.strip()
        if not _EMAIL.match(value):
            raise ValueError("email must be a valid address")
        return value


class ContactResponse(BaseModel):
    status: str = "ok"


class Fallback(BaseModel):
    reason: str
    booking_url: str


class ChatResponse(BaseModel):
    chat_id: str
    reply: str
    fallback: Fallback | None


class MessageOut(BaseModel):
    role: str
    content: str
    fallback: Fallback | None = None


class ChatHistoryResponse(BaseModel):
    chat_id: str
    messages: list[MessageOut]
