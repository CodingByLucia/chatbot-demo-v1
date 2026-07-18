"""Session storage: the SessionStore interface and the in-memory implementation."""

import time
from abc import ABC, abstractmethod
from threading import Lock
from typing import Callable

import structlog

from app.sessions.models import Session


class SessionStore(ABC):
    @abstractmethod
    def create(self) -> Session: ...

    @abstractmethod
    def get(self, session_id: str) -> Session | None: ...

    @abstractmethod
    def save(self, session: Session) -> None: ...

    @abstractmethod
    def delete(self, session_id: str) -> None: ...


class InMemorySessionStore(SessionStore):
    """Dict-backed store; a session expires ttl_seconds after its last save."""

    def __init__(
        self, ttl_seconds: int, clock: Callable[[], float] = time.time
    ) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._lock = Lock()
        self._sessions: dict[str, tuple[Session, float]] = {}

    def create(self) -> Session:
        session = Session()
        with self._lock:
            self._sessions[session.id] = (session, self._clock())
        return session

    def get(self, session_id: str) -> Session | None:
        with self._lock:
            entry = self._sessions.get(session_id)
            if entry is None:
                return None
            session, saved_at = entry
            if self._clock() - saved_at > self._ttl:
                del self._sessions[session_id]
                structlog.get_logger().info("session_expired", session_id=session_id)
                return None
            return session

    def save(self, session: Session) -> None:
        with self._lock:
            self._sessions[session.id] = (session, self._clock())

    def delete(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)
