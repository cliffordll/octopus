"""Import a companies.sh / Rudder directory-style organization package.

Supports both layouts in one parser:
- Paperclip-native: COMPANY.md + .paperclip.yaml + agents/<slug>/AGENTS.md
- Rudder-exported:  ORGANIZATION.md + .rudder.yaml + agents/<slug>/{AGENTS,SOUL,MEMORY,...}.md

`teams/` is intentionally ignored (octopus has no team model). The importer
reuses existing services: OrgService, AgentService, OrganizationSkillService,
AgentInstructionsService, ProjectService.
"""

from __future__ import annotations

import re
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Literal

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from .agent_instructions import AgentInstructionsService
from .agents import AgentService
from .organization_skills import OrganizationSkillService
from .orgs import OrgService
from .projects import ProjectService

_ORG_FILES = ("COMPANY.md", "ORGANIZATION.md")
_EXTENSION_FILES = (".rudder.yaml", ".rudder.yml", ".paperclip.yaml", ".paperclip.yml")
_AGENT_ENTRY = "AGENTS.md"
_BUNDLE_FILES = (
    "SOUL.md",
    "MEMORY.md",
    "HEARTBEAT.md",
    "TOOLS.md",
    "SOUL.zh-CN.md",
    "MEMORY.zh-CN.md",
    "HEARTBEAT.zh-CN.md",
    "TOOLS.zh-CN.md",
)
_FRONTMATTER_RE = re.compile(r"\A﻿?---\s*\n(?P<body>.*?)\n---\s*\n?", re.DOTALL)
_VALID_ROLES = {
    "ceo",
    "cto",
    "cmo",
    "cfo",
    "engineer",
    "designer",
    "pm",
    "qa",
    "devops",
    "researcher",
    "general",
}
# Ordered keyword -> role inference for Paperclip packages that omit explicit roles.
_ROLE_KEYWORDS: list[tuple[str, str]] = [
    ("chief executive", "ceo"),
    ("ceo", "ceo"),
    ("chief technology", "cto"),
    ("cto", "cto"),
    ("cfo", "cfo"),
    ("cmo", "cmo"),
    ("designer", "designer"),
    ("design", "designer"),
    ("quality", "qa"),
    ("evaluat", "qa"),
    ("review", "qa"),
    (" qa", "qa"),
    ("test", "qa"),
    ("architect", "pm"),
    ("product manager", "pm"),
    ("product", "pm"),
    ("devops", "devops"),
    ("integration", "devops"),
    ("infra", "devops"),
    ("ci/cd", "devops"),
    ("research", "researcher"),
    ("analyst", "researcher"),
    ("engineer", "engineer"),
    ("editor", "engineer"),
    ("writer", "engineer"),
]

CollisionStrategy = Literal["rename", "skip", "replace"]
ImportTarget = Literal["new", "existing"]
_PROVIDER_MODEL_RUNTIMES = {"opencode_local", "openclaw_local"}


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        return {}, text
    try:
        data = yaml.safe_load(match.group("body")) or {}
    except yaml.YAMLError:
        data = {}
    return (data if isinstance(data, dict) else {}), text[match.end() :]


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _as_str(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _infer_role(*candidates: str | None) -> str:
    blob = " ".join(c for c in candidates if c).lower()
    for keyword, role in _ROLE_KEYWORDS:
        if keyword in blob:
            return role
    return "general"


def parse_company_package(root: Path) -> dict[str, Any]:
    """Parse a directory-style organization package into an import manifest."""
    root = Path(root)
    warnings: list[str] = []

    org_file = next(
        (root / name for name in _ORG_FILES if (root / name).is_file()), None
    )
    if org_file is None:
        raise ValueError(
            "Organization package must contain COMPANY.md or ORGANIZATION.md at its root"
        )
    org_fm, _ = _parse_frontmatter(_read_text(org_file) or "")
    organization = {
        "name": _as_str(org_fm.get("name")) or root.name,
        "slug": _as_str(org_fm.get("slug")),
        "description": _as_str(org_fm.get("description")),
    }

    ext: dict[str, Any] = {}
    ext_file = next((root / n for n in _EXTENSION_FILES if (root / n).is_file()), None)
    if ext_file is not None:
        try:
            loaded = yaml.safe_load(_read_text(ext_file) or "") or {}
            ext = loaded if isinstance(loaded, dict) else {}
        except yaml.YAMLError:
            warnings.append(
                f"Failed to parse {ext_file.name}; ignoring extension config."
            )
    ext_agents = ext.get("agents") if isinstance(ext.get("agents"), dict) else {}

    agents: list[dict[str, Any]] = []
    agents_dir = root / "agents"
    if agents_dir.is_dir():
        for agent_dir in sorted(p for p in agents_dir.iterdir() if p.is_dir()):
            slug = agent_dir.name
            md_text = _read_text(agent_dir / _AGENT_ENTRY)
            if md_text is None:
                warnings.append(f"Agent '{slug}' has no {_AGENT_ENTRY}; skipped.")
                continue
            fm, body = _parse_frontmatter(md_text)
            ext_entry = (
                ext_agents.get(slug) if isinstance(ext_agents.get(slug), dict) else {}
            )
            ext_adapter = (
                ext_entry.get("adapter")
                if isinstance(ext_entry.get("adapter"), dict)
                else {}
            )
            ext_cfg = (
                ext_adapter.get("config")
                if isinstance(ext_adapter.get("config"), dict)
                else {}
            )

            bundle: dict[str, str] = {}
            for fname in _BUNDLE_FILES:
                content = _read_text(agent_dir / fname)
                if content is not None:
                    bundle[fname] = content
            # octopus instructions entry is SOUL.md; fall back to AGENTS.md body.
            if "SOUL.md" not in bundle:
                bundle["SOUL.md"] = body or md_text

            skills_raw = fm.get("skills")
            skills = (
                [s for s in skills_raw if isinstance(s, str)]
                if isinstance(skills_raw, list)
                else []
            )
            role = _as_str(ext_entry.get("role")) or _infer_role(
                _as_str(fm.get("title")), _as_str(fm.get("name")), slug
            )
            if role not in _VALID_ROLES:
                warnings.append(
                    f"Agent '{slug}' inferred invalid role '{role}'; using general."
                )
                role = "general"

            agents.append(
                {
                    "slug": slug,
                    "name": _as_str(fm.get("name")) or _as_str(fm.get("title")) or slug,
                    "title": _as_str(fm.get("title")),
                    "role": role,
                    "reportsToSlug": _as_str(fm.get("reportsTo"))
                    or _as_str(ext_entry.get("reportsTo")),
                    "skills": skills,
                    "runtimeType": _as_str(ext_adapter.get("type")),
                    "model": _as_str(ext_cfg.get("model")),
                    "bundle": bundle,
                }
            )

    skills_dir = root / "skills"
    has_skills = (
        skills_dir.is_dir() and next(skills_dir.rglob("SKILL.md"), None) is not None
    )

    projects: list[dict[str, Any]] = []
    projects_dir = root / "projects"
    if projects_dir.is_dir():
        for project_md in sorted(projects_dir.rglob("PROJECT.md")):
            fm, body = _parse_frontmatter(_read_text(project_md) or "")
            projects.append(
                {
                    "slug": _as_str(fm.get("slug")) or project_md.parent.name,
                    "name": _as_str(fm.get("name")) or project_md.parent.name,
                    "description": _as_str(fm.get("description"))
                    or (body.strip() or None),
                    "ownerSlug": _as_str(fm.get("owner")),
                }
            )

    if not agents:
        warnings.append("Package contains no importable agents.")

    return {
        "organization": organization,
        "agents": agents,
        "skillsDir": str(skills_dir) if has_skills else None,
        "projects": projects,
        "warnings": warnings,
    }


class OrganizationImportService:
    """Import a companies.sh / Rudder directory-style package into octopus."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._orgs = OrgService(session)
        self._agents = AgentService(session)
        self._skills = OrganizationSkillService(session)
        self._instructions = AgentInstructionsService(session)
        self._projects = ProjectService(session)

    async def import_package(
        self,
        root_path: str,
        *,
        target: ImportTarget = "new",
        org_id: str | None = None,
        runtime_type: str = "opencode_local",
        model: str | None = None,
        collision: CollisionStrategy = "rename",
        dry_run: bool = False,
        actor_type: str = "board",
        actor_id: str = "board",
    ) -> dict[str, Any]:
        manifest = parse_company_package(Path(root_path))
        warnings = list(manifest["warnings"])

        # Validate models before any writes so we fail fast and atomically-ish.
        for agent in manifest["agents"]:
            eff_runtime = agent["runtimeType"] or runtime_type
            eff_model = model or agent["model"]
            if eff_runtime in _PROVIDER_MODEL_RUNTIMES and (
                not eff_model or "/" not in eff_model
            ):
                raise ValueError(
                    f"Agent '{agent['slug']}' on runtime '{eff_runtime}' requires a "
                    "provider/model formatted model; pass model or set it in the package."
                )

        plan = {
            "organization": manifest["organization"],
            "target": target,
            "agents": [
                {
                    "slug": a["slug"],
                    "name": a["name"],
                    "role": a["role"],
                    "reportsTo": a["reportsToSlug"],
                    "skills": a["skills"],
                }
                for a in manifest["agents"]
            ],
            "skills": bool(manifest["skillsDir"]),
            "projects": [p["slug"] for p in manifest["projects"]],
            "warnings": warnings,
        }
        if dry_run:
            return {"dryRun": True, "plan": plan}

        actor = {"actor_type": actor_type, "actor_id": actor_id}

        # 1) organization
        if target == "existing":
            if not org_id:
                raise ValueError("target=existing requires org_id")
            if await self._orgs.get(org_id) is None:
                raise ValueError("Target organization not found")
            resolved_org_id = org_id
        else:
            created_org = await self._orgs.create(
                {
                    "name": manifest["organization"]["name"],
                    "description": manifest["organization"]["description"],
                },
                **actor,
            )
            resolved_org_id = created_org["id"]

        # 2) skills (recursive scan-local import); map slug -> stored key
        skill_slug_to_key: dict[str, str] = {}
        skills_imported = 0
        if manifest["skillsDir"]:
            result = await self._skills.scan_local_skills(
                resolved_org_id,
                {
                    "rootPath": manifest["skillsDir"],
                    "importDiscovered": True,
                    "overwrite": collision == "replace",
                },
                **actor,
            )
            for skill in result.get("imported", []):
                skills_imported += 1
                slug = skill.get("slug")
                if slug:
                    skill_slug_to_key[slug] = skill.get("key") or slug

        # 3) agents — create, then force-inject the package's real SOUL bundle
        slug_to_id: dict[str, str] = {}
        created_agents: list[dict[str, Any]] = []
        for agent in manifest["agents"]:
            eff_runtime = agent["runtimeType"] or runtime_type
            eff_model = model or agent["model"]
            desired: list[str] = []
            for skill_ref in agent["skills"]:
                # AGENTS.md may reference skills as a bare slug ("pragmatic-code-review")
                # or a fully-qualified ref ("org:author/lib/chapter-writing"); imported
                # skills are keyed by the last path segment, so match on that too.
                normalized = skill_ref.rsplit("/", 1)[-1].rsplit(":", 1)[-1]
                key = skill_slug_to_key.get(skill_ref) or skill_slug_to_key.get(
                    normalized
                )
                if key:
                    desired.append(key)
                else:
                    warnings.append(
                        f"Agent '{agent['slug']}' references skill '{skill_ref}' "
                        "not present in imported skills; not enabled."
                    )
            payload: dict[str, Any] = {
                "role": agent["role"],
                "name": agent["name"],
                "title": agent["title"],
                "agentRuntimeType": eff_runtime,
                "agentRuntimeConfig": {"model": eff_model} if eff_model else {},
                "runtimeConfig": {},
                "budgetMonthlyCents": 0,
                "desiredSkills": desired,
            }
            created = await self._agents.create_agent(resolved_org_id, payload, **actor)
            agent_id = created["id"]
            slug_to_id[agent["slug"]] = agent_id
            await self._instructions.materialize_external_bundle(
                agent_id, agent["bundle"], entry_file="SOUL.md", **actor
            )
            created_agents.append(
                {
                    "slug": agent["slug"],
                    "id": agent_id,
                    "name": created["name"],
                    "role": agent["role"],
                }
            )

        # 4) reporting lines (ids now known)
        for agent in manifest["agents"]:
            mgr_slug = agent["reportsToSlug"]
            agent_id = slug_to_id.get(agent["slug"])
            if not mgr_slug or not agent_id:
                continue
            mgr_id = slug_to_id.get(mgr_slug)
            if not mgr_id:
                warnings.append(
                    f"Agent '{agent['slug']}' reportsTo '{mgr_slug}' which was not imported."
                )
                continue
            if mgr_id == agent_id:
                continue
            try:
                await self._agents.update_agent(
                    agent_id, {"reportsTo": mgr_id}, **actor
                )
            except Exception as exc:  # noqa: BLE001 - record and continue
                warnings.append(f"Failed to set reportsTo for '{agent['slug']}': {exc}")

        # 5) projects (optional)
        created_projects: list[dict[str, Any]] = []
        for project in manifest["projects"]:
            try:
                payload = {
                    "name": project["name"],
                    "description": project["description"],
                }
                lead_id = (
                    slug_to_id.get(project["ownerSlug"])
                    if project["ownerSlug"]
                    else None
                )
                if lead_id:
                    payload["leadAgentId"] = lead_id
                created = await self._projects.create_project(
                    resolved_org_id, payload, **actor
                )
                created_projects.append(
                    {
                        "slug": project["slug"],
                        "id": created["id"],
                        "name": created["name"],
                    }
                )
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"Failed to create project '{project['slug']}': {exc}")

        return {
            "dryRun": False,
            "organization": {
                "id": resolved_org_id,
                "name": manifest["organization"]["name"],
                "action": "created" if target == "new" else "updated",
            },
            "agents": created_agents,
            "skillsImported": skills_imported,
            "projects": created_projects,
            "warnings": warnings,
        }

    async def import_zip(self, zip_path: str, **kwargs: Any) -> dict[str, Any]:
        """Extract an uploaded zip package to a temp dir, then import."""
        with tempfile.TemporaryDirectory(prefix="org-import-") as tmp:
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(tmp)
            return await self.import_package(
                str(_resolve_package_root(Path(tmp))), **kwargs
            )


def _resolve_package_root(extracted: Path) -> Path:
    """Locate the package root in an extracted zip (handles a single wrapping dir)."""
    candidates = [extracted, *(p for p in extracted.iterdir() if p.is_dir())]
    for candidate in candidates:
        if any((candidate / name).is_file() for name in _ORG_FILES):
            return candidate
    return extracted
