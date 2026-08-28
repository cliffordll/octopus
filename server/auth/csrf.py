from __future__ import annotations

from urllib.parse import urlsplit


SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def is_trusted_session_origin(
    *,
    method: str,
    origin: str | None,
    request_url: str,
    allow_loopback_proxy: bool = False,
) -> bool:
    if method.upper() in SAFE_METHODS:
        return True
    if not origin:
        return False
    request = urlsplit(request_url)
    candidate = urlsplit(origin)
    if (
        candidate.scheme.lower() == request.scheme.lower()
        and candidate.netloc.lower() == request.netloc.lower()
    ):
        return True
    return bool(
        allow_loopback_proxy
        and candidate.scheme.lower() == request.scheme.lower()
        and candidate.hostname in LOOPBACK_HOSTS
        and request.hostname in LOOPBACK_HOSTS
    )
