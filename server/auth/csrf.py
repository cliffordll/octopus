from __future__ import annotations

from urllib.parse import urlsplit


SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def is_trusted_session_origin(
    *, method: str, origin: str | None, request_url: str
) -> bool:
    if method.upper() in SAFE_METHODS:
        return True
    if not origin:
        return False
    request = urlsplit(request_url)
    candidate = urlsplit(origin)
    return (
        candidate.scheme.lower() == request.scheme.lower()
        and candidate.netloc.lower() == request.netloc.lower()
    )
