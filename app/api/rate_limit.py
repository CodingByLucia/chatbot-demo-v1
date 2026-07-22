"""Per-client message rate limit: an in-memory fixed-window counter.

Guards the routes that spend credits. The access code keeps strangers out;
this keeps one holder of it from draining the budget in a burst.
"""

import time
from functools import lru_cache
from threading import Lock
from typing import Annotated, Callable

import structlog
from fastapi import Depends, Header, Request

from app.api.errors import ApiError

MAX_MESSAGES = 10
WINDOW_SECONDS = 60


class RateLimiter:
    """Counts hits per key within a fixed window.

    A key is allowed max_hits hits per window; the window starts on the first
    hit and the count resets once it has passed. Rejected hits are not counted,
    so a client that keeps knocking still gets in as soon as the window rolls.
    """

    def __init__(
        self,
        max_hits: int = MAX_MESSAGES,
        window_seconds: int = WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_hits = max_hits
        self._window = window_seconds
        self._clock = clock
        self._lock = Lock()
        self._windows: dict[str, tuple[float, int]] = {}

    def check(self, key: str) -> int:
        """Records a hit and returns the number used in the current window.

        Raises ApiError 429 instead when the key is already at its limit.
        """
        with self._lock:
            now = self._clock()
            self._drop_passed_windows(now)
            started_at, hits = self._windows.get(key, (now, 0))
            if hits >= self._max_hits:
                raise ApiError(
                    429,
                    "TOO_MANY_MESSAGES",
                    "You're sending messages too quickly. Try again later.",
                )
            self._windows[key] = (started_at, hits + 1)
            return hits + 1

    def _drop_passed_windows(self, now: float) -> None:
        """Forgets keys whose window has passed, so the dict tracks only
        clients seen within the last window."""
        for key, (started_at, _) in list(self._windows.items()):
            if now - started_at >= self._window:
                del self._windows[key]


@lru_cache
def get_rate_limiter() -> RateLimiter:
    return RateLimiter()


def enforce_message_rate_limit(
    request: Request,
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    x_access_code: Annotated[str | None, Header()] = None,
) -> None:
    """Route dependency for the message-sending endpoints.

    Keyed on the access code as well as the client address: the code is shared,
    so counting it alone would let one visitor lock everyone else out.
    """
    client = request.client.host if request.client else "unknown"
    try:
        used = limiter.check(f"{x_access_code}\x00{client}")
    except ApiError:
        structlog.get_logger().warning("rate_limited", client=client)
        raise
    structlog.get_logger().debug("rate_limit_ok", client=client, used=used)
