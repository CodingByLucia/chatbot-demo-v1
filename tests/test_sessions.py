from app.sessions.manager import SessionManager
from app.sessions.store import InMemorySessionStore


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def make_store(ttl=100):
    clock = FakeClock()
    return InMemorySessionStore(ttl_seconds=ttl, clock=clock), clock


def test_create_then_get_roundtrip():
    store, _ = make_store()
    session = store.create()
    assert store.get(session.id) is session


def test_unknown_id_returns_none():
    store, _ = make_store()
    assert store.get("nope") is None


def test_session_expires_after_ttl():
    store, clock = make_store(ttl=100)
    session = store.create()
    clock.advance(101)
    assert store.get(session.id) is None


def test_save_refreshes_ttl():
    store, clock = make_store(ttl=100)
    session = store.create()
    clock.advance(60)
    store.save(session)
    clock.advance(60)  # 120s since create, but only 60s since the last save
    assert store.get(session.id) is session


def test_delete_removes_session():
    store, _ = make_store()
    session = store.create()
    store.delete(session.id)
    assert store.get(session.id) is None


def test_manager_add_message_appends_and_persists():
    store, _ = make_store()
    manager = SessionManager(store)
    session = manager.create_session()
    manager.add_message(session, "user", "hi")
    manager.add_message(session, "assistant", "hello")
    fetched = manager.get_session(session.id)
    assert [(m.role, m.content) for m in fetched.messages] == [
        ("user", "hi"),
        ("assistant", "hello"),
    ]


def test_manager_returns_none_for_expired_session():
    store, clock = make_store(ttl=100)
    manager = SessionManager(store)
    session = manager.create_session()
    clock.advance(101)
    assert manager.get_session(session.id) is None


def test_store_keeps_full_history_beyond_ten_messages():
    store, _ = make_store()
    manager = SessionManager(store)
    session = manager.create_session()
    for i in range(15):
        manager.add_message(session, "user", f"msg {i}")
    assert len(manager.get_session(session.id).messages) == 15
