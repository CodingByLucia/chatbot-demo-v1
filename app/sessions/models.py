"""Chat session data: a session is an id plus its full message history."""

import uuid
from dataclasses import dataclass, field


@dataclass
class Message:
    role: str
    content: str
    # Set on assistant messages that triggered the fallback card, so the card
    # can be rebuilt when the conversation is reloaded.
    fallback_reason: str | None = None


@dataclass
class Contact:
    name: str
    email: str


@dataclass
class Session:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    messages: list[Message] = field(default_factory=list)
    contact: Contact | None = None
