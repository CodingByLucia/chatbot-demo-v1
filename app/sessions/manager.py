"""SessionManager: the only door to session storage; every write goes through save()."""

from functools import lru_cache

from app.config import get_settings
from app.sessions.models import Contact, Message, Session
from app.sessions.store import InMemorySessionStore, SessionStore


class SessionManager:
    def __init__(self, store: SessionStore) -> None:
        self._store = store

    def create_session(self) -> Session:
        return self._store.create()

    def get_session(self, session_id: str) -> Session | None:
        """None means the session is unknown or expired."""
        return self._store.get(session_id)

    def add_message(
        self,
        session: Session,
        role: str,
        content: str,
        fallback_reason: str | None = None,
    ) -> Message:
        message = Message(role=role, content=content, fallback_reason=fallback_reason)
        session.messages.append(message)
        self._store.save(session)
        return message

    def set_contact(self, session: Session, name: str, email: str) -> Contact:
        session.contact = Contact(name=name, email=email)
        self._store.save(session)
        return session.contact


@lru_cache
def get_session_manager() -> SessionManager:
    settings = get_settings()
    return SessionManager(
        InMemorySessionStore(ttl_seconds=settings.session_ttl_seconds)
    )
