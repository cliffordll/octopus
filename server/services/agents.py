from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
from pathlib import Path
import re
from collections.abc import Mapping, Sequence
from typing import Any, Literal, cast
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.activity_log import insert_activity_log
from packages.database.queries.agents import (
    create_agent,
    get_agent_by_id,
    list_org_agents,
    update_agent,
)
from packages.database.queries.issues import list_agent_inbox_issues
from packages.database.queries.organizations import get_organization_by_id
from packages.database.queries.agent_skills import (
    add_enabled_skill_keys,
    list_enabled_skill_keys,
    list_enabled_skill_keys_by_agent_ids,
    list_skill_usage_sources,
    replace_enabled_skill_keys,
)
from packages.database.queries.agent_state import (
    create_config_revision,
    create_runtime_state,
    delete_task_sessions,
    get_config_revision,
    get_runtime_state,
    list_config_revisions,
    list_task_sessions,
    update_runtime_state,
)
from packages.database.schema import (
    Agent as AgentRow,
    AgentConfigRevision as AgentConfigRevisionRow,
    AgentRuntimeState as AgentRuntimeStateRow,
    AgentTaskSession as AgentTaskSessionRow,
    AgentWakeupRequest as AgentWakeupRequestRow,
    Issue as IssueRow,
    IssueComment as IssueCommentRow,
    Organization as OrganizationRow,
)
from packages.shared.constants.agent import (
    AGENT_DICEBEAR_NOTIONISTS_ICON_PREFIX,
    DEFAULT_AGENT_RUNTIME_TYPE,
    DEFAULT_AGENT_STATUS,
    DEFAULT_AGENT_ROLE,
    AgentRole,
    AgentRuntimeType,
    AgentStatus,
    PauseReason,
)
from packages.shared.constants.issue import IssuePriority, IssueStatus
from packages.shared.constants.heartbeat import (
    AGENT_RUN_CONCURRENCY_DEFAULT,
    HEARTBEAT_INTERVAL_DEFAULT_SEC,
)
from packages.shared.types.agent import (
    Agent,
    AgentAccessState,
    AgentChainOfCommandEntry,
    AgentConfigRevision,
    AgentConfiguration,
    AgentDetail,
    AgentHireResult,
    AgentInboxItem,
    AgentRuntimeState,
    AgentSkillAnalytics,
    AgentSkillSnapshot,
    AgentTaskSession,
    CreateAgentPayload,
    HireAgentPayload,
    ResetAgentSessionPayload,
    ResetAgentSessionResult,
    UpdateAgentPayload,
)
from packages.shared.types.heartbeat import InstanceSchedulerHeartbeatAgent
from packages.shared.types.approval import CreateApprovalPayload
from packages.runtimes import get_runtime_adapter

from .agent_instructions import (
    materialize_default_instructions_for_new_agent,
    normalize_instructions_paths,
)
from .organization_skills import (
    BUNDLED_SKILL_KEYS,
    OrganizationSkillService,
    organization_skills_root,
)
from .workspace_paths import agent_workspace_root

_URL_KEY_PATTERN = re.compile(r"[^a-z0-9]+")
_SENSITIVE_KEY_PATTERN = re.compile(
    r"(api[-_]?key|access[-_]?token|auth(?:_?token)?|authorization|bearer|secret|passwd|password|credential|jwt|private[-_]?key|cookie|connectionstring)",
    re.IGNORECASE,
)
_REDACTED = "***REDACTED***"
_DEFAULT_ENABLED_SKILLS = BUNDLED_SKILL_KEYS
_CONFIG_REVISION_FIELDS: tuple[str, ...] = (
    "name",
    "role",
    "title",
    "reportsTo",
    "capabilities",
    "agentRuntimeType",
    "agentRuntimeConfig",
    "runtimeConfig",
    "budgetMonthlyCents",
    "metadata",
)
_AGENT_WORKSPACE_HOME_DIRS = ("instructions", "skills", "life", "memory")
_SKILL_EVIDENCE_KINDS = ("used", "requested", "loaded")
_SCHEDULER_INELIGIBLE_STATUSES = {"paused", "terminated", "pending_approval"}
SkillEvidenceKind = Literal["used", "requested", "loaded"]
_DEFAULT_HEARTBEAT_INTERVAL_SEC = HEARTBEAT_INTERVAL_DEFAULT_SEC
_DEFAULT_HEARTBEAT_POLICY: dict[str, Any] = {
    "enabled": True,
    "intervalSec": _DEFAULT_HEARTBEAT_INTERVAL_SEC,
    "wakeOnDemand": True,
    "preflightEnabled": True,
    "maxConcurrentRuns": AGENT_RUN_CONCURRENCY_DEFAULT,
}
_INBOX_COMMENT_WAKEUP_REASONS = {"issue_comment_added", "issue_comment_mentioned"}
_INBOX_ACTIVE_WAKEUP_STATUSES = {
    "queued",
    "claimed",
    "deferred_issue_execution",
    "deferred_agent_paused",
}


class AgentConflictError(ValueError):
    pass


def _normalize_url_key(value: str | None) -> str | None:
    if not value:
        return None
    normalized = _URL_KEY_PATTERN.sub("-", value.strip().lower()).strip("-")
    return normalized or None


def _derive_url_key(name: str | None, fallback: str | None = None) -> str:
    return _normalize_url_key(name) or _normalize_url_key(fallback) or "agent"


def _parse_scheduler_heartbeat_policy(
    runtime_config: dict[str, Any],
) -> dict[str, float | bool]:
    heartbeat = runtime_config.get("heartbeat", {})
    config = heartbeat if isinstance(heartbeat, dict) else {}
    enabled = config.get("enabled", True)
    interval = config.get("intervalSec", 0)
    interval_sec = (
        max(0.0, float(interval))
        if isinstance(interval, (int, float)) and not isinstance(interval, bool)
        else 0.0
    )
    return {
        "enabled": enabled if isinstance(enabled, bool) else True,
        "intervalSec": interval_sec
        if interval_sec > 0
        else _DEFAULT_HEARTBEAT_INTERVAL_SEC,
    }


def _materialize_heartbeat_runtime_config(
    runtime_config: dict[str, Any] | None,
) -> dict[str, Any]:
    config = dict(runtime_config or {})
    heartbeat = config.get("heartbeat")
    if heartbeat is None:
        config["heartbeat"] = dict(_DEFAULT_HEARTBEAT_POLICY)
    elif isinstance(heartbeat, dict):
        materialized = {**_DEFAULT_HEARTBEAT_POLICY, **heartbeat}
        interval = materialized.get("intervalSec")
        if (
            not isinstance(interval, (int, float))
            or isinstance(interval, bool)
            or interval <= 0
        ):
            materialized["intervalSec"] = _DEFAULT_HEARTBEAT_INTERVAL_SEC
        config["heartbeat"] = materialized
    return config


def _is_hidden_system_agent_metadata(metadata: dict[str, Any] | None) -> bool:
    if not isinstance(metadata, dict):
        return False
    return (
        metadata.get("hidden") is True
        or metadata.get("systemManaged") == "rudder_copilot"
    )


def _source_issue_ids(payload: HireAgentPayload) -> list[str]:
    issue_ids: list[str] = []
    source_issue_id = payload.get("sourceIssueId")
    if isinstance(source_issue_id, str) and source_issue_id.strip():
        issue_ids.append(source_issue_id.strip())
    for issue_id in payload.get("sourceIssueIds", []):
        if issue_id.strip():
            issue_ids.append(issue_id.strip())
    return list(dict.fromkeys(issue_ids))


def _workspace_key(agent_id: str, name: str) -> str:
    normalized = re.sub(r"[^a-f0-9]", "", agent_id.lower())
    short_id = (
        normalized[:8]
        if len(normalized) >= 8
        else hashlib.sha1(agent_id.encode("utf-8")).hexdigest()[:8]
    )
    return f"{_derive_url_key(name)}--{short_id}"


def _agent_home_root(row: AgentRow) -> Path:
    workspace_key = row.workspace_key or _derive_url_key(row.name, row.id)
    return agent_workspace_root(row.org_id, workspace_key)


def _agent_home_root_from_values(values: dict[str, Any]) -> Path:
    workspace_key = cast(str | None, values.get("workspace_key")) or _derive_url_key(
        cast(str | None, values.get("name")), cast(str, values["id"])
    )
    return agent_workspace_root(cast(str, values["org_id"]), workspace_key)


def _agent_skills_root(row: AgentRow) -> Path:
    return _ensure_agent_workspace_layout(_agent_home_root(row)) / "skills"


def _ensure_agent_workspace_layout(agent_home: Path) -> Path:
    root = agent_home.resolve()
    root.mkdir(parents=True, exist_ok=True)
    for dirname in _AGENT_WORKSPACE_HOME_DIRS:
        (root / dirname).mkdir(parents=True, exist_ok=True)
    return root


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _compact_text(value: str | None, *, limit: int = 140) -> str | None:
    if value is None:
        return None
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 1]}..."


def _relationship_rank(value: str) -> int:
    return {"mentioned": 0, "reviewer": 1, "assignee": 2}.get(value, 3)


def _issue_status_rank(value: str) -> int:
    return {
        "blocked": 0,
        "in_review": 1,
        "in_progress": 2,
        "todo": 3,
    }.get(value, 4)


def _timestamp_desc_rank(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    return -parsed.timestamp()


def _normalized_permissions(value: object, role: str) -> dict[str, bool]:
    if isinstance(value, dict) and isinstance(value.get("canCreateAgents"), bool):
        return {"canCreateAgents": bool(value["canCreateAgents"])}
    return {"canCreateAgents": role == "ceo"}


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _REDACTED
            if _SENSITIVE_KEY_PATTERN.search(key)
            else _sanitize_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    return value


def _contains_redacted(value: Any) -> bool:
    if value == _REDACTED:
        return True
    if isinstance(value, dict):
        return any(_contains_redacted(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_redacted(item) for item in value)
    return False


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _draft_skill_markdown(payload: dict[str, Any]) -> str:
    markdown = payload.get("markdown")
    if isinstance(markdown, str) and markdown.strip():
        return markdown
    lines = [
        "---",
        f"name: {payload['name']}",
    ]
    description = payload.get("description")
    if isinstance(description, str) and description.strip():
        lines.append(f"description: {description.strip()}")
    lines.extend(
        [
            "---",
            "",
            f"# {payload['name']}",
            "",
            description.strip()
            if isinstance(description, str) and description.strip()
            else "Describe what this skill does.",
            "",
        ]
    )
    return "\n".join(lines)


def _skill_description_from_markdown(markdown: str) -> str | None:
    lines = markdown.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        value = line.strip()
        if value == "---":
            return None
        if value.lower().startswith("description:"):
            description = value.split(":", 1)[1].strip().strip("\"'")
            return description or None
    return None


def _skill_evidence_from_payload(
    payload: dict[str, Any],
) -> list[tuple[str, SkillEvidenceKind]]:
    evidence: list[tuple[str, SkillEvidenceKind]] = []

    for section_name in ("context", "result", "usage"):
        section = payload.get(section_name)
        if isinstance(section, dict):
            evidence.extend(_skill_evidence_from_payload(section))

    for key, kind in (
        ("desiredSkills", "requested"),
        ("requestedSkills", "requested"),
        ("loadedSkills", "loaded"),
        ("usedSkills", "used"),
    ):
        evidence.extend(_skill_list_evidence(payload.get(key), cast(SkillEvidenceKind, kind)))

    skills = payload.get("skills")
    if isinstance(skills, dict):
        for kind in _SKILL_EVIDENCE_KINDS:
            evidence.extend((skill, kind) for skill in _string_list(skills.get(kind)))

    raw_evidence = payload.get("skillEvidence")
    if isinstance(raw_evidence, list):
        for item in raw_evidence:
            if not isinstance(item, dict):
                continue
            skill = item.get("skill") or item.get("skillKey") or item.get("key")
            kind = item.get("kind") or item.get("evidence")
            if isinstance(skill, str) and kind in _SKILL_EVIDENCE_KINDS:
                normalized = skill.strip()
                if normalized:
                    evidence.append((normalized, cast(SkillEvidenceKind, kind)))

    return evidence


def _skill_list_evidence(value: object, kind: SkillEvidenceKind) -> list[tuple[str, SkillEvidenceKind]]:
    if not isinstance(value, list):
        return []
    evidence: list[tuple[str, SkillEvidenceKind]] = []
    for item in value:
        if isinstance(item, str):
            normalized = item.strip()
        elif isinstance(item, dict):
            raw = item.get("key") or item.get("runtimeName") or item.get("name")
            normalized = raw.strip() if isinstance(raw, str) else ""
        else:
            normalized = ""
        if normalized:
            evidence.append((normalized, kind))
    return evidence


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        normalized = item.strip()
        if normalized:
            result.append(normalized)
    return result


def _apply_desired_skills_to_entries(
    snapshot: dict[str, Any], desired_skills: list[str]
) -> None:
    desired = set(desired_skills)
    entries = snapshot.get("entries")
    if not isinstance(entries, list):
        return
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        selection_key = entry.get("selectionKey")
        key = entry.get("key")
        candidates = {
            value
            for value in (
                selection_key,
                key,
                f"skills/{key}" if isinstance(key, str) else None,
            )
            if isinstance(value, str) and value
        }
        is_desired = not candidates.isdisjoint(desired)
        entry["desired"] = is_desired
        if is_desired and entry.get("state") == "available":
            entry["state"] = "configured"


def _organization_skill_selection_key(key: str) -> str:
    return key if key.startswith("org:") else f"org:{key}"


def _organization_skill_is_desired(
    skill: Mapping[str, Any], desired_skills: list[str]
) -> bool:
    key = skill.get("key")
    slug = skill.get("slug")
    candidates = {
        value
        for value in (
            key,
            slug,
            f"org:{key}" if isinstance(key, str) else None,
        )
        if isinstance(value, str) and value
    }
    return not candidates.isdisjoint(desired_skills)


def _is_external_skill_entry(entry: dict[str, Any]) -> bool:
    source_class = entry.get("sourceClass")
    return entry.get("managed") is False or source_class in {
        "adapter_home",
        "external",
    }


def _namespace_external_skill_conflicts(
    entries: list[Any], org_skills: Sequence[Mapping[str, Any]]
) -> None:
    managed_names = {
        value
        for skill in org_skills
        for value in (skill.get("key"), skill.get("slug"))
        if isinstance(value, str) and value
    }
    if not managed_names:
        return
    for entry in entries:
        if not isinstance(entry, dict) or not _is_external_skill_entry(entry):
            continue
        runtime_name = entry.get("runtimeName")
        key = entry.get("key")
        selection_key = entry.get("selectionKey")
        names = {
            value
            for value in (runtime_name, key, selection_key)
            if isinstance(value, str) and value
        }
        if managed_names.isdisjoint(names):
            continue
        runtime_slug = (
            runtime_name
            if isinstance(runtime_name, str) and runtime_name
            else key
            if isinstance(key, str) and key
            else selection_key
        )
        if not isinstance(runtime_slug, str) or runtime_slug.startswith("external:"):
            continue
        external_key = f"external:{runtime_slug}"
        entry["key"] = external_key
        entry["selectionKey"] = external_key


def _runtime_config_with_context(
    row: AgentRow, base_config: dict[str, Any] | None = None
) -> dict[str, Any]:
    organization_root = str(organization_skills_root(row.org_id))
    agent_home = _ensure_agent_workspace_layout(_agent_home_root(row))
    instructions_dir = agent_home / "instructions"
    memory_dir = agent_home / "memory"
    life_dir = agent_home / "life"
    skills_dir = agent_home / "skills"
    config = dict(base_config if base_config is not None else row.agent_runtime_config)
    config.setdefault("skillsRootPath", organization_root)
    runtime_context = config.get("_octopus")
    if not isinstance(runtime_context, dict):
        runtime_context = {}
    return {
        **config,
        "_octopus": {
            **runtime_context,
            "orgId": row.org_id,
            "agentId": row.id,
            "agentHome": str(agent_home),
            "agentInstructionsDir": str(instructions_dir),
            "agentMemoryDir": str(memory_dir),
            "agentLifeDir": str(life_dir),
            "organizationSkillsRootPath": organization_root,
            "agentSkillsRootPath": str(skills_dir),
        },
    }


async def prepare_agent_runtime_config(
    session: AsyncSession,
    row: AgentRow,
    *,
    base_config: dict[str, Any] | None = None,
    extra_octopus: dict[str, Any] | None = None,
) -> dict[str, Any]:
    await OrganizationSkillService(session).list(row.org_id)
    config = _runtime_config_with_context(row, base_config)
    configured_skills = (
        _string_list(extra_octopus.get("desiredSkills"))
        if extra_octopus and "desiredSkills" in extra_octopus
        else await list_enabled_skill_keys(session, row.id)
    )
    if extra_octopus:
        runtime_context = config.get("_octopus")
        config["_octopus"] = {
            **(runtime_context if isinstance(runtime_context, dict) else {}),
            **extra_octopus,
        }
    runtime_context = config.get("_octopus")
    config["_octopus"] = {
        **(runtime_context if isinstance(runtime_context, dict) else {}),
        "desiredSkills": configured_skills,
    }
    return config


def _validate_runtime_config(runtime_type: str, config: dict[str, Any]) -> None:
    if runtime_type != "opencode_local":
        return
    model = config.get("model")
    if not isinstance(model, str) or not model.strip():
        raise ValueError(
            "opencode_local requires agentRuntimeConfig.model in provider/model format"
        )
    provider, separator, model_name = model.strip().partition("/")
    if not separator or not provider.strip() or not model_name.strip():
        raise ValueError(
            "opencode_local requires agentRuntimeConfig.model in provider/model format"
        )


class AgentService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_org(self, org_id: str) -> list[Agent]:
        rows = await list_org_agents(self._session, org_id)
        visible = [row for row in rows if row.status != "terminated"]
        skills_by_agent = await list_enabled_skill_keys_by_agent_ids(
            self._session, [row.id for row in visible]
        )
        return [self._to_agent(row, skills_by_agent.get(row.id, [])) for row in visible]

    async def list_instance_scheduler_heartbeats(
        self,
    ) -> list[InstanceSchedulerHeartbeatAgent]:
        result = await self._session.execute(
            select(AgentRow, OrganizationRow)
            .join(OrganizationRow, AgentRow.org_id == OrganizationRow.id)
            .order_by(OrganizationRow.name, AgentRow.name)
        )
        items: list[InstanceSchedulerHeartbeatAgent] = []
        for row, org in result.all():
            if row.status in _SCHEDULER_INELIGIBLE_STATUSES:
                continue
            if _is_hidden_system_agent_metadata(row.metadata_json):
                continue
            policy = _parse_scheduler_heartbeat_policy(row.runtime_config)
            heartbeat_enabled = cast(bool, policy["enabled"])
            interval_sec = cast(float, policy["intervalSec"])
            items.append(
                {
                    "id": row.id,
                    "orgId": row.org_id,
                    "organizationName": org.name,
                    "organizationIssuePrefix": org.issue_prefix,
                    "agentName": row.name,
                    "agentUrlKey": _derive_url_key(row.name, row.id),
                    "role": cast(AgentRole, row.role),
                    "title": row.title,
                    "status": cast(AgentStatus, row.status),
                    "agentRuntimeType": cast(AgentRuntimeType, row.agent_runtime_type),
                    "intervalSec": interval_sec,
                    "heartbeatEnabled": heartbeat_enabled,
                    "schedulerActive": heartbeat_enabled and interval_sec > 0,
                    "lastHeartbeatAt": (
                        row.last_heartbeat_at.isoformat()
                        if row.last_heartbeat_at is not None
                        else None
                    ),
                }
            )
        return sorted(
            items,
            key=lambda item: (
                not item["schedulerActive"],
                item["organizationName"],
                item["agentName"],
            ),
        )

    async def get(self, agent_id: str) -> Agent | None:
        row = await get_agent_by_id(self._session, agent_id)
        if row is None:
            return None
        return self._to_agent(row, await list_enabled_skill_keys(self._session, row.id))

    async def get_detail(self, agent_id: str) -> AgentDetail | None:
        row = await get_agent_by_id(self._session, agent_id)
        if row is None:
            return None
        detail: AgentDetail = {
            **self._to_agent(row, await list_enabled_skill_keys(self._session, row.id)),
            "chainOfCommand": await self._chain_of_command(row),
            "access": self._access_state(row),
        }
        return detail

    async def list_inbox(self, agent_id: str) -> list[AgentInboxItem] | None:
        row = await get_agent_by_id(self._session, agent_id)
        if row is None:
            return None
        issue_rows = await list_agent_inbox_issues(self._session, row.org_id, row.id)
        items_by_issue_id = {
            issue.id: self._to_inbox_item(row.id, issue) for issue in issue_rows
        }
        for wakeup in await self._list_inbox_comment_wakeups(row):
            payload = wakeup.payload if isinstance(wakeup.payload, dict) else {}
            issue_id = payload.get("issueId")
            if not isinstance(issue_id, str) or not issue_id:
                continue
            issue = await self._session.get(IssueRow, issue_id)
            if (
                issue is None
                or issue.org_id != row.org_id
                or issue.hidden_at is not None
            ):
                continue
            item = items_by_issue_id.get(issue.id) or self._to_inbox_item(row.id, issue)
            items_by_issue_id[issue.id] = await self._merge_comment_wakeup(
                row.org_id, item, wakeup
            )
        return sorted(
            items_by_issue_id.values(),
            key=lambda item: (
                _relationship_rank(item["relationship"]),
                _issue_status_rank(item["status"]),
                _timestamp_desc_rank(item["updatedAt"]),
            ),
        )

    async def suggest_name(self, org_id: str) -> str:
        existing = await list_org_agents(self._session, org_id)
        return self._next_role_sequence_name(DEFAULT_AGENT_ROLE, existing)

    async def create_agent(
        self,
        org_id: str,
        payload: CreateAgentPayload,
        *,
        actor_type: str,
        actor_id: str,
    ) -> Agent:
        return await self._create_agent(
            org_id,
            payload,
            actor_type=actor_type,
            actor_id=actor_id,
            status=DEFAULT_AGENT_STATUS,
            activity_action="agent.created",
        )

    async def hire_agent(
        self,
        org_id: str,
        payload: HireAgentPayload,
        *,
        actor_type: str,
        actor_id: str,
    ) -> AgentHireResult:
        organization = await get_organization_by_id(self._session, org_id)
        if organization is None:
            raise ValueError("Organization not found")
        await self._validate_hire_actor(
            org_id, actor_type=actor_type, actor_id=actor_id
        )
        requires_approval = organization.require_board_approval_for_new_agents
        agent_payload = {
            key: value
            for key, value in payload.items()
            if key not in {"sourceIssueId", "sourceIssueIds"}
        }
        agent = await self._create_agent(
            org_id,
            cast(CreateAgentPayload, agent_payload),
            actor_type=actor_type,
            actor_id=actor_id,
            status="pending_approval" if requires_approval else DEFAULT_AGENT_STATUS,
            activity_action="agent.hire_requested"
            if requires_approval
            else "agent.hired",
        )
        if not requires_approval:
            return {"agent": agent, "approval": None}

        issue_ids = _source_issue_ids(payload)
        from .approvals import ApprovalService

        approval_payload: CreateApprovalPayload = {
            "type": "hire_agent",
            "payload": {
                "agentId": agent["id"],
                "hire": dict(payload),
                "sourceIssueIds": issue_ids,
            },
        }
        if issue_ids:
            approval_payload["issueIds"] = issue_ids
        approval = await ApprovalService(self._session).create_approval(
            org_id,
            approval_payload,
            actor_type=actor_type,
            actor_id=actor_id,
        )
        return {"agent": agent, "approval": approval}

    async def _validate_hire_actor(
        self,
        org_id: str,
        *,
        actor_type: str,
        actor_id: str,
    ) -> None:
        if actor_type == "board":
            return
        if actor_type != "agent":
            raise PermissionError("Only board or agent actors can hire agents")
        actor_agent = await get_agent_by_id(self._session, actor_id)
        if actor_agent is None or actor_agent.org_id != org_id:
            raise PermissionError("Agent cannot hire agents for another organization")
        permissions = _normalized_permissions(actor_agent.permissions, actor_agent.role)
        if not permissions["canCreateAgents"]:
            raise PermissionError("Agent does not have permission to create agents")

    async def _create_agent(
        self,
        org_id: str,
        payload: CreateAgentPayload,
        *,
        actor_type: str,
        actor_id: str,
        status: AgentStatus,
        activity_action: str,
    ) -> Agent:
        role = cast(AgentRole, payload.get("role", DEFAULT_AGENT_ROLE))
        manager_id = payload.get("reportsTo")
        if "reportsTo" not in payload and actor_type == "agent":
            manager_id = actor_id
        if manager_id is not None:
            await self._validate_manager(org_id, manager_id)
        existing = await list_org_agents(self._session, org_id)
        requested_name = str(payload.get("name", "")).strip()
        if self._should_use_role_sequence_name(
            requested_name, role=role, actor_type=actor_type
        ):
            name = self._next_role_sequence_name(role, existing)
        else:
            name = self._deduplicate_name(requested_name, existing)
        agent_id = str(uuid.uuid4())
        agent_runtime_type = payload.get("agentRuntimeType", DEFAULT_AGENT_RUNTIME_TYPE)
        agent_runtime_config = normalize_instructions_paths(
            dict(payload.get("agentRuntimeConfig", {}))
        )
        _validate_runtime_config(agent_runtime_type, agent_runtime_config)
        values: dict[str, Any] = {
            "id": agent_id,
            "org_id": org_id,
            "name": name,
            "workspace_key": _workspace_key(agent_id, name),
            "role": role,
            "title": payload.get("title"),
            "icon": payload.get("icon")
            or f"{AGENT_DICEBEAR_NOTIONISTS_ICON_PREFIX}{uuid.uuid4()}",
            "status": status,
            "reports_to": manager_id,
            "capabilities": payload.get("capabilities"),
            "agent_runtime_type": agent_runtime_type,
            "agent_runtime_config": agent_runtime_config,
            "runtime_config": _materialize_heartbeat_runtime_config(
                dict(payload.get("runtimeConfig", {}))
            ),
            "budget_monthly_cents": payload.get("budgetMonthlyCents", 0),
            "spent_monthly_cents": 0,
            "permissions": _normalized_permissions(payload.get("permissions"), role),
            "metadata_json": payload.get("metadata"),
        }
        row = await create_agent(self._session, values)
        agent_home = _ensure_agent_workspace_layout(
            _agent_home_root_from_values(values)
        )
        next_runtime_config = materialize_default_instructions_for_new_agent(
            row, agent_home
        )
        if next_runtime_config is not None:
            updated = await update_agent(
                self._session,
                row.id,
                {"agent_runtime_config": next_runtime_config},
            )
            if updated is not None:
                row = updated
        desired_skills = list(
            payload["desiredSkills"]
            if "desiredSkills" in payload
            else _DEFAULT_ENABLED_SKILLS
        )
        if desired_skills:
            desired_skills = await replace_enabled_skill_keys(
                self._session,
                org_id=org_id,
                agent_id=row.id,
                skill_keys=desired_skills,
            )
        await insert_activity_log(
            self._session,
            org_id=org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action=activity_action,
            entity_type="agent",
            entity_id=row.id,
            details={"name": row.name, "role": row.role},
        )
        return self._to_agent(row, desired_skills)

    async def update_agent(
        self,
        agent_id: str,
        payload: UpdateAgentPayload,
        *,
        actor_type: str,
        actor_id: str,
        revision_source: str = "patch",
        rolled_back_from_revision_id: str | None = None,
    ) -> Agent | None:
        existing = await get_agent_by_id(self._session, agent_id)
        if existing is None:
            return None
        if existing.status == "terminated" and payload.get("status") not in (
            None,
            "terminated",
        ):
            raise AgentConflictError("Terminated agents cannot be resumed")
        if existing.status == "pending_approval" and payload.get("status") not in (
            None,
            "pending_approval",
            "terminated",
        ):
            raise AgentConflictError(
                "Pending approval agents cannot be activated directly"
            )
        if "reportsTo" in payload:
            manager_id = payload["reportsTo"]
            if manager_id is not None:
                await self._validate_manager(existing.org_id, manager_id)
            await self._validate_no_cycle(agent_id, manager_id)
        if "name" in payload:
            next_key = _derive_url_key(payload["name"])
            for row in await list_org_agents(self._session, existing.org_id):
                if (
                    row.id != existing.id
                    and row.status != "terminated"
                    and _derive_url_key(row.name) == next_key
                ):
                    raise AgentConflictError(
                        f"Agent shortname '{next_key}' is already in use in this organization"
                    )
        patch = dict(payload)
        desired_skills: list[str] | None = None
        if "desiredSkills" in patch:
            desired_skills = cast(list[str], patch.pop("desiredSkills"))
        replace_runtime_config = patch.pop("replaceAgentRuntimeConfig", False)
        if "agentRuntimeConfig" in patch and not replace_runtime_config:
            patch["agentRuntimeConfig"] = {
                **existing.agent_runtime_config,
                **cast(dict[str, Any], patch["agentRuntimeConfig"]),
            }
        if "agentRuntimeConfig" in patch:
            patch["agentRuntimeConfig"] = normalize_instructions_paths(
                cast(dict[str, Any], patch["agentRuntimeConfig"])
            )
        next_runtime_type = cast(
            str, patch.get("agentRuntimeType", existing.agent_runtime_type)
        )
        next_runtime_config = cast(
            dict[str, Any],
            patch.get("agentRuntimeConfig", existing.agent_runtime_config),
        )
        _validate_runtime_config(next_runtime_type, next_runtime_config)
        field_map = {
            "name": "name",
            "role": "role",
            "title": "title",
            "icon": "icon",
            "reportsTo": "reports_to",
            "capabilities": "capabilities",
            "agentRuntimeType": "agent_runtime_type",
            "agentRuntimeConfig": "agent_runtime_config",
            "runtimeConfig": "runtime_config",
            "budgetMonthlyCents": "budget_monthly_cents",
            "spentMonthlyCents": "spent_monthly_cents",
            "status": "status",
            "metadata": "metadata_json",
        }
        values = {
            field_map[key]: value for key, value in patch.items() if key in field_map
        }
        before_config = self._config_snapshot(existing)
        row = await update_agent(self._session, agent_id, values)
        if row is None:
            return None
        if desired_skills is not None:
            desired_skills = await replace_enabled_skill_keys(
                self._session,
                org_id=row.org_id,
                agent_id=row.id,
                skill_keys=desired_skills,
            )
        after_config = self._config_snapshot(row)
        changed_keys = [
            key
            for key in _CONFIG_REVISION_FIELDS
            if before_config[key] != after_config[key]
        ]
        if changed_keys:
            await create_config_revision(
                self._session,
                {
                    "org_id": row.org_id,
                    "agent_id": row.id,
                    "created_by_agent_id": actor_id if actor_type == "agent" else None,
                    "created_by_user_id": actor_id if actor_type != "agent" else None,
                    "source": revision_source,
                    "rolled_back_from_revision_id": rolled_back_from_revision_id,
                    "changed_keys": changed_keys,
                    "before_config": _sanitize_value(before_config),
                    "after_config": _sanitize_value(after_config),
                },
            )
        if patch:
            await insert_activity_log(
                self._session,
                org_id=row.org_id,
                actor_type=actor_type,
                actor_id=actor_id,
                action="agent.updated",
                entity_type="agent",
                entity_id=row.id,
                details=patch,
            )
        return self._to_agent(
            row,
            desired_skills
            if desired_skills is not None
            else await list_enabled_skill_keys(self._session, row.id),
        )

    async def apply_runtime_config(
        self,
        agent_id: str,
        config: dict[str, Any],
        *,
        actor_type: str,
        actor_id: str,
        source: str,
    ) -> AgentRow | None:
        """Replace ``agent_runtime_config`` and record a config revision when
        revision-tracked fields change.

        Instruction edits compute a full replacement config and used to persist
        it through the database-layer ``update_agent`` directly, bypassing the
        revision recording. Routing those edits here keeps the config revision
        history populated, matching upstream where instruction mutations call the
        agent update with ``recordRevision``.
        """

        existing = await get_agent_by_id(self._session, agent_id)
        if existing is None:
            return None
        before_config = self._config_snapshot(existing)
        row = await update_agent(
            self._session, agent_id, {"agent_runtime_config": config}
        )
        if row is None:
            return None
        after_config = self._config_snapshot(row)
        changed_keys = [
            key
            for key in _CONFIG_REVISION_FIELDS
            if before_config[key] != after_config[key]
        ]
        if changed_keys:
            await create_config_revision(
                self._session,
                {
                    "org_id": row.org_id,
                    "agent_id": row.id,
                    "created_by_agent_id": actor_id if actor_type == "agent" else None,
                    "created_by_user_id": actor_id if actor_type != "agent" else None,
                    "source": source,
                    "rolled_back_from_revision_id": None,
                    "changed_keys": changed_keys,
                    "before_config": _sanitize_value(before_config),
                    "after_config": _sanitize_value(after_config),
                },
            )
        return row

    async def get_skill_snapshot(self, agent_id: str) -> AgentSkillSnapshot | None:
        row = await get_agent_by_id(self._session, agent_id)
        if row is None:
            return None
        desired_skills = await list_enabled_skill_keys(self._session, row.id)
        runtime_config = await self._runtime_config_with_desired_skill_sources(
            row, desired_skills
        )
        snapshot = await get_runtime_adapter(row.agent_runtime_type).list_skills(
            runtime_config, desired_skills
        )
        snapshot["desiredSkills"] = desired_skills
        await self._merge_organization_skill_entries(row, snapshot, desired_skills)
        _apply_desired_skills_to_entries(snapshot, desired_skills)
        return cast(AgentSkillSnapshot, snapshot)

    async def sync_skills(
        self,
        agent_id: str,
        desired_skills: list[str],
        *,
        actor_type: str,
        actor_id: str,
    ) -> AgentSkillSnapshot | None:
        existing = await get_agent_by_id(self._session, agent_id)
        if existing is None:
            return None
        desired_skills = await replace_enabled_skill_keys(
            self._session,
            org_id=existing.org_id,
            agent_id=existing.id,
            skill_keys=desired_skills,
        )
        await insert_activity_log(
            self._session,
            org_id=existing.org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="agent.skills_synced",
            entity_type="agent",
            entity_id=existing.id,
            details={"desiredSkills": desired_skills},
        )
        runtime_config = await self._runtime_config_with_desired_skill_sources(
            existing, desired_skills
        )
        snapshot = await get_runtime_adapter(existing.agent_runtime_type).sync_skills(
            runtime_config, desired_skills
        )
        snapshot["desiredSkills"] = desired_skills
        await self._merge_organization_skill_entries(existing, snapshot, desired_skills)
        _apply_desired_skills_to_entries(snapshot, desired_skills)
        return cast(AgentSkillSnapshot, snapshot)

    async def enable_skills(
        self,
        agent_id: str,
        skills: list[str],
        *,
        actor_type: str,
        actor_id: str,
    ) -> AgentSkillSnapshot | None:
        existing = await get_agent_by_id(self._session, agent_id)
        if existing is None:
            return None
        desired_skills = await add_enabled_skill_keys(
            self._session,
            org_id=existing.org_id,
            agent_id=existing.id,
            skill_keys=skills,
        )
        runtime_config = await self._runtime_config_with_desired_skill_sources(
            existing, desired_skills
        )
        snapshot = await get_runtime_adapter(existing.agent_runtime_type).sync_skills(
            runtime_config, desired_skills
        )
        snapshot["desiredSkills"] = desired_skills
        await self._merge_organization_skill_entries(existing, snapshot, desired_skills)
        _apply_desired_skills_to_entries(snapshot, desired_skills)
        await insert_activity_log(
            self._session,
            org_id=existing.org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="agent.skills_enabled",
            entity_type="agent",
            entity_id=existing.id,
            details={
                "requestedSkills": skills,
                "desiredSkills": snapshot["desiredSkills"],
                "mode": snapshot["mode"],
                "supported": snapshot["supported"],
                "entryCount": len(snapshot["entries"]),
                "warningCount": len(snapshot["warnings"]),
            },
        )
        return cast(AgentSkillSnapshot, snapshot)

    async def _runtime_config_with_desired_skill_sources(
        self, row: AgentRow, desired_skills: list[str]
    ) -> dict[str, Any]:
        config = _runtime_config_with_context(row)
        org_skills = await OrganizationSkillService(self._session).list(row.org_id)
        desired_sources = [
            {
                "key": skill["key"],
                "selectionKey": _organization_skill_selection_key(str(skill["key"])),
                "runtimeName": skill["slug"],
                "sourcePath": skill["sourcePath"],
            }
            for skill in org_skills
            if _organization_skill_is_desired(skill, desired_skills)
            and isinstance(skill.get("sourcePath"), str)
            and skill.get("sourcePath")
        ]
        runtime_context = config.get("_octopus")
        config["_octopus"] = {
            **(runtime_context if isinstance(runtime_context, dict) else {}),
            "desiredSkills": desired_skills,
            "desiredSkillSources": desired_sources,
        }
        return config

    async def _merge_organization_skill_entries(
        self, row: AgentRow, snapshot: dict[str, Any], desired_skills: list[str]
    ) -> None:
        entries = snapshot.get("entries")
        if not isinstance(entries, list):
            return
        org_skills = await OrganizationSkillService(self._session).list(row.org_id)
        _namespace_external_skill_conflicts(entries, org_skills)
        existing_refs = {
            value
            for entry in entries
            if isinstance(entry, dict) and not _is_external_skill_entry(entry)
            for value in (
                entry.get("key"),
                entry.get("selectionKey"),
                entry.get("runtimeName"),
            )
            if isinstance(value, str) and value
        }
        desired = set(desired_skills)
        for skill in org_skills:
            key = str(skill["key"])
            slug = str(skill["slug"])
            if skill.get("sourceBadge") == "built-in":
                continue
            if key in existing_refs or slug in existing_refs:
                continue
            selection_key = _organization_skill_selection_key(key)
            metadata = skill.get("metadata")
            source_kind = (
                metadata.get("sourceKind")
                if isinstance(metadata, dict)
                and isinstance(metadata.get("sourceKind"), str)
                else "organization_managed"
            )
            source_label = skill.get("sourceLabel")
            is_desired = (
                selection_key in desired
                or key in desired
                or slug in desired
                or f"org:{key}" in desired
            )
            entries.append(
                {
                    "key": key,
                    "selectionKey": selection_key,
                    "runtimeName": slug,
                    "sourceRole": slug,
                    "description": skill.get("description"),
                    "desired": is_desired,
                    "configurable": True,
                    "alwaysEnabled": False,
                    "managed": True,
                    "state": "configured" if is_desired else "available",
                    "sourceClass": "organization",
                    "sourceBadge": skill.get("sourceBadge"),
                    "sourceLabel": source_label,
                    "origin": source_kind,
                    "originLabel": source_label or "Organization skill",
                    "locationLabel": "Organization skill",
                    "readOnly": not bool(skill.get("editable")),
                    "sourcePath": skill.get("sourcePath"),
                    "targetPath": None,
                    "workspaceEditPath": skill.get("workspaceEditPath"),
                    "detail": skill.get("editableReason"),
                }
            )
        entries.sort(key=lambda entry: str(entry.get("key", "")))

    async def create_private_skill(
        self,
        agent_id: str,
        payload: dict[str, Any],
        *,
        actor_type: str,
        actor_id: str,
    ) -> dict[str, Any] | None:
        existing = await get_agent_by_id(self._session, agent_id)
        if existing is None:
            return None
        slug = _derive_url_key(payload.get("slug") or payload["name"])
        skills_root = _agent_skills_root(existing)
        skill_dir = (skills_root / slug).resolve()
        if not _is_relative_to(skill_dir, skills_root.resolve()):
            raise ValueError("Invalid agent skill slug")
        skill_file = skill_dir / "SKILL.md"
        if skill_file.is_file():
            raise AgentConflictError(f"Agent skill already exists: {slug}")
        skill_dir.mkdir(parents=True, exist_ok=True)
        markdown = _draft_skill_markdown(payload)
        skill_file.write_text(markdown, encoding="utf-8")
        description = _skill_description_from_markdown(markdown) or payload.get(
            "description"
        )
        entry = {
            "key": slug,
            "selectionKey": f"agent:{slug}",
            "runtimeName": slug,
            "description": description,
            "desired": False,
            "configurable": True,
            "alwaysEnabled": False,
            "managed": False,
            "state": "external",
            "sourceClass": "agent_home",
            "origin": "user_installed",
            "originLabel": "Agent skill",
            "locationLabel": "AGENT_HOME/skills",
            "readOnly": False,
            "sourcePath": str(skill_dir),
            "targetPath": None,
            "workspaceEditPath": str(skill_file),
            "detail": "Installed, not enabled. Future runs will not load it until enabled.",
        }
        await insert_activity_log(
            self._session,
            org_id=existing.org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="agent.private_skill_created",
            entity_type="agent",
            entity_id=existing.id,
            details={
                "slug": entry["key"],
                "selectionKey": entry["selectionKey"],
                "sourcePath": entry["sourcePath"],
            },
        )
        return entry

    async def get_skill_analytics(
        self, agent_id: str, *, window_days: int = 30
    ) -> AgentSkillAnalytics | None:
        existing = await get_agent_by_id(self._session, agent_id)
        if existing is None:
            return None
        end_date = datetime.now(UTC).date()
        start_date = end_date - timedelta(days=max(window_days, 1) - 1)
        start_time = datetime.combine(start_date, datetime.min.time(), tzinfo=UTC)
        sources = await list_skill_usage_sources(
            self._session,
            org_id=existing.org_id,
            agent_id=existing.id,
            start_time=start_time,
        )
        skill_counts: dict[str, dict[str, int]] = {}
        day_counts: dict[str, dict[str, int]] = {}
        evidence_counts = {"used": 0, "requested": 0, "loaded": 0}
        run_ids: set[str] = set()

        for source in sources:
            source_evidence = list(_skill_evidence_from_payload(source.payload))
            if not source_evidence:
                continue
            if source.run_id is not None:
                run_ids.add(source.run_id)
            day = source.created_at.date().isoformat()
            day_bucket = day_counts.setdefault(
                day, {"used": 0, "requested": 0, "loaded": 0}
            )
            for skill_key, kind in source_evidence:
                evidence_counts[kind] += 1
                day_bucket[kind] += 1
                skill_bucket = skill_counts.setdefault(
                    skill_key,
                    {
                        "used": 0,
                        "requested": 0,
                        "loaded": 0,
                        "totalCount": 0,
                    },
                )
                skill_bucket[kind] += 1
                skill_bucket["totalCount"] += 1

        skills = [
            {"skill": skill_key, **counts}
            for skill_key, counts in sorted(
                skill_counts.items(),
                key=lambda item: (-item[1]["totalCount"], item[0]),
            )
        ]
        days = [
            {"date": day, **counts}
            for day, counts in sorted(day_counts.items(), reverse=True)
        ]
        return {
            "agentId": existing.id,
            "orgId": existing.org_id,
            "windowDays": window_days,
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "totalCount": sum(evidence_counts.values()),
            "totalRunsWithSkills": len(run_ids),
            "evidenceCounts": evidence_counts,
            "skills": skills,
            "days": days,
        }

    async def get_configuration(self, agent_id: str) -> AgentConfiguration | None:
        row = await get_agent_by_id(self._session, agent_id)
        if row is None:
            return None
        return {
            "id": row.id,
            "orgId": row.org_id,
            "name": row.name,
            "role": cast(AgentRole, row.role),
            "title": row.title,
            "status": cast(AgentStatus, row.status),
            "reportsTo": row.reports_to,
            "capabilities": row.capabilities,
            "desiredSkills": await list_enabled_skill_keys(self._session, row.id),
            "agentRuntimeType": cast(AgentRuntimeType, row.agent_runtime_type),
            "agentRuntimeConfig": cast(
                dict[str, Any], _sanitize_value(row.agent_runtime_config)
            ),
            "runtimeConfig": cast(
                dict[str, Any],
                _sanitize_value(
                    _materialize_heartbeat_runtime_config(row.runtime_config)
                ),
            ),
            "permissions": cast(
                Any, _normalized_permissions(row.permissions, row.role)
            ),
            "updatedAt": row.updated_at.isoformat(),
        }

    async def list_configurations_for_org(
        self, org_id: str
    ) -> list[AgentConfiguration]:
        rows = await list_org_agents(self._session, org_id)
        configurations: list[AgentConfiguration] = []
        for row in rows:
            if row.status == "terminated":
                continue
            configuration = await self.get_configuration(row.id)
            if configuration is not None:
                configurations.append(configuration)
        return configurations

    async def list_config_revisions(self, agent_id: str) -> list[AgentConfigRevision]:
        rows = await list_config_revisions(self._session, agent_id)
        return [self._to_config_revision(row) for row in rows]

    async def get_config_revision(
        self, agent_id: str, revision_id: str
    ) -> AgentConfigRevision | None:
        row = await get_config_revision(self._session, agent_id, revision_id)
        return self._to_config_revision(row) if row is not None else None

    async def rollback_config_revision(
        self,
        agent_id: str,
        revision_id: str,
        *,
        actor_type: str,
        actor_id: str,
    ) -> Agent | None:
        revision = await get_config_revision(self._session, agent_id, revision_id)
        if revision is None:
            return None
        if _contains_redacted(revision.after_config):
            raise ValueError(
                "Cannot roll back a revision that contains redacted secret values"
            )
        snapshot = revision.after_config
        payload = cast(
            UpdateAgentPayload,
            {key: snapshot[key] for key in _CONFIG_REVISION_FIELDS if key in snapshot},
        )
        updated = await self.update_agent(
            agent_id,
            payload,
            actor_type=actor_type,
            actor_id=actor_id,
            revision_source="rollback",
            rolled_back_from_revision_id=revision.id,
        )
        if updated is not None:
            await insert_activity_log(
                self._session,
                org_id=updated["orgId"],
                actor_type=actor_type,
                actor_id=actor_id,
                action="agent.config_rolled_back",
                entity_type="agent",
                entity_id=agent_id,
                details={"revisionId": revision_id},
            )
        return updated

    async def get_runtime_state(self, agent_id: str) -> AgentRuntimeState | None:
        agent = await get_agent_by_id(self._session, agent_id)
        if agent is None:
            return None
        state = await self._ensure_runtime_state(agent)
        sessions = await list_task_sessions(self._session, agent_id)
        latest = sessions[0] if sessions else None
        return self._to_runtime_state(state, latest)

    async def list_task_sessions(self, agent_id: str) -> list[AgentTaskSession]:
        rows = await list_task_sessions(self._session, agent_id)
        return [self._to_task_session(row) for row in rows]

    async def reset_runtime_session(
        self,
        agent_id: str,
        payload: ResetAgentSessionPayload,
        *,
        actor_type: str,
        actor_id: str,
    ) -> ResetAgentSessionResult | None:
        agent = await get_agent_by_id(self._session, agent_id)
        if agent is None:
            return None
        state = await self._ensure_runtime_state(agent)
        task_key = payload.get("taskKey")
        cleared = await delete_task_sessions(
            self._session,
            org_id=agent.org_id,
            agent_id=agent.id,
            task_key=task_key,
            agent_runtime_type=agent.agent_runtime_type if task_key else None,
        )
        values: dict[str, Any] = {"session_id": None, "last_error": None}
        if not task_key:
            values["state_json"] = {}
        updated = await update_runtime_state(self._session, state.agent_id, values)
        if updated is None:
            return None
        await insert_activity_log(
            self._session,
            org_id=agent.org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="agent.runtime_session_reset",
            entity_type="agent",
            entity_id=agent.id,
            details={"taskKey": task_key},
        )
        return {
            **self._to_runtime_state(updated, None),
            "clearedTaskSessions": cleared,
        }

    async def pause_agent(
        self, agent_id: str, *, actor_type: str, actor_id: str
    ) -> Agent | None:
        existing = await get_agent_by_id(self._session, agent_id)
        if existing is None:
            return None
        if existing.status == "terminated":
            raise AgentConflictError("Cannot pause terminated agent")
        row = await update_agent(
            self._session,
            agent_id,
            {
                "status": "paused",
                "pause_reason": "manual",
                "paused_at": datetime.now(UTC),
            },
        )
        if row is not None:
            await self._record_lifecycle(row, "agent.paused", actor_type, actor_id)
        return (
            self._to_agent(row, await list_enabled_skill_keys(self._session, row.id))
            if row is not None
            else None
        )

    async def resume_agent(
        self, agent_id: str, *, actor_type: str, actor_id: str
    ) -> Agent | None:
        existing = await get_agent_by_id(self._session, agent_id)
        if existing is None:
            return None
        if existing.status == "terminated":
            raise AgentConflictError("Cannot resume terminated agent")
        if existing.status == "pending_approval":
            raise AgentConflictError("Pending approval agents cannot be resumed")
        row = await update_agent(
            self._session,
            agent_id,
            {"status": "idle", "pause_reason": None, "paused_at": None},
        )
        if row is not None:
            await self._record_lifecycle(row, "agent.resumed", actor_type, actor_id)
        return (
            self._to_agent(row, await list_enabled_skill_keys(self._session, row.id))
            if row is not None
            else None
        )

    async def terminate_agent(
        self, agent_id: str, *, actor_type: str, actor_id: str
    ) -> Agent | None:
        existing = await get_agent_by_id(self._session, agent_id)
        if existing is None:
            return None
        row = await update_agent(
            self._session,
            agent_id,
            {"status": "terminated", "pause_reason": None, "paused_at": None},
        )
        if row is not None:
            await self._record_lifecycle(row, "agent.terminated", actor_type, actor_id)
        return (
            self._to_agent(row, await list_enabled_skill_keys(self._session, row.id))
            if row is not None
            else None
        )

    async def _record_lifecycle(
        self, row: AgentRow, action: str, actor_type: str, actor_id: str
    ) -> None:
        await insert_activity_log(
            self._session,
            org_id=row.org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            entity_type="agent",
            entity_id=row.id,
        )

    async def _validate_manager(self, org_id: str, manager_id: str) -> None:
        manager = await get_agent_by_id(self._session, manager_id)
        if manager is None:
            raise ValueError("Manager not found")
        if manager.org_id != org_id:
            raise ValueError("Manager must belong to same organization")

    async def _validate_no_cycle(self, agent_id: str, manager_id: str | None) -> None:
        if manager_id is None:
            return
        if manager_id == agent_id:
            raise ValueError("Agent cannot report to itself")
        current = manager_id
        while current is not None:
            if current == agent_id:
                raise ValueError("Reporting relationship would create cycle")
            row = await get_agent_by_id(self._session, current)
            current = row.reports_to if row is not None else None

    def _deduplicate_name(self, requested: str, existing: Sequence[AgentRow]) -> str:
        used = {
            _derive_url_key(row.name) for row in existing if row.status != "terminated"
        }
        if _derive_url_key(requested) not in used:
            return requested
        index = 2
        while _derive_url_key(f"{requested} {index}") in used:
            index += 1
        return f"{requested} {index}"

    def _should_use_role_sequence_name(
        self, requested: str, *, role: AgentRole, actor_type: str
    ) -> bool:
        if actor_type == "agent":
            return True
        if not requested:
            return True
        return _derive_url_key(requested) == _derive_url_key(role)

    def _next_role_sequence_name(
        self, role: AgentRole, existing: Sequence[AgentRow]
    ) -> str:
        prefix = _derive_url_key(role)
        used: set[int] = set()
        for row in existing:
            if row.status == "terminated":
                continue
            key = _derive_url_key(row.name)
            if key == prefix:
                used.add(1)
                continue
            marker = f"{prefix}-"
            if not key.startswith(marker):
                continue
            suffix = key[len(marker) :]
            if suffix.isdigit():
                used.add(int(suffix))
        index = 1
        while index in used:
            index += 1
        return f"{prefix}-{index}"

    async def _chain_of_command(self, row: AgentRow) -> list[AgentChainOfCommandEntry]:
        chain: list[AgentChainOfCommandEntry] = []
        manager_id = row.reports_to
        while manager_id is not None:
            manager = await get_agent_by_id(self._session, manager_id)
            if manager is None:
                break
            chain.append(
                {
                    "id": manager.id,
                    "name": manager.name,
                    "role": cast(AgentRole, manager.role),
                    "title": manager.title,
                }
            )
            manager_id = manager.reports_to
        return chain

    def _access_state(self, row: AgentRow) -> AgentAccessState:
        return {
            "canAssignTasks": row.role == "ceo",
            "taskAssignSource": "ceo_role" if row.role == "ceo" else "none",
            "membership": None,
            "grants": [],
        }

    def _to_agent(
        self, row: AgentRow, desired_skills: list[str] | None = None
    ) -> Agent:
        return {
            "id": row.id,
            "orgId": row.org_id,
            "name": row.name,
            "urlKey": _derive_url_key(row.name, row.id),
            "role": cast(AgentRole, row.role),
            "title": row.title,
            "icon": row.icon,
            "status": cast(AgentStatus, row.status),
            "reportsTo": row.reports_to,
            "capabilities": row.capabilities,
            "desiredSkills": list(desired_skills or []),
            "agentRuntimeType": cast(AgentRuntimeType, row.agent_runtime_type),
            "agentRuntimeConfig": row.agent_runtime_config,
            "runtimeConfig": _materialize_heartbeat_runtime_config(row.runtime_config),
            "budgetMonthlyCents": row.budget_monthly_cents,
            "spentMonthlyCents": row.spent_monthly_cents,
            "pauseReason": cast(PauseReason | None, row.pause_reason),
            "pausedAt": _iso(row.paused_at),
            "permissions": cast(
                Any, _normalized_permissions(row.permissions, row.role)
            ),
            "lastHeartbeatAt": _iso(row.last_heartbeat_at),
            "metadata": row.metadata_json,
            "createdAt": row.created_at.isoformat(),
            "updatedAt": row.updated_at.isoformat(),
        }

    def _to_inbox_item(self, agent_id: str, row: IssueRow) -> AgentInboxItem:
        relationship = "reviewer" if row.reviewer_agent_id == agent_id else "assignee"
        return {
            "relationship": relationship,
            "issueId": row.id,
            "identifier": row.identifier,
            "title": row.title,
            "status": cast(IssueStatus, row.status),
            "priority": cast(IssuePriority, row.priority),
            "checkoutRunId": row.checkout_run_id,
            "executionRunId": row.execution_run_id,
            "wakeReason": None,
            "wakeCommentId": None,
            "commentPreview": None,
            "updatedAt": row.updated_at.isoformat(),
        }

    async def _list_inbox_comment_wakeups(
        self, agent: AgentRow
    ) -> Sequence[AgentWakeupRequestRow]:
        result = await self._session.execute(
            select(AgentWakeupRequestRow)
            .where(
                AgentWakeupRequestRow.org_id == agent.org_id,
                AgentWakeupRequestRow.agent_id == agent.id,
                AgentWakeupRequestRow.reason.in_(_INBOX_COMMENT_WAKEUP_REASONS),
                AgentWakeupRequestRow.status.in_(_INBOX_ACTIVE_WAKEUP_STATUSES),
            )
            .order_by(AgentWakeupRequestRow.requested_at.desc())
        )
        return result.scalars().all()

    async def _merge_comment_wakeup(
        self,
        org_id: str,
        item: AgentInboxItem,
        wakeup: AgentWakeupRequestRow,
    ) -> AgentInboxItem:
        payload = wakeup.payload if isinstance(wakeup.payload, dict) else {}
        comment_id = payload.get("commentId")
        wake_time = wakeup.requested_at.isoformat()
        if (
            wakeup.reason == "issue_comment_mentioned"
            and item["relationship"] != "reviewer"
        ):
            item = {**item, "relationship": "mentioned"}
        if item["updatedAt"] < wake_time:
            item = {**item, "updatedAt": wake_time}
        return {
            **item,
            "wakeReason": wakeup.reason,
            "wakeCommentId": comment_id if isinstance(comment_id, str) else None,
            "commentPreview": await self._comment_preview(org_id, comment_id),
        }

    async def _comment_preview(self, org_id: str, comment_id: object) -> str | None:
        if not isinstance(comment_id, str) or not comment_id:
            return None
        comment = await self._session.get(IssueCommentRow, comment_id)
        if comment is None or comment.org_id != org_id:
            return None
        return _compact_text(comment.body)

    def _config_snapshot(self, row: AgentRow) -> dict[str, Any]:
        return {
            "name": row.name,
            "role": row.role,
            "title": row.title,
            "reportsTo": row.reports_to,
            "capabilities": row.capabilities,
            "agentRuntimeType": row.agent_runtime_type,
            "agentRuntimeConfig": row.agent_runtime_config,
            "runtimeConfig": row.runtime_config,
            "budgetMonthlyCents": row.budget_monthly_cents,
            "metadata": row.metadata_json,
        }

    def _to_config_revision(self, row: AgentConfigRevisionRow) -> AgentConfigRevision:
        return {
            "id": row.id,
            "orgId": row.org_id,
            "agentId": row.agent_id,
            "createdByAgentId": row.created_by_agent_id,
            "createdByUserId": row.created_by_user_id,
            "source": row.source,
            "rolledBackFromRevisionId": row.rolled_back_from_revision_id,
            "changedKeys": row.changed_keys,
            "beforeConfig": cast(dict[str, Any], _sanitize_value(row.before_config)),
            "afterConfig": cast(dict[str, Any], _sanitize_value(row.after_config)),
            "createdAt": row.created_at.isoformat(),
        }

    async def _ensure_runtime_state(self, agent: AgentRow) -> AgentRuntimeStateRow:
        existing = await get_runtime_state(self._session, agent.id)
        if existing is not None:
            return existing
        return await create_runtime_state(
            self._session,
            {
                "agent_id": agent.id,
                "org_id": agent.org_id,
                "agent_runtime_type": agent.agent_runtime_type,
                "state_json": {},
            },
        )

    def _to_runtime_state(
        self, row: AgentRuntimeStateRow, latest_session: AgentTaskSessionRow | None
    ) -> AgentRuntimeState:
        return {
            "agentId": row.agent_id,
            "orgId": row.org_id,
            "agentRuntimeType": row.agent_runtime_type,
            "sessionId": row.session_id,
            "stateJson": row.state_json,
            "lastRunId": row.last_run_id,
            "lastRunStatus": row.last_run_status,
            "totalInputTokens": row.total_input_tokens,
            "totalOutputTokens": row.total_output_tokens,
            "totalCachedInputTokens": row.total_cached_input_tokens,
            "totalCostCents": row.total_cost_cents,
            "lastError": row.last_error,
            "createdAt": row.created_at.isoformat(),
            "updatedAt": row.updated_at.isoformat(),
            "sessionDisplayId": (
                latest_session.session_display_id
                if latest_session is not None
                else row.session_id
            ),
            "sessionParamsJson": (
                cast(
                    dict[str, Any] | None,
                    _sanitize_value(latest_session.session_params_json),
                )
                if latest_session is not None
                else None
            ),
        }

    def _to_task_session(self, row: AgentTaskSessionRow) -> AgentTaskSession:
        return {
            "id": row.id,
            "orgId": row.org_id,
            "agentId": row.agent_id,
            "agentRuntimeType": row.agent_runtime_type,
            "taskKey": row.task_key,
            "sessionParamsJson": cast(
                dict[str, Any] | None, _sanitize_value(row.session_params_json)
            ),
            "sessionDisplayId": row.session_display_id,
            "lastRunId": row.last_run_id,
            "lastError": row.last_error,
            "createdAt": row.created_at.isoformat(),
            "updatedAt": row.updated_at.isoformat(),
        }
