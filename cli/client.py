from __future__ import annotations

from typing import Any, BinaryIO
import os

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
        self._client = httpx.Client(
            base_url=api_base.rstrip("/"),
            transport=transport,
            headers=_runtime_actor_headers(),
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        data: dict[str, str] | None = None,
        files: dict[str, tuple[str, BinaryIO, str]] | None = None,
        params: dict[str, str] | None = None,
        json: object | None = None,
    ) -> Any:
        response = self._client.request(
            method,
            path,
            data=data,
            files=files,
            params=params,
            json=json,
        )
        if response.is_error:
            message = f"Request failed ({response.status_code})"
            try:
                detail = response.json().get("detail")
                if isinstance(detail, str):
                    message = detail
            except (ValueError, AttributeError):
                pass
            raise ApiError(response.status_code, message)
        if response.status_code == 204 or not response.content:
            return {}
        return response.json()

    def request_bytes(self, method: str, path: str) -> bytes:
        response = self._client.request(method, path)
        if response.is_error:
            message = f"Request failed ({response.status_code})"
            try:
                detail = response.json().get("detail")
                if isinstance(detail, str):
                    message = detail
            except (ValueError, AttributeError):
                pass
            raise ApiError(response.status_code, message)
        return response.content


def _runtime_actor_headers() -> dict[str, str]:
    headers: dict[str, str] = {}
    agent_id = _env("OCTOPUS_AGENT_ID")
    org_id = _env("OCTOPUS_ORG_ID")
    run_id = _env("OCTOPUS_RUN_ID")
    api_key = _env("OCTOPUS_API_KEY")
    if agent_id and org_id:
        headers["x-test-agent-id"] = agent_id
        headers["x-test-org-id"] = org_id
    if run_id:
        headers["x-octopus-run-id"] = run_id
    if api_key:
        headers["x-api-key"] = api_key
    return headers


def _env(key: str) -> str | None:
    value = os.environ.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None
