from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from collections.abc import Mapping
from typing import Any


class HmacJwtCodec:
    """Small HS256 codec for trusted control-plane token contracts."""

    def __init__(self, *, secret: str, issuer: str, audience: str) -> None:
        if not secret:
            raise ValueError("JWT secret must not be empty")
        self._secret = secret.encode()
        self._issuer = issuer
        self._audience = audience

    def encode(self, claims: Mapping[str, Any]) -> str:
        header = _encode_json({"alg": "HS256", "typ": "JWT"})
        payload = _encode_json(
            {**dict(claims), "iss": self._issuer, "aud": self._audience}
        )
        signed = f"{header}.{payload}"
        signature = hmac.new(self._secret, signed.encode(), hashlib.sha256).digest()
        return f"{signed}.{_encode_bytes(signature)}"

    def decode(self, token: str) -> dict[str, Any] | None:
        try:
            encoded_header, encoded_payload, encoded_signature = token.split(".", 2)
            header = json.loads(_decode_bytes(encoded_header))
            claims = json.loads(_decode_bytes(encoded_payload))
            signature = _decode_bytes(encoded_signature)
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
            return None
        if not isinstance(header, dict) or header.get("alg") != "HS256":
            return None
        if not isinstance(claims, dict):
            return None
        signed = f"{encoded_header}.{encoded_payload}".encode()
        expected = hmac.new(self._secret, signed, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            return None
        now = int(time.time())
        issued_at = claims.get("iat")
        expires_at = claims.get("exp")
        if not isinstance(issued_at, int) or not isinstance(expires_at, int):
            return None
        if issued_at > now + 60 or expires_at <= now:
            return None
        if claims.get("iss") != self._issuer or claims.get("aud") != self._audience:
            return None
        return claims


def _encode_json(value: Mapping[str, Any]) -> str:
    return _encode_bytes(
        json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    )


def _encode_bytes(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _decode_bytes(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
