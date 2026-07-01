from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
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
    OrganizationSkillFileInventoryEntry,
    OrganizationSkillImportPayload,
    OrganizationSkillListItem,
    OrganizationSkillScanCandidate,
    OrganizationSkillScanLocalPayload,
    OrganizationSkillScanLocalResult,
    OrganizationSkillUpdateStatus,
)
from .workspace_paths import ensure_organization_workspace_root

_DEFAULT_MARKDOWN = "Use this skill when it is relevant to the current task."
_SKILL_FILE = "SKILL.md"
_INVENTORY_EXCLUDED_DIRS = {"__pycache__", ".git", ".hg", ".svn", ".mypy_cache"}
_INVENTORY_EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
_SLUG_CLEANUP_RE = re.compile(r"[^a-z0-9_-]+")
_FRONTMATTER_RE = re.compile(r"\A\ufeff?---\s*\n(?P<body>.*?)\n---\s*", re.DOTALL)
_BUNDLED_SKILLS: tuple[tuple[str, str], ...] = (
    ("para-memory-files", "para-memory-files"),
    ("control-plane", "control-plane"),
    ("create-agent", "create-agent"),
    ("create-plugin", "create-plugin"),
    ("skill-creator", "skill-creator"),
    ("skill-optimizer", "skill-optimizer"),
    ("conversation-to-skill", "conversation-to-skill"),
)
BUNDLED_SKILL_KEYS = tuple(f"skills/{slug}" for slug, _ in _BUNDLED_SKILLS)
_COMMUNITY_PRESET_SKILLS: tuple[str, ...] = (
    "deep-research",
    "software-product-advisor",
)
_BUNDLED_KEY_ORDER = {
    skill_key: index for index, skill_key in enumerate(BUNDLED_SKILL_KEYS)
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
        await self._ensure_community_preset_skills(org_id)

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
                "file_inventory": _scan_skill_inventory(skill_dir),
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

    async def _ensure_community_preset_skills(self, org_id: str) -> None:
        for slug in _COMMUNITY_PRESET_SKILLS:
            skill_dir = _find_community_preset_skill_dir(slug)
            if skill_dir is None:
                continue
            markdown = _read_skill_markdown(skill_dir)
            if markdown is None:
                continue
            key = f"organization/{org_id}/{slug}"
            metadata = {"sourceKind": "community_preset", "skillKey": key}
            fields = {
                "key": key,
                "slug": slug,
                "name": _skill_name_from_markdown(markdown, slug),
                "description": _skill_description_from_markdown(markdown),
                "markdown": markdown,
                "source_type": "local_path",
                "source_locator": str(skill_dir),
                "source_ref": None,
                "trust_level": "markdown_only",
                "compatibility": "compatible",
                "file_inventory": _scan_skill_inventory(skill_dir),
                "metadata_json": metadata,
            }
            existing = await get_organization_skill_by_key(self._session, org_id, key)
            if existing is None:
                await create_organization_skill(
                    self._session, {"id": str(uuid.uuid4()), "org_id": org_id, **fields}
                )
            elif _skill_source_kind(existing) == "community_preset":
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
        if _skill_source_kind(row) == "local_import":
            source_dir = _local_import_source_dir(row)
            if source_dir is None:
                return {
                    "supported": False,
                    "reason": "Local import source directory is not available.",
                    "trackingRef": row.source_ref,
                    "currentRef": _skill_tree_hash(_skill_root(row)),
                    "latestRef": None,
                    "hasUpdate": False,
                }
            latest_ref = _skill_tree_hash(source_dir)
            return {
                "supported": True,
                "reason": None,
                "trackingRef": row.source_ref,
                "currentRef": _skill_tree_hash(_skill_root(row)),
                "latestRef": latest_ref,
                "hasUpdate": latest_ref != row.source_ref,
            }
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
                "file_inventory": _scan_skill_inventory(skill_dir),
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

    async def import_local_skill(
        self,
        org_id: str,
        payload: OrganizationSkillImportPayload,
        *,
        actor_type: str,
        actor_id: str,
    ) -> OrganizationSkillData:
        resolved_org_id = await self._resolve_org_id(org_id)
        if resolved_org_id is None:
            raise ValueError("Organization not found")
        org_id = resolved_org_id
        source_dir = _resolve_local_skill_source(payload["sourcePath"])
        markdown = _read_skill_markdown(source_dir)
        if markdown is None:
            raise ValueError("Local skill source must contain SKILL.md")
        slug = str(payload.get("slug") or _slugify(source_dir.name))
        existing = await get_organization_skill_by_key(self._session, org_id, slug)
        overwrite = bool(payload.get("overwrite", False))
        if existing is not None and not overwrite:
            raise OrganizationSkillConflictError("Organization skill already exists")
        name = payload.get("name") or _skill_name_from_markdown(markdown, slug)
        description = payload.get("description")
        if description is None:
            description = _skill_description_from_markdown(markdown)
        installed_dir = _org_skill_dir(org_id, slug)
        _replace_skill_tree(source_dir, installed_dir)
        source_ref = _skill_tree_hash(source_dir)
        fields = {
            "key": slug,
            "slug": slug,
            "name": name,
            "description": description,
            "markdown": markdown,
            "source_type": "local_path",
            "source_locator": str(source_dir),
            "source_ref": source_ref,
            "trust_level": "markdown_only",
            "compatibility": "compatible",
            "file_inventory": _scan_skill_inventory(installed_dir),
            "metadata_json": {"sourceKind": "local_import"},
        }
        if existing is None:
            row = await create_organization_skill(
                self._session,
                {"id": str(uuid.uuid4()), "org_id": org_id, **fields},
            )
        else:
            row = await update_organization_skill(
                self._session, org_id, existing.id, fields
            )
            assert row is not None
        await insert_activity_log(
            self._session,
            org_id=org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="organization.skill_imported",
            entity_type="organization_skill",
            entity_id=row.id,
            details={"slug": row.slug, "sourcePath": str(source_dir)},
        )
        return self._to_skill(row)

    async def scan_local_skills(
        self,
        org_id: str,
        payload: OrganizationSkillScanLocalPayload,
        *,
        actor_type: str,
        actor_id: str,
    ) -> OrganizationSkillScanLocalResult:
        resolved_org_id = await self._resolve_org_id(org_id)
        if resolved_org_id is None:
            raise ValueError("Organization not found")
        org_id = resolved_org_id
        root = Path(payload["rootPath"]).expanduser().resolve()
        if not root.is_dir():
            raise ValueError("Local skill scan root must be a directory")
        import_discovered = bool(payload.get("importDiscovered", False))
        overwrite = bool(payload.get("overwrite", False))
        candidates: list[OrganizationSkillScanCandidate] = []
        imported: list[OrganizationSkillData] = []
        for source_dir in _scan_local_skill_dirs(root):
            markdown = _read_skill_markdown(source_dir)
            if markdown is None:
                continue
            slug = _slugify(source_dir.name)
            existing = await get_organization_skill_by_key(self._session, org_id, slug)
            candidate: OrganizationSkillScanCandidate = {
                "sourcePath": str(source_dir),
                "slug": slug,
                "name": _skill_name_from_markdown(markdown, slug),
                "description": _skill_description_from_markdown(markdown),
                "sourceRef": _skill_tree_hash(source_dir),
                "alreadyImported": existing is not None,
                "skillId": existing.id if existing is not None else None,
            }
            candidates.append(candidate)
            if import_discovered and (existing is None or overwrite):
                imported.append(
                    await self.import_local_skill(
                        org_id,
                        {
                            "sourcePath": str(source_dir),
                            "overwrite": overwrite,
                        },
                        actor_type=actor_type,
                        actor_id=actor_id,
                    )
                )
        return {"candidates": candidates, "imported": imported}

    async def install_update(
        self,
        org_id: str,
        skill_id: str,
        *,
        actor_type: str,
        actor_id: str,
    ) -> OrganizationSkillData | None:
        row = await self._get_row(org_id, skill_id)
        if row is None:
            return None
        if _skill_source_kind(row) != "local_import":
            raise ValueError("Only local imported organization skills support updates")
        source_dir = _local_import_source_dir(row)
        if source_dir is None:
            raise ValueError("Local import source directory is not available")
        markdown = _read_skill_markdown(source_dir)
        if markdown is None:
            raise ValueError("Local skill source must contain SKILL.md")
        installed_dir = _org_skill_dir(row.org_id, row.slug)
        _replace_skill_tree(source_dir, installed_dir)
        source_ref = _skill_tree_hash(source_dir)
        updated = await update_organization_skill(
            self._session,
            row.org_id,
            row.id,
            {
                "name": _skill_name_from_markdown(markdown, row.slug),
                "description": _skill_description_from_markdown(markdown),
                "markdown": markdown,
                "source_ref": source_ref,
                "file_inventory": _scan_skill_inventory(installed_dir),
            },
        )
        assert updated is not None
        await insert_activity_log(
            self._session,
            org_id=row.org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="organization.skill_update_installed",
            entity_type="organization_skill",
            entity_id=row.id,
            details={"slug": row.slug, "sourcePath": str(source_dir)},
        )
        return self._to_skill(updated)

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
        if _is_read_only_source_kind(_skill_source_kind(row)):
            raise OrganizationSkillPathError(
                "Shipped organization skills are read-only"
            )
        path = _normalize_skill_file_path(relative_path)
        file_path = _resolve_skill_file(row, path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        update_fields: dict[str, Any] = {
            "file_inventory": _scan_skill_inventory(_skill_root(row))
        }
        if path == _SKILL_FILE:
            update_fields["markdown"] = content
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
        editable = not _is_read_only_source_kind(source_kind)
        return {
            **skill,
            "attachedAgentCount": attached_agent_count,
            "editable": editable,
            "editableReason": None if editable else _read_only_reason(source_kind),
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
            "fileInventory": _inventory_for_row(row),
            "metadata": row.metadata_json,
            "createdAt": row.created_at.isoformat(),
            "updatedAt": row.updated_at.isoformat(),
        }


class OrganizationSkillConflictError(ValueError):
    pass


def organization_skills_root(org_id: str) -> Path:
    root = (ensure_organization_workspace_root(org_id) / "skills").resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _org_skill_dir(org_id: str, slug: str) -> Path:
    return organization_skills_root(org_id) / slug


def _find_bundled_skill_dir(local_slug: str) -> Path | None:
    for root in _bundled_skill_roots():
        skill_dir = root / local_slug
        if (skill_dir / _SKILL_FILE).is_file():
            return skill_dir.resolve()
    return None


def _find_community_preset_skill_dir(slug: str) -> Path | None:
    for root in _community_preset_skill_roots():
        skill_dir = root / slug
        if (skill_dir / _SKILL_FILE).is_file():
            return skill_dir.resolve()
    return None


def _bundled_skill_roots() -> list[Path]:
    repo_root = Path(__file__).resolve().parents[2]
    return [
        Path.cwd() / "server" / "skills" / "bundled",
        repo_root / "server" / "skills" / "bundled",
    ]


def _community_preset_skill_roots() -> list[Path]:
    repo_root = Path(__file__).resolve().parents[2]
    return [
        Path.cwd() / "server" / "skills" / "community",
        repo_root / "server" / "skills" / "community",
    ]


def _read_skill_markdown(skill_dir: Path) -> str | None:
    try:
        return (skill_dir / _SKILL_FILE).read_text(encoding="utf-8")
    except OSError:
        return None


def _inventory_for_row(
    row: OrganizationSkill,
) -> list[OrganizationSkillFileInventoryEntry]:
    scanned = _scan_skill_inventory(_skill_root(row))
    if scanned:
        return scanned
    return [
        {"path": str(entry.get("path", "")), "kind": str(entry.get("kind", "other"))}
        for entry in row.file_inventory
        if isinstance(entry, dict)
    ]


def _scan_skill_inventory(skill_dir: Path) -> list[OrganizationSkillFileInventoryEntry]:
    if not skill_dir.exists() or not skill_dir.is_dir():
        return []
    entries: list[OrganizationSkillFileInventoryEntry] = []
    for path in skill_dir.rglob("*"):
        if not path.is_file():
            continue
        try:
            relative = path.relative_to(skill_dir)
        except ValueError:
            continue
        if _skip_inventory_path(relative):
            continue
        relative_path = relative.as_posix()
        entries.append({"path": relative_path, "kind": _inventory_kind(relative_path)})
    return sorted(entries, key=_inventory_sort_key)


def _skip_inventory_path(relative: Path) -> bool:
    return (
        any(
            part.startswith(".") or part in _INVENTORY_EXCLUDED_DIRS
            for part in relative.parts
        )
        or relative.suffix.lower() in _INVENTORY_EXCLUDED_SUFFIXES
    )


def _inventory_kind(relative_path: str) -> str:
    if relative_path == _SKILL_FILE:
        return "skill"
    if relative_path == "README.md":
        return "readme"
    first_segment = relative_path.split("/", 1)[0]
    if first_segment in {"reference", "references"}:
        return "reference"
    if first_segment == "scripts":
        return "script"
    if first_segment == "templates":
        return "template"
    if relative_path.endswith(".md"):
        return "markdown"
    return "other"


def _inventory_sort_key(entry: OrganizationSkillFileInventoryEntry) -> tuple[int, str]:
    path = entry["path"]
    order = {
        _SKILL_FILE: 0,
        "README.md": 1,
        "reference": 2,
        "references": 2,
        "scripts": 3,
        "templates": 4,
    }
    first_segment = path.split("/", 1)[0]
    return (order.get(path, order.get(first_segment, 10)), path)


def _frontmatter_value(markdown: str, key: str) -> str | None:
    match = _FRONTMATTER_RE.match(markdown)
    if match is None:
        return None
    lines = match.group("body").splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        name, separator, value = line.strip().partition(":")
        if separator and name.strip() == key:
            text = value.strip().strip("\"'")
            if text in {">", "|"}:
                folded: list[str] = []
                index += 1
                while index < len(lines):
                    nested = lines[index]
                    if nested and not nested[:1].isspace():
                        break
                    stripped = nested.strip()
                    if stripped:
                        folded.append(stripped)
                    index += 1
                return (" " if text == ">" else "\n").join(folded) or None
            return text or None
        index += 1
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
    if _skill_source_kind(row) == "local_import":
        return _org_skill_dir(row.org_id, row.slug)
    if row.source_locator:
        path = Path(row.source_locator)
        if path.exists():
            return path.resolve()
    return _org_skill_dir(row.org_id, row.slug)


def _local_import_source_dir(row: OrganizationSkill) -> Path | None:
    if not row.source_locator:
        return None
    source_dir = Path(row.source_locator).expanduser().resolve()
    if not source_dir.is_dir() or not source_dir.joinpath(_SKILL_FILE).is_file():
        return None
    return source_dir


def _resolve_local_skill_source(source_path: str) -> Path:
    source_dir = Path(source_path).expanduser().resolve()
    if not source_dir.is_dir():
        raise ValueError("Local skill source must be a directory")
    if not source_dir.joinpath(_SKILL_FILE).is_file():
        raise ValueError("Local skill source must contain SKILL.md")
    return source_dir


def _scan_local_skill_dirs(root: Path) -> list[Path]:
    candidates: dict[str, Path] = {}
    if root.joinpath(_SKILL_FILE).is_file():
        candidates[str(root.resolve())] = root.resolve()
    for skill_file in root.rglob(_SKILL_FILE):
        source_dir = skill_file.parent.resolve()
        if _skip_inventory_path(source_dir.relative_to(root.resolve())):
            continue
        candidates[str(source_dir)] = source_dir
    return sorted(candidates.values(), key=lambda path: path.as_posix())


def _replace_skill_tree(source_dir: Path, target_dir: Path) -> None:
    root = target_dir.parent.resolve()
    target = target_dir.resolve()
    if not _is_relative_to(target, root):
        raise OrganizationSkillPathError("Invalid organization skill target path")
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    for source_path in source_dir.rglob("*"):
        if not source_path.is_file():
            continue
        relative = source_path.relative_to(source_dir)
        if _skip_inventory_path(relative):
            continue
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination)


def _skill_tree_hash(skill_dir: Path) -> str:
    digest = hashlib.sha256()
    for entry in _scan_skill_inventory(skill_dir):
        path = skill_dir / entry["path"]
        digest.update(entry["path"].encode("utf-8"))
        digest.update(b"\0")
        try:
            digest.update(path.read_bytes())
        except OSError:
            continue
        digest.update(b"\0")
    return digest.hexdigest()


def _skill_source_kind(row: OrganizationSkill) -> str | None:
    metadata = row.metadata_json or {}
    value = metadata.get("sourceKind")
    return value if isinstance(value, str) else None


def _is_bundled_skill(row: OrganizationSkill) -> bool:
    return _is_bundled_source_kind(_skill_source_kind(row))


def _is_bundled_source_kind(source_kind: str | None) -> bool:
    return source_kind in {"built_in", "octopus_bundled", "octopus_bundled"}


def _is_read_only_source_kind(source_kind: str | None) -> bool:
    return _is_bundled_source_kind(source_kind) or source_kind == "community_preset"


def _read_only_reason(source_kind: str | None) -> str:
    if source_kind == "community_preset":
        return "Community preset skill"
    return "Built-in skill"


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
        "control-plane": "octopus",
        "create-agent": "octopus-create-agent",
        "create-plugin": "octopus-create-plugin",
    }
    return f"octopus/{legacy_slugs.get(slug, slug)}"


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
        "kind": _inventory_kind(relative_path),
        "content": content,
        "language": "markdown" if relative_path.endswith(".md") else None,
        "markdown": relative_path.endswith(".md"),
        "editable": True,
    }
