from __future__ import annotations

import hashlib
import hmac
import secrets


class PasswordHasher:
    _n = 2**14
    _r = 8
    _p = 1

    def hash(self, password: str) -> str:
        if len(password) < 8:
            raise ValueError("Password must contain at least 8 characters")
        salt = secrets.token_bytes(16)
        digest = hashlib.scrypt(
            password.encode(), salt=salt, n=self._n, r=self._r, p=self._p
        )
        return f"scrypt${self._n}${self._r}${self._p}${salt.hex()}${digest.hex()}"

    def verify(self, password: str, encoded: str) -> bool:
        try:
            algorithm, n, r, p, salt, expected = encoded.split("$", 5)
            if algorithm != "scrypt":
                return False
            actual = hashlib.scrypt(
                password.encode(),
                salt=bytes.fromhex(salt),
                n=int(n),
                r=int(r),
                p=int(p),
            )
        except (ValueError, TypeError):
            return False
        return hmac.compare_digest(actual.hex(), expected)
