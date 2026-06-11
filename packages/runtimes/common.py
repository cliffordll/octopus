from __future__ import annotations

import os
import subprocess
from typing import Any

from .skills import skill_snapshot_from_root
from .types import RuntimeEnvironmentTestResult, RuntimeExecutionResult


def runtime_subprocess_kwargs() -> dict[str, int]:
    if os.name != "nt":
        return {}
    return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}


class UnavailableRuntimeAdapter:
    def __init__(self, runtime_type: str) -> None:
        self.type = runtime_type

    async def execute(self, context: Any) -> RuntimeExecutionResult:
        return RuntimeExecutionResult(
            exit_code=None,
            error_message=f"Runtime adapter is not implemented: {self.type}",
            result_json={"adapterUnavailable": True, "agentRuntimeType": self.type},
        )

    async def test_environment(
        self, config: dict[str, Any]
    ) -> RuntimeEnvironmentTestResult:
        return RuntimeEnvironmentTestResult(
            agent_runtime_type=self.type,
            status="unavailable",
            checks=[
                {
                    "id": "adapter",
                    "label": "Adapter implementation",
                    "status": "unavailable",
                    "message": f"Runtime adapter is not implemented: {self.type}",
                    "hint": "This runtime type is recognized but not included in the current implementation scope.",
                }
            ],
        )

    async def list_models(
        self, config: dict[str, Any] | None = None
    ) -> list[dict[str, str]]:
        return []

    async def list_skills(
        self, config: dict[str, Any], desired_skills: list[str] | None = None
    ) -> dict[str, Any]:
        return _unsupported_skill_snapshot(self.type, desired_skills or [])

    async def sync_skills(
        self, config: dict[str, Any], desired_skills: list[str]
    ) -> dict[str, Any]:
        return _unsupported_skill_snapshot(self.type, desired_skills)

    async def get_metadata(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "capabilities": {
                "models": False,
                "skills": False,
                "environmentTest": True,
                "quotaWindows": False,
                "localAgentJwt": False,
            },
            "supportsLocalAgentJwt": False,
            "agentConfigurationDoc": None,
        }

    async def get_quota_windows(self) -> dict[str, Any]:
        return {
            "provider": self.type,
            "source": None,
            "ok": False,
            "error": f"Runtime adapter is not implemented: {self.type}",
            "windows": [],
        }


def _unsupported_skill_snapshot(
    runtime_type: str, desired_skills: list[str]
) -> dict[str, Any]:
    return {
        "agentRuntimeType": runtime_type,
        "supported": False,
        "mode": "unsupported",
        "desiredSkills": desired_skills,
        "entries": [],
        "warnings": ["This adapter does not implement skill sync."],
    }


class RuntimeCapabilityMixin:
    type: str
    supports_local_agent_jwt = False
    agent_configuration_doc: str | None = None
    quota_provider: str | None = None

    async def test_environment(
        self, config: dict[str, Any]
    ) -> RuntimeEnvironmentTestResult:
        return RuntimeEnvironmentTestResult(
            agent_runtime_type=self.type,
            status="ok",
            checks=[
                {
                    "id": "configuration",
                    "label": "Configuration",
                    "status": "ok",
                    "message": "Runtime configuration is accepted.",
                    "hint": None,
                }
            ],
        )

    async def list_models(
        self, config: dict[str, Any] | None = None
    ) -> list[dict[str, str]]:
        return []

    async def list_skills(
        self, config: dict[str, Any], desired_skills: list[str] | None = None
    ) -> dict[str, Any]:
        return self._skill_snapshot(config, desired_skills or [], materialize=False)

    async def sync_skills(
        self, config: dict[str, Any], desired_skills: list[str]
    ) -> dict[str, Any]:
        return self._skill_snapshot(config, desired_skills, materialize=True)

    def _skill_snapshot(
        self,
        config: dict[str, Any],
        desired_skills: list[str],
        *,
        materialize: bool,
    ) -> dict[str, Any]:
        return skill_snapshot_from_root(
            runtime_type=self.type,
            config=config,
            desired_skills=desired_skills,
            mode="runtime",
            location_label="runtime skills",
            materialize=materialize,
        )

    async def get_metadata(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "capabilities": {
                "models": True,
                "skills": True,
                "environmentTest": True,
                "quotaWindows": self.quota_provider is not None,
                "localAgentJwt": self.supports_local_agent_jwt,
            },
            "supportsLocalAgentJwt": self.supports_local_agent_jwt,
            "agentConfigurationDoc": self.agent_configuration_doc,
        }

    async def get_quota_windows(self) -> dict[str, Any]:
        if self.quota_provider is None:
            return {
                "provider": self.type,
                "source": None,
                "ok": False,
                "error": "This runtime adapter does not expose quota windows.",
                "windows": [],
            }
        return {
            "provider": self.quota_provider,
            "source": self.type,
            "ok": False,
            "error": "Quota window probe is not configured in this environment.",
            "windows": [],
        }
