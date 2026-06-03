from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
from pathlib import Path
import re
from collections.abc import Sequence
from typing import Any, cast
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.activity_log import insert_activity_log
from packages.database.queries.agents import (
    create_agent,
    get_agent_by_id,
    list_org_agents,
    update_agent,
)
from packages.database.queries.organizations import get_organization_by_id
from packages.database.queries.agent_skills import (
    add_enabled_skill_keys,
    list_enabled_skill_keys,
    list_enabled_skill_keys_by_agent_ids,
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
from packages.shared.types.agent import (
    Agent,
    AgentAccessState,
    AgentChainOfCommandEntry,
    AgentConfigRevision,
    AgentConfiguration,
    AgentDetail,
    AgentHireResult,
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
from packages.shared.types.approval import CreateApprovalPayload
from packages.runtimes import get_runtime_adapter

from .agent_instructions import (
    materialize_default_instructions_for_new_agent,
    normalize_instructions_paths,
)
from .organization_skills import OrganizationSkillService, organization_skills_root
from .agent_names import pick_unique_agent_name

_URL_KEY_PATTERN = re.compile(r"[^a-z0-9]+")
_SENSITIVE_KEY_PATTERN = re.compile(
    r"(api[-_]?key|access[-_]?token|auth(?:_?token)?|authorization|bearer|secret|passwd|password|credential|jwt|private[-_]?key|cookie|connectionstring)",
    re.IGNORECASE,
)
_REDACTED = "***REDACTED***"
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


class AgentConflictError(ValueError):
    pass


def _normalize_url_key(value: str | None) -> str | None:
    if not value:
        return None
    normalized = _URL_KEY_PATTERN.sub("-", value.strip().lower()).strip("-")
    return normalized or None


def _derive_url_key(name: str | None, fallback: str | None = None) -> str:
    return _normalize_url_key(name) or _normalize_url_key(fallback) or "agent"


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
    workspace_key = _derive_url_key(row.workspace_key, row.id)
    return (
        Path.cwd()
        / ".octopus"
        / "workspaces"
        / f"org_{row.org_id}"
        / "agents"
        / workspace_key
    ).resolve()


def _agent_home_root_from_values(values: dict[str, Any]) -> Path:
    workspace_key = _derive_url_key(
        cast(str | None, values.get("workspace_key")), cast(str, values["id"])
    )
    return (
        Path.cwd()
        / ".octopus"
        / "workspaces"
        / f"org_{values['org_id']}"
        / "agents"
        / workspace_key
    ).resolve()


def _agent_skills_root(row: AgentRow) -> Path:
    return _agent_home_root(row) / "skills"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


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
        is_desired = selection_key in desired or key in desired
        entry["desired"] = is_desired
        if is_desired and entry.get("state") == "available":
            entry["state"] = "configured"


def _organization_skill_selection_key(key: str) -> str:
    return key if key.startswith("org:") else f"org:{key}"


def _runtime_config_with_context(row: AgentRow) -> dict[str, Any]:
    organization_root = str(organization_skills_root(row.org_id))
    config = dict(row.agent_runtime_config)
    config.setdefault("skillsRootPath", organization_root)
    return {
        **config,
        "_octopus": {
            "orgId": row.org_id,
            "agentId": row.id,
            "organizationSkillsRootPath": organization_root,
            "agentSkillsRootPath": str(_agent_skills_root(row)),
        },
    }


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

    async def suggest_name(self, org_id: str) -> str:
        existing = await list_org_agents(self._session, org_id)
        name = pick_unique_agent_name([(row.name, row.status) for row in existing])
        return self._deduplicate_name(name, existing)

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
        manager_id = payload.get("reportsTo")
        if manager_id is not None:
            await self._validate_manager(org_id, manager_id)
        existing = await list_org_agents(self._session, org_id)
        requested_name = str(payload.get("name", "")).strip()
        candidate_name = requested_name or pick_unique_agent_name(
            [(row.name, row.status) for row in existing]
        )
        name = self._deduplicate_name(candidate_name, existing)
        agent_id = str(uuid.uuid4())
        role = cast(AgentRole, payload.get("role", DEFAULT_AGENT_ROLE))
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
            "reports_to": payload.get("reportsTo"),
            "capabilities": payload.get("capabilities"),
            "agent_runtime_type": agent_runtime_type,
            "agent_runtime_config": agent_runtime_config,
            "runtime_config": dict(payload.get("runtimeConfig", {})),
            "budget_monthly_cents": payload.get("budgetMonthlyCents", 0),
            "spent_monthly_cents": 0,
            "permissions": _normalized_permissions(payload.get("permissions"), role),
            "metadata_json": payload.get("metadata"),
        }
        row = await create_agent(self._session, values)
        next_runtime_config = materialize_default_instructions_for_new_agent(
            row, _agent_home_root_from_values(values)
        )
        if next_runtime_config is not None:
            updated = await update_agent(
                self._session,
                row.id,
                {"agent_runtime_config": next_runtime_config},
            )
            if updated is not None:
                row = updated
        desired_skills = list(payload.get("desiredSkills", []))
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

    async def get_skill_snapshot(self, agent_id: str) -> AgentSkillSnapshot | None:
        row = await get_agent_by_id(self._session, agent_id)
        if row is None:
            return None
        desired_skills = await list_enabled_skill_keys(self._session, row.id)
        snapshot = await get_runtime_adapter(row.agent_runtime_type).list_skills(
            _runtime_config_with_context(row), desired_skills
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
        snapshot = await get_runtime_adapter(existing.agent_runtime_type).sync_skills(
            _runtime_config_with_context(existing), desired_skills
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
        snapshot = await get_runtime_adapter(existing.agent_runtime_type).sync_skills(
            _runtime_config_with_context(existing), desired_skills
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

    async def _merge_organization_skill_entries(
        self, row: AgentRow, snapshot: dict[str, Any], desired_skills: list[str]
    ) -> None:
        entries = snapshot.get("entries")
        if not isinstance(entries, list):
            return
        existing_refs = {
            value
            for entry in entries
            if isinstance(entry, dict)
            for value in (
                entry.get("key"),
                entry.get("selectionKey"),
                entry.get("runtimeName"),
            )
            if isinstance(value, str) and value
        }
        desired = set(desired_skills)
        org_skills = await OrganizationSkillService(self._session).list(row.org_id)
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
        return {
            "agentId": existing.id,
            "orgId": existing.org_id,
            "windowDays": window_days,
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "totalCount": 0,
            "totalRunsWithSkills": 0,
            "evidenceCounts": {"used": 0, "requested": 0, "loaded": 0},
            "skills": [],
            "days": [],
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
            "runtimeConfig": cast(dict[str, Any], _sanitize_value(row.runtime_config)),
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
            "runtimeConfig": row.runtime_config,
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
