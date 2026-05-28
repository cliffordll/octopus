from __future__ import annotations

from pathlib import Path
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


def skill_snapshot_from_root(
    *,
    runtime_type: str,
    config: dict[str, Any],
    desired_skills: list[str],
    mode: str,
    location_label: str,
) -> dict[str, Any]:
    root = config.get("skillsRootPath")
    desired = set(desired_skills)
    entries: list[dict[str, Any]] = []
    warnings: list[str] = []
    seen_keys: set[str] = set()
    if isinstance(root, str) and root.strip():
        root_path = Path(root)
        if root_path.exists() and root_path.is_dir():
            for skill_dir in _skill_dirs(root_path):
                entries.append(
                    _skill_entry(
                        skill_dir,
                        desired=skill_dir.name in desired,
                        location_label=location_label,
                        source_class="organization",
                        origin="organization_managed",
                        origin_label="Organization skill",
                        read_only=False,
                    )
                )
                seen_keys.add(skill_dir.name)
        else:
            warnings.append(f"skillsRootPath does not exist: {root}")
    for skill_dir in _skill_dirs(_bundled_skills_root()):
        if skill_dir.name in seen_keys:
            continue
        entries.append(
            _skill_entry(
                skill_dir,
                desired=skill_dir.name in desired,
                location_label="bundled skills",
                source_class="bundled",
                origin="bundled",
                origin_label="Bundled skill",
                read_only=True,
            )
        )
    return {
        "agentRuntimeType": runtime_type,
        "supported": True,
        "mode": mode,
        "desiredSkills": desired_skills,
        "entries": entries,
        "warnings": warnings,
    }


def _bundled_skills_root() -> Path:
    return Path(__file__).resolve().parents[2] / "server" / "skills" / "bundled"


def _skill_dirs(root_path: Path) -> list[Path]:
    if not root_path.exists() or not root_path.is_dir():
        return []
    return [
        skill_dir
        for skill_dir in sorted(root_path.iterdir(), key=lambda item: item.name)
        if skill_dir.is_dir() and skill_dir.joinpath("SKILL.md").is_file()
    ]


def _skill_entry(
    skill_dir: Path,
    *,
    desired: bool,
    location_label: str,
    source_class: str,
    origin: str,
    origin_label: str,
    read_only: bool,
) -> dict[str, Any]:
    description = _skill_description(skill_dir.joinpath("SKILL.md"))
    return {
        "key": skill_dir.name,
        "selectionKey": skill_dir.name,
        "runtimeName": skill_dir.name,
        "description": description,
        "desired": desired,
        "configurable": True,
        "alwaysEnabled": False,
        "managed": True,
        "state": "configured" if desired else "available",
        "sourceClass": source_class,
        "origin": origin,
        "originLabel": origin_label,
        "locationLabel": location_label,
        "readOnly": read_only,
        "sourcePath": str(skill_dir),
        "targetPath": None,
        "workspaceEditPath": str(skill_dir.joinpath("SKILL.md")),
        "detail": None,
    }


def _skill_description(skill_file: Path) -> str | None:
    try:
        lines = skill_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        return value
    return None


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

    async def list_models(self) -> list[dict[str, str]]:
        return []

    async def list_skills(self, config: dict[str, Any]) -> dict[str, Any]:
        return self._skill_snapshot(config, [])

    async def sync_skills(
        self, config: dict[str, Any], desired_skills: list[str]
    ) -> dict[str, Any]:
        return self._skill_snapshot(config, desired_skills)

    def _skill_snapshot(
        self, config: dict[str, Any], desired_skills: list[str]
    ) -> dict[str, Any]:
        return skill_snapshot_from_root(
            runtime_type=self.type,
            config=config,
            desired_skills=desired_skills,
            mode="runtime",
            location_label="runtime skills",
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
