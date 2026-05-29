from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
import re
import shutil
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.activity_log import insert_activity_log
from packages.database.queries.agent_skills import list_enabled_skill_keys_by_agent_ids
from packages.database.queries.agents import list_org_agents
from packages.database.queries.organization_skills import (
    create_organization_skill,
    delete_enabled_skill_key,
    delete_organization_skill,
    get_organization_skill,
    get_organization_skill_by_key,
    list_organization_skills,
    update_organization_skill,
)
from packages.database.queries.organizations import (
    get_organization_by_id,
    get_organization_by_url_key,
)
from packages.database.schema import OrganizationSkill
from packages.shared.types.organization_skill import (
    OrganizationSkill as OrganizationSkillData,
    OrganizationSkillDetail,
    OrganizationSkillFileDetail,
    OrganizationSkillListItem,
    OrganizationSkillUpdateStatus,
)

_DEFAULT_MARKDOWN = "Use this skill when it is relevant to the current task."
_SKILL_FILE = "SKILL.md"
_SLUG_CLEANUP_RE = re.compile(r"[^a-z0-9_-]+")
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(?P<body>.*?)\n---\s*", re.DOTALL)
_BUNDLED_SKILLS: tuple[tuple[str, str], ...] = (
    ("para-memory-files", "para-memory-files"),
    ("control-plane", "control-plane"),
    ("create-agent", "create-agent"),
    ("create-plugin", "create-plugin"),
    ("skill-creator", "skill-creator"),
    ("skill-optimizer", "skill-optimizer"),
    ("conversation-to-skill", "conversation-to-skill"),
)
_BUNDLED_KEY_ORDER = {
    f"skills/{slug}": index for index, (slug, _) in enumerate(_BUNDLED_SKILLS)
}


class OrganizationSkillService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(self, org_id: str) -> list[OrganizationSkillListItem]:
        resolved_org_id = await self._resolve_org_id(org_id)
        if resolved_org_id is None:
            return []
        await self._ensure_skill_inventory_current(resolved_org_id)
        rows = await list_organization_skills(self._session, resolved_org_id)
        attached_counts = await self._attached_counts(resolved_org_id, rows)
        return sorted(
            [self._to_list_item(row, attached_counts.get(row.key, 0)) for row in rows],
            key=_organization_skill_sort_key,
        )

    async def _ensure_skill_inventory_current(self, org_id: str) -> None:
        await self._ensure_bundled_skills(org_id)

    async def _resolve_org_id(self, org_ref: str) -> str | None:
        by_id = await get_organization_by_id(self._session, org_ref)
        if by_id is not None:
            return by_id.id
        by_url_key = await get_organization_by_url_key(self._session, org_ref)
        return by_url_key.id if by_url_key is not None else None

    async def _ensure_bundled_skills(self, org_id: str) -> None:
        for canonical_slug, local_slug in _BUNDLED_SKILLS:
            skill_dir = _find_bundled_skill_dir(local_slug)
            if skill_dir is None:
                continue
            markdown = _read_skill_markdown(skill_dir)
            if markdown is None:
                continue
            key = f"skills/{canonical_slug}"
            legacy_key = _legacy_bundled_skill_key(canonical_slug)
            metadata = {"sourceKind": "built_in", "skillKey": key}
            fields = {
                "key": key,
                "slug": canonical_slug,
                "name": _skill_name_from_markdown(markdown, canonical_slug),
                "description": _skill_description_from_markdown(markdown),
                "markdown": markdown,
                "source_type": "local_path",
                "source_locator": str(skill_dir),
                "source_ref": None,
                "trust_level": "markdown_only",
                "compatibility": "compatible",
                "file_inventory": [{"path": _SKILL_FILE, "kind": "skill"}],
                "metadata_json": metadata,
            }
            existing = await get_organization_skill_by_key(self._session, org_id, key)
            if existing is None and legacy_key is not None:
                existing = await get_organization_skill_by_key(
                    self._session, org_id, legacy_key
                )
            if existing is None:
                await create_organization_skill(
                    self._session, {"id": str(uuid.uuid4()), "org_id": org_id, **fields}
                )
            elif _is_bundled_source_kind(_skill_source_kind(existing)):
                await update_organization_skill(
                    self._session, org_id, existing.id, fields
                )

    async def _list_rows(self, org_id: str) -> list[OrganizationSkill]:
        resolved_org_id = await self._resolve_org_id(org_id)
        if resolved_org_id is None:
            return []
        org_id = resolved_org_id
        await self._ensure_skill_inventory_current(org_id)
        return list(await list_organization_skills(self._session, org_id))

    async def _get_row(self, org_id: str, skill_id: str) -> OrganizationSkill | None:
        resolved_org_id = await self._resolve_org_id(org_id)
        if resolved_org_id is None:
            return None
        org_id = resolved_org_id
        await self._ensure_skill_inventory_current(org_id)
        return await get_organization_skill(self._session, org_id, skill_id)

    async def detail(
        self, org_id: str, skill_id: str
    ) -> OrganizationSkillDetail | None:
        row = await self._get_row(org_id, skill_id)
        if row is None:
            return None
        attached_counts = await self._attached_counts(org_id, [row])
        return {
            **self._to_list_item(row, attached_counts.get(row.key, 0)),
            "usedByAgents": [],
        }

    async def update_status(
        self, org_id: str, skill_id: str
    ) -> OrganizationSkillUpdateStatus | None:
        row = await self._get_row(org_id, skill_id)
        if row is None:
            return None
        return {
            "supported": False,
            "reason": "Local organization skills do not support upstream update checks.",
            "trackingRef": row.source_ref,
            "currentRef": row.source_ref,
            "latestRef": None,
            "hasUpdate": False,
        }

    async def create_local_skill(
        self,
        org_id: str,
        payload: Mapping[str, Any],
        *,
        actor_type: str,
        actor_id: str,
    ) -> OrganizationSkillData:
        resolved_org_id = await self._resolve_org_id(org_id)
        if resolved_org_id is None:
            raise ValueError("Organization not found")
        org_id = resolved_org_id
        slug = str(payload.get("slug") or _slugify(str(payload["name"])))
        existing = await get_organization_skill_by_key(self._session, org_id, slug)
        if existing is not None:
            raise OrganizationSkillConflictError("Organization skill already exists")
        markdown = str(payload.get("markdown") or _DEFAULT_MARKDOWN)
        skill_id = str(uuid.uuid4())
        skill_dir = _org_skill_dir(org_id, slug)
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_file = skill_dir / _SKILL_FILE
        skill_file.write_text(markdown, encoding="utf-8")
        row = await create_organization_skill(
            self._session,
            {
                "id": skill_id,
                "org_id": org_id,
                "key": slug,
                "slug": slug,
                "name": payload["name"],
                "description": payload.get("description"),
                "markdown": markdown,
                "source_type": "local_path",
                "source_locator": str(skill_dir),
                "source_ref": None,
                "trust_level": "markdown_only",
                "compatibility": "compatible",
                "file_inventory": [{"path": _SKILL_FILE, "kind": "skill"}],
                "metadata_json": None,
            },
        )
        await insert_activity_log(
            self._session,
            org_id=org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="organization.skill_created",
            entity_type="organization_skill",
            entity_id=row.id,
            details={"slug": row.slug, "name": row.name},
        )
        return self._to_skill(row)

    async def read_file(
        self, org_id: str, skill_id: str, relative_path: str
    ) -> OrganizationSkillFileDetail | None:
        row = await self._get_row(org_id, skill_id)
        if row is None:
            return None
        path = _normalize_skill_file_path(relative_path)
        file_path = _resolve_skill_file(row, path)
        try:
            content = file_path.read_text(encoding="utf-8")
        except OSError:
            return None
        return _file_detail(row.id, path, content)

    async def update_file(
        self,
        org_id: str,
        skill_id: str,
        relative_path: str,
        content: str,
        *,
        actor_type: str,
        actor_id: str,
    ) -> OrganizationSkillFileDetail | None:
        row = await self._get_row(org_id, skill_id)
        if row is None:
            return None
        if _is_bundled_skill(row):
            raise OrganizationSkillPathError(
                "Bundled organization skills are read-only"
            )
        path = _normalize_skill_file_path(relative_path)
        file_path = _resolve_skill_file(row, path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        update_fields: dict[str, Any] = {}
        if path == _SKILL_FILE:
            update_fields["markdown"] = content
        if update_fields:
            row = await update_organization_skill(
                self._session, org_id, skill_id, update_fields
            )
            if row is None:
                return None
        await insert_activity_log(
            self._session,
            org_id=org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="organization.skill_file_updated",
            entity_type="organization_skill",
            entity_id=skill_id,
            details={"path": path, "markdown": path == _SKILL_FILE},
        )
        return _file_detail(skill_id, path, content)

    async def delete_skill(
        self,
        org_id: str,
        skill_id: str,
        *,
        actor_type: str,
        actor_id: str,
    ) -> OrganizationSkillData | None:
        resolved_org_id = await self._resolve_org_id(org_id)
        if resolved_org_id is None:
            return None
        org_id = resolved_org_id
        existing = await get_organization_skill(self._session, org_id, skill_id)
        if existing is None:
            return None
        detail = self._to_skill(existing)
        row = await delete_organization_skill(self._session, org_id, skill_id)
        if row is None:
            return None
        await delete_enabled_skill_key(self._session, org_id, row.key)
        shutil.rmtree(_org_skill_dir(org_id, row.slug), ignore_errors=True)
        await insert_activity_log(
            self._session,
            org_id=org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="organization.skill_deleted",
            entity_type="organization_skill",
            entity_id=row.id,
            details={"slug": row.slug, "name": row.name},
        )
        return detail

    async def _attached_counts(
        self, org_id: str, rows: Sequence[OrganizationSkill]
    ) -> dict[str, int]:
        agents = await list_org_agents(self._session, org_id)
        if not agents:
            return {}
        enabled = await list_enabled_skill_keys_by_agent_ids(
            self._session, [agent.id for agent in agents]
        )
        counts = {row.key: 0 for row in rows}
        for keys in enabled.values():
            for key in keys:
                if key in counts:
                    counts[key] += 1
        return counts

    def _to_list_item(
        self, row: OrganizationSkill, attached_agent_count: int
    ) -> OrganizationSkillListItem:
        skill = self._to_skill(row)
        skill_dir = _skill_root(row)
        source_kind = _skill_source_kind(row)
        editable = not _is_bundled_source_kind(source_kind)
        return {
            **skill,
            "attachedAgentCount": attached_agent_count,
            "editable": editable,
            "editableReason": None if editable else "Built-in skill",
            "sourceLabel": _source_label(source_kind),
            "sourceBadge": _source_badge(source_kind),
            "sourcePath": str(skill_dir),
            "workspaceEditPath": str(skill_dir / _SKILL_FILE) if editable else None,
        }

    def _to_skill(self, row: OrganizationSkill) -> OrganizationSkillData:
        return {
            "id": row.id,
            "orgId": row.org_id,
            "key": row.key,
            "slug": row.slug,
            "name": row.name,
            "description": row.description,
            "markdown": row.markdown,
            "sourceType": row.source_type,
            "sourceLocator": row.source_locator,
            "sourceRef": row.source_ref,
            "trustLevel": row.trust_level,
            "compatibility": row.compatibility,
            "fileInventory": [
                {
                    "path": str(entry.get("path", "")),
                    "kind": str(entry.get("kind", "other")),
                }
                for entry in row.file_inventory
                if isinstance(entry, dict)
            ],
            "metadata": row.metadata_json,
            "createdAt": row.created_at.isoformat(),
            "updatedAt": row.updated_at.isoformat(),
        }


class OrganizationSkillConflictError(ValueError):
    pass


def organization_skills_root(org_id: str) -> Path:
    return (
        Path.cwd() / ".octopus" / "workspaces" / f"org_{org_id}" / "skills"
    ).resolve()


def _org_skill_dir(org_id: str, slug: str) -> Path:
    return organization_skills_root(org_id) / slug


def _find_bundled_skill_dir(local_slug: str) -> Path | None:
    for root in _bundled_skill_roots():
        skill_dir = root / local_slug
        if (skill_dir / _SKILL_FILE).is_file():
            return skill_dir.resolve()
    return None


def _bundled_skill_roots() -> list[Path]:
    repo_root = Path(__file__).resolve().parents[2]
    return [
        Path.cwd() / "server" / "skills" / "bundled",
        repo_root / "server" / "skills" / "bundled",
    ]


def _read_skill_markdown(skill_dir: Path) -> str | None:
    try:
        return (skill_dir / _SKILL_FILE).read_text(encoding="utf-8")
    except OSError:
        return None


def _frontmatter_value(markdown: str, key: str) -> str | None:
    match = _FRONTMATTER_RE.match(markdown)
    if match is None:
        return None
    for line in match.group("body").splitlines():
        name, separator, value = line.partition(":")
        if separator and name.strip() == key:
            return value.strip().strip("\"'")
    return None


def _skill_name_from_markdown(markdown: str, fallback_slug: str) -> str:
    return _frontmatter_value(markdown, "name") or fallback_slug


def _skill_description_from_markdown(markdown: str) -> str | None:
    return _frontmatter_value(markdown, "description")


def _slugify(value: str) -> str:
    slug = _SLUG_CLEANUP_RE.sub("-", value.strip().lower()).strip("-_")
    return slug or "skill"


def _normalize_skill_file_path(value: str) -> str:
    path = value.strip() or _SKILL_FILE
    normalized = Path(path)
    if normalized.is_absolute() or ".." in normalized.parts:
        raise OrganizationSkillPathError("Invalid organization skill file path")
    return normalized.as_posix()


def _resolve_skill_file(row: OrganizationSkill, relative_path: str) -> Path:
    root = _skill_root(row)
    target = (root / relative_path).resolve()
    if not _is_relative_to(target, root.resolve()):
        raise OrganizationSkillPathError("Invalid organization skill file path")
    return target


def _skill_root(row: OrganizationSkill) -> Path:
    if row.source_locator:
        path = Path(row.source_locator)
        if path.exists():
            return path.resolve()
    return _org_skill_dir(row.org_id, row.slug)


def _skill_source_kind(row: OrganizationSkill) -> str | None:
    metadata = row.metadata_json or {}
    value = metadata.get("sourceKind")
    return value if isinstance(value, str) else None


def _is_bundled_skill(row: OrganizationSkill) -> bool:
    return _is_bundled_source_kind(_skill_source_kind(row))


def _is_bundled_source_kind(source_kind: str | None) -> bool:
    return source_kind in {"built_in", "octopus_bundled", "rudder_bundled"}


def _source_label(source_kind: str | None) -> str:
    if _is_bundled_source_kind(source_kind):
        return "Built-in skill"
    if source_kind == "community_preset":
        return "Community preset"
    return "Local organization skill"


def _source_badge(source_kind: str | None) -> str:
    if _is_bundled_source_kind(source_kind):
        return "built-in"
    if source_kind == "community_preset":
        return "community"
    return "local"


def _legacy_bundled_skill_key(slug: str) -> str | None:
    legacy_slugs = {
        "control-plane": "rudder",
        "create-agent": "rudder-create-agent",
        "create-plugin": "rudder-create-plugin",
    }
    return f"rudder/{legacy_slugs.get(slug, slug)}"


def _organization_skill_sort_key(skill: OrganizationSkillListItem) -> tuple[int, str]:
    bundled_order = _BUNDLED_KEY_ORDER.get(skill["key"])
    if bundled_order is not None:
        return (bundled_order, "")
    return (len(_BUNDLED_KEY_ORDER), skill["name"].lower())


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


class OrganizationSkillPathError(ValueError):
    pass


def _file_detail(
    skill_id: str, relative_path: str, content: str
) -> OrganizationSkillFileDetail:
    return {
        "skillId": skill_id,
        "path": relative_path,
        "kind": "skill" if relative_path == _SKILL_FILE else "other",
        "content": content,
        "language": "markdown" if relative_path.endswith(".md") else None,
        "markdown": relative_path.endswith(".md"),
        "editable": True,
    }
