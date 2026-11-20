"""@cached_per_user: an API operation's response kept in the cache for each user,
under a key that can be deleted when that user's data changes (Django's
cache_page can't: its keys hash the URL and headers)."""

from functools import wraps

from django.core.cache import cache
from django.http import HttpResponse
from ninja.decorators import decorate_view


def key(name: str, user_id) -> str:
    return f"{name}:{user_id}"


def invalidate(name: str, *user_ids) -> None:
    cache.delete_many([key(name, user_id) for user_id in user_ids])


def cached_per_user(name: str, timeout: int):
    """Keeps the logged-in user's 200 response for `timeout` seconds, under
    key(name, user.pk). Anyone not logged in goes through, so the operation's
    auth still answers them."""

    def wrap(run):
        @wraps(run)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return run(request, *args, **kwargs)
            entry_key = key(name, request.user.pk)
            entry = cache.get(entry_key)
            if entry is None:
                response = run(request, *args, **kwargs)
                if response.status_code != 200:
                    return response
                entry = (response.content, response["Content-Type"])
                cache.set(entry_key, entry, timeout)
            content, content_type = entry
            return HttpResponse(content, content_type=content_type)

        return wrapper

    return decorate_view(wrap)
