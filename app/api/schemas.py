"""Request and response shapes for the chat API."""

from pydantic import BaseModel, field_validator


class ChatRequest(BaseModel):
    message: str

    @field_validator("message")
    @classmethod
    def _strip_and_require_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message must not be empty")
        return value


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


class ChatHistoryResponse(BaseModel):
    chat_id: str
    messages: list[MessageOut]
