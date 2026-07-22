"""The message rate limit: the allowance, the 429, and the window reset."""

import pytest

from app.api.errors import ApiError
from app.api.rate_limit import MAX_MESSAGES, RateLimiter, get_rate_limiter
from tests.conftest import HEADERS


class FakeClock:
    """Hand-advanced clock, so window expiry is tested without sleeping."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_allows_up_to_the_limit_then_rejects(api):
    client, _, _ = api
    for _ in range(MAX_MESSAGES):
        assert client.post("/api/v1/chat", json={"message": "hi"}, headers=HEADERS).status_code == 200

    response = client.post("/api/v1/chat", json={"message": "hi"}, headers=HEADERS)

    assert response.status_code == 429
    assert response.json() == {
        "code": "TOO_MANY_MESSAGES",
        "message": "You're sending messages too quickly. Try again later.",
    }


def test_follow_up_messages_count_against_the_same_limit(api):
    client, _, _ = api
    chat_id = client.post("/api/v1/chat", json={"message": "hi"}, headers=HEADERS).json()["chat_id"]
    for _ in range(MAX_MESSAGES - 1):
        assert (
            client.post(
                f"/api/v1/chat/{chat_id}/messages", json={"message": "more"}, headers=HEADERS
            ).status_code
            == 200
        )

    response = client.post(
        f"/api/v1/chat/{chat_id}/messages", json={"message": "more"}, headers=HEADERS
    )

    assert response.status_code == 429


def test_reading_the_history_is_not_rate_limited(api):
    client, _, _ = api
    chat_id = client.post("/api/v1/chat", json={"message": "hi"}, headers=HEADERS).json()["chat_id"]
    for _ in range(MAX_MESSAGES + 5):
        assert client.get(f"/api/v1/chat/{chat_id}", headers=HEADERS).status_code == 200


def test_a_different_key_has_its_own_allowance():
    limiter = RateLimiter(max_hits=2)
    limiter.check("code-a|1.1.1.1")
    limiter.check("code-a|1.1.1.1")

    assert limiter.check("code-b|1.1.1.1") == 1


def test_the_window_resets_once_it_has_passed():
    clock = FakeClock()
    limiter = RateLimiter(max_hits=2, window_seconds=60, clock=clock)
    limiter.check("k")
    limiter.check("k")
    with pytest.raises(ApiError):
        limiter.check("k")

    clock.advance(60)

    assert limiter.check("k") == 1


def test_a_rejected_hit_does_not_extend_the_window():
    clock = FakeClock()
    limiter = RateLimiter(max_hits=1, window_seconds=60, clock=clock)
    limiter.check("k")
    clock.advance(59)
    with pytest.raises(ApiError):
        limiter.check("k")

    clock.advance(1)

    assert limiter.check("k") == 1


def test_keys_are_forgotten_once_their_window_has_passed():
    clock = FakeClock()
    limiter = RateLimiter(window_seconds=60, clock=clock)
    limiter.check("gone")
    clock.advance(60)

    limiter.check("kept")

    assert list(limiter._windows) == ["kept"]


def test_the_limiter_singleton_is_shared():
    assert get_rate_limiter() is get_rate_limiter()
