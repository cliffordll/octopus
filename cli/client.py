from __future__ import annotations

from typing import Any

import httpx

DEFAULT_API_BASE = "http://127.0.0.1:8000"


class ApiError(RuntimeError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class ApiClient:
    def __init__(
        self,
        api_base: str = DEFAULT_API_BASE,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(base_url=api_base.rstrip("/"), transport=transport)

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: object | None = None,
    ) -> Any:
        response = self._client.request(method, path, params=params, json=json)
        if response.is_error:
            message = f"Request failed ({response.status_code})"
            try:
                detail = response.json().get("detail")
                if isinstance(detail, str):
                    message = detail
            except (ValueError, AttributeError):
                pass
            raise ApiError(response.status_code, message)
        return response.json()
