from __future__ import annotations

from typing import Any

from .types import RuntimeEnvironmentTestResult, RuntimeExecutionResult


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

    async def list_models(self) -> list[dict[str, str]]:
        return []

    async def list_skills(self, config: dict[str, Any]) -> dict[str, Any]:
        return _unsupported_skill_snapshot(self.type, [])

    async def sync_skills(
        self, config: dict[str, Any], desired_skills: list[str]
    ) -> dict[str, Any]:
        return _unsupported_skill_snapshot(self.type, desired_skills)


def _unsupported_skill_snapshot(
    runtime_type: str, desired_skills: list[str]
) -> dict[str, Any]:
    return {
        "agentRuntimeType": runtime_type,
        "supported": False,
        "desiredSkills": desired_skills,
        "entries": [],
        "warnings": ["This adapter does not implement skill sync."],
    }


class RuntimeCapabilityMixin:
    type: str

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

    async def list_models(self) -> list[dict[str, str]]:
        return []

    async def list_skills(self, config: dict[str, Any]) -> dict[str, Any]:
        return {
            "agentRuntimeType": self.type,
            "supported": True,
            "desiredSkills": [],
            "entries": [],
            "warnings": [],
        }

    async def sync_skills(
        self, config: dict[str, Any], desired_skills: list[str]
    ) -> dict[str, Any]:
        return {
            "agentRuntimeType": self.type,
            "supported": True,
            "desiredSkills": desired_skills,
            "entries": [],
            "warnings": [],
        }
