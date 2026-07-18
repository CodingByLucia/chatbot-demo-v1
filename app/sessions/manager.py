"""SessionManager: the only door to session storage; every write goes through save()."""

from functools import lru_cache

from app.config import get_settings
from app.sessions.models import Message, Session
from app.sessions.store import InMemorySessionStore, SessionStore


class SessionManager:
    def __init__(self, store: SessionStore) -> None:
        self._store = store

    def create_session(self) -> Session:
        return self._store.create()

    def get_session(self, session_id: str) -> Session | None:
        """None means the session is unknown or expired."""
        return self._store.get(session_id)

    def add_message(self, session: Session, role: str, content: str) -> Message:
        message = Message(role=role, content=content)
        session.messages.append(message)
        self._store.save(session)
        return message


@lru_cache
def get_session_manager() -> SessionManager:
    settings = get_settings()
    return SessionManager(
        InMemorySessionStore(ttl_seconds=settings.session_ttl_seconds)
    )
