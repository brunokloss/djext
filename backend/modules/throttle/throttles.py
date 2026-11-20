"""Rate limits for the API, kept in the cache (see modules/cache/caches.py).

django-ninja's throttles, with one change: who is logged in comes from the
session (request.user), not from the endpoint's `auth`, so a logged-in user
calling an endpoint without auth still counts as that user.

The client's IP is the last X-Forwarded-For entry (NINJA_NUM_PROXIES = 1),
the same rule as the logs. Next passes on the header the client sent, so this
needs a load balancer in front of Next that appends the client's address (see
the README). With Next exposed directly, a client sends its own header, gets
a fresh IP on every request, and the per-IP limits stop nothing.
"""

import math

from django.http import HttpRequest
from django.utils.crypto import salted_hmac
from ninja.throttling import SimpleRateThrottle


class AnonThrottle(SimpleRateThrottle):
    """Requests from one IP while logged out."""

    scope = "anon"

    def get_cache_key(self, request: HttpRequest) -> str | None:
        if request.user.is_authenticated:
            return None
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }


class UserThrottle(SimpleRateThrottle):
    """Requests from one logged-in user, from any IP."""

    scope = "user"

    def get_cache_key(self, request: HttpRequest) -> str | None:
        if not request.user.is_authenticated:
            return None
        return self.cache_format % {"scope": self.scope, "ident": request.user.pk}


def throttles(**rates: str) -> list[SimpleRateThrottle]:
    """One throttle per non-empty rate, e.g. throttles(anon="60/min").
    An empty rate turns that one off."""
    classes = {"anon": AnonThrottle, "user": UserThrottle}
    return [classes[name](rate) for name, rate in rates.items() if rate]


class FailureLimit(SimpleRateThrottle):
    """Counts failures only (e.g. wrong passwords), not every request, so
    whoever gets it right is never slowed down until they get it wrong.

    Each try is counted as a failure up front (attempt()), before the slow
    password check, and taken back (forget()) when it succeeds. Checking first
    and counting after would let a burst of parallel tries all read the same
    count during the check. What is left is the gap between the cache's get
    and set (a few ms); only an atomic incr (Redis) would close it.

    Kept in no instance: make new ones on every request (like authd's login).
    `ident` is what is counted: an IP, or hashed(email).
    """

    def __init__(self, scope: str, rate: str):
        self.scope = scope
        super().__init__(rate)

    def _key(self, ident: str) -> str:
        return self.cache_format % {"scope": self.scope, "ident": ident}

    def _history(self, ident: str, now: float) -> list[float]:
        """The failures still inside the window, newest first."""
        history = self.cache.get(self._key(ident), [])
        return [t for t in history if t > now - self.duration]

    def attempt(self, ident: str) -> tuple[int | None, float | None]:
        """(retry_after, None) when the limit is reached: seconds until the
        oldest failure leaves the window. Otherwise counts this try as a
        failure and returns (None, its timestamp), for forget()."""
        now = self.timer()
        history = self._history(ident, now)
        if len(history) >= self.num_requests:
            return max(1, math.ceil(history[-1] + self.duration - now)), None
        self.cache.set(self._key(ident), [now, *history], self.duration)
        return None, now

    def status(self, ident: str) -> tuple[int, int | None]:
        """(failures in the window, seconds until it lets a try in or None
        when it already does). Reads only, for the admin."""
        now = self.timer()
        history = self._history(ident, now)
        if len(history) < self.num_requests:
            return len(history), None
        return len(history), max(1, math.ceil(history[-1] + self.duration - now))

    def forget(self, ident: str, stamp: float) -> None:
        """Takes back one try attempt() counted (it didn't fail after all)."""
        history = self._history(ident, self.timer())
        # One entry only: two tries may share a timestamp.
        if stamp in history:
            history.remove(stamp)
        self.cache.set(self._key(ident), history, self.duration)

    def clear(self, ident: str) -> None:
        self.cache.delete(self._key(ident))


def hashed(value: str) -> str:
    """For cache keys made from personal data, like an email: the cache
    monitor lists the keys. Keyed with SECRET_KEY, so whoever sees the keys
    can't hash a known email and look for it."""
    return salted_hmac("modules.throttle", value, algorithm="sha256").hexdigest()
