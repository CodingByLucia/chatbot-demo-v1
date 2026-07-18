"""Chat session data: a session is an id plus its full message history."""

import uuid
from dataclasses import dataclass, field


@dataclass
class Message:
    role: str
    content: str


@dataclass
class Session:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    messages: list[Message] = field(default_factory=list)
