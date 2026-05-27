from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
import re
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.activity_log import insert_activity_log
from packages.database.queries.goals import list_project_goals, replace_project_goals
from packages.database.queries.projects import (
    create_project,
    delete_project,
    get_project_by_id,
    list_org_projects,
    update_project,
)
from packages.database.queries.resources import (
    create_organization_resource,
    create_project_resource_attachment,
    delete_project_resource_attachment,
    delete_project_resource_attachments,
    get_organization_resource_by_id,
    get_project_resource_attachment,
    get_project_resource_attachment_by_resource,
    list_project_resource_attachments,
    update_project_resource_attachment,
)
from packages.database.schema import (
    OrganizationResource,
    Project,
    ProjectResourceAttachment,
)
from packages.shared.constants.project import (
    DEFAULT_PROJECT_STATUS,
    OrganizationResourceKind,
    PROJECT_COLORS,
    PauseReason,
    ProjectResourceAttachmentRole,
    ProjectStatus,
)
from packages.shared.types.project import (
    CreateProjectPayload,
    CreateProjectInlineResourceInput,
    OrganizationResource as OrganizationResourceData,
    ProjectDetail,
    ProjectGoalRef,
    ProjectResourceAttachment as ProjectResourceAttachmentData,
    ProjectResourceAttachmentInput,
    UpdateProjectPayload,
    UpdateProjectResourceAttachmentPayload,
)

PROJECT_CREATE_TO_COLUMN: dict[str, str] = {
    "name": "name",
    "description": "description",
    "status": "status",
    "leadAgentId": "lead_agent_id",
    "targetDate": "target_date",
    "color": "color",
    "executionWorkspacePolicy": "execution_workspace_policy",
    "archivedAt": "archived_at",
}
PROJECT_UPDATE_TO_COLUMN = PROJECT_CREATE_TO_COLUMN


def _normalize_project_url_key(value: str | None) -> str | None:
    if not value:
        return None
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized or None


def _derive_project_url_key(name: str | None, fallback: str | None = None) -> str:
    return (
        _normalize_project_url_key(name)
        or _normalize_project_url_key(fallback)
        or "project"
    )


def _parse_date(value: object) -> date | None:
    if value is None or isinstance(value, date):
        return cast(date | None, value)
    return date.fromisoformat(str(value))


def _parse_datetime(value: object) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return cast(datetime | None, value)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _iso(value: date | datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _resolve_goal_ids(
    payload: CreateProjectPayload | UpdateProjectPayload,
) -> list[str] | None:
    if "goalIds" in payload:
        return list(payload["goalIds"])
    if "goalId" in payload:
        return [payload["goalId"]] if payload["goalId"] is not None else []
    return None


class ProjectService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_org(self, org_id: str) -> list[ProjectDetail]:
        rows = await list_org_projects(self._session, org_id)
        return [await self._to_detail(row) for row in rows]

    async def get_by_id(self, project_id: str) -> ProjectDetail | None:
        row = await get_project_by_id(self._session, project_id)
        return await self._to_detail(row) if row is not None else None

    async def resolve_by_reference(
        self, reference: str, *, org_id: str | None
    ) -> ProjectDetail | None:
        row = await self.get_by_id(reference)
        if row is not None or org_id is None:
            return row
        matches = [
            item
            for item in await self.list_for_org(org_id)
            if item["urlKey"] == _normalize_project_url_key(reference)
        ]
        if len(matches) > 1:
            raise ValueError(
                "Project shortname is ambiguous in this organization. Use the project ID."
            )
        return matches[0] if matches else None

    async def create_project(
        self,
        org_id: str,
        payload: CreateProjectPayload,
        *,
        actor_type: str,
        actor_id: str,
    ) -> ProjectDetail:
        goal_ids = _resolve_goal_ids(payload)
        values = {
            PROJECT_CREATE_TO_COLUMN[key]: value
            for key, value in payload.items()
            if key in PROJECT_CREATE_TO_COLUMN
        }
        values["org_id"] = org_id
        values["name"] = await self._unique_name(org_id, str(payload["name"]).strip())
        if goal_ids is not None:
            values["goal_id"] = goal_ids[0] if goal_ids else None
        values.setdefault("status", DEFAULT_PROJECT_STATUS)
        if "target_date" in values:
            values["target_date"] = _parse_date(values["target_date"])
        if "archived_at" in values:
            values["archived_at"] = _parse_datetime(values["archived_at"])
        if not values.get("color"):
            existing = await list_org_projects(self._session, org_id)
            used_colors = {item.color for item in existing if item.color}
            values["color"] = next(
                (color for color in PROJECT_COLORS if color not in used_colors),
                PROJECT_COLORS[len(existing) % len(PROJECT_COLORS)],
            )
        project = await create_project(self._session, values)
        if goal_ids is not None:
            await replace_project_goals(self._session, project.id, org_id, goal_ids)
        await self._replace_resources(
            project,
            payload.get("resourceAttachments", []),
            payload.get("newResources", []),
        )
        await insert_activity_log(
            self._session,
            org_id=org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="project.created",
            entity_type="project",
            entity_id=project.id,
            details={"name": project.name},
        )
        return await self._to_detail(project)

    async def update_project(
        self,
        project_id: str,
        payload: UpdateProjectPayload,
        *,
        actor_type: str,
        actor_id: str,
    ) -> ProjectDetail | None:
        existing = await get_project_by_id(self._session, project_id)
        if existing is None:
            return None
        goal_ids = _resolve_goal_ids(payload)
        values = {
            PROJECT_UPDATE_TO_COLUMN[key]: value
            for key, value in payload.items()
            if key in PROJECT_UPDATE_TO_COLUMN
        }
        if "name" in values:
            values["name"] = await self._unique_name(
                existing.org_id, str(values["name"]).strip(), excluding_id=existing.id
            )
        if "target_date" in values:
            values["target_date"] = _parse_date(values["target_date"])
        if "archived_at" in values:
            values["archived_at"] = _parse_datetime(values["archived_at"])
        if goal_ids is not None:
            values["goal_id"] = goal_ids[0] if goal_ids else None
        row = await update_project(self._session, project_id, values)
        if row is None:
            return None
        if goal_ids is not None:
            await replace_project_goals(self._session, row.id, row.org_id, goal_ids)
        if "resourceAttachments" in payload or "newResources" in payload:
            attachment_inputs = payload.get("resourceAttachments")
            if attachment_inputs is None:
                current = await self.list_resources(row.id)
                attachment_inputs = [
                    cast(
                        ProjectResourceAttachmentInput,
                        {
                            "resourceId": attachment["resourceId"],
                            "role": attachment["role"],
                            "note": attachment["note"],
                            "sortOrder": attachment["sortOrder"],
                        },
                    )
                    for attachment in current
                ]
            await self._replace_resources(
                row,
                attachment_inputs,
                payload.get("newResources", []),
            )
        if payload:
            await insert_activity_log(
                self._session,
                org_id=row.org_id,
                actor_type=actor_type,
                actor_id=actor_id,
                action="project.updated",
                entity_type="project",
                entity_id=row.id,
                details=dict(payload),
            )
        return await self._to_detail(row)

    async def delete_project(
        self, project_id: str, *, actor_type: str, actor_id: str
    ) -> ProjectDetail | None:
        detail = await self.get_by_id(project_id)
        if detail is None:
            return None
        row = await delete_project(self._session, project_id)
        if row is None:
            return None
        await insert_activity_log(
            self._session,
            org_id=row.org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="project.deleted",
            entity_type="project",
            entity_id=row.id,
        )
        return detail

    async def list_resources(
        self, project_id: str
    ) -> list[ProjectResourceAttachmentData]:
        rows = await list_project_resource_attachments(self._session, project_id)
        return [await self._to_attachment(row) for row in rows]

    async def add_resource_attachment(
        self,
        project_id: str,
        payload: ProjectResourceAttachmentInput,
        *,
        actor_type: str,
        actor_id: str,
    ) -> ProjectResourceAttachmentData | None:
        project = await get_project_by_id(self._session, project_id)
        resource = await get_organization_resource_by_id(
            self._session, payload["resourceId"]
        )
        if project is None or resource is None or resource.org_id != project.org_id:
            return None
        existing = await get_project_resource_attachment_by_resource(
            self._session, project.id, resource.id
        )
        if existing is None:
            row = await create_project_resource_attachment(
                self._session,
                {
                    "org_id": project.org_id,
                    "project_id": project.id,
                    "resource_id": resource.id,
                    "role": payload.get("role", "reference"),
                    "note": payload.get("note"),
                    "sort_order": payload.get("sortOrder", 0),
                },
            )
        else:
            values: dict[str, Any] = {}
            if "role" in payload:
                values["role"] = payload["role"]
            if "note" in payload:
                values["note"] = payload["note"]
            if "sortOrder" in payload:
                values["sort_order"] = payload["sortOrder"]
            row = await update_project_resource_attachment(
                self._session, existing.id, values
            )
            if row is None:
                return None
        await insert_activity_log(
            self._session,
            org_id=project.org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="project.resource.attached",
            entity_type="project_resource_attachment",
            entity_id=row.id,
            details={
                "projectId": project.id,
                "resourceId": resource.id,
                "role": row.role,
            },
        )
        return await self._to_attachment(row)

    async def update_resource_attachment(
        self,
        project_id: str,
        attachment_id: str,
        payload: UpdateProjectResourceAttachmentPayload,
        *,
        actor_type: str,
        actor_id: str,
    ) -> ProjectResourceAttachmentData | None:
        existing = await get_project_resource_attachment(
            self._session, project_id, attachment_id
        )
        if existing is None:
            return None
        values: dict[str, Any] = {}
        if "role" in payload:
            values["role"] = payload["role"]
        if "note" in payload:
            values["note"] = payload["note"]
        if "sortOrder" in payload:
            values["sort_order"] = payload["sortOrder"]
        row = await update_project_resource_attachment(
            self._session, attachment_id, values
        )
        if row is None:
            return None
        await insert_activity_log(
            self._session,
            org_id=row.org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="project.resource.updated",
            entity_type="project_resource_attachment",
            entity_id=row.id,
            details=dict(payload),
        )
        return await self._to_attachment(row)

    async def remove_resource_attachment(
        self,
        project_id: str,
        attachment_id: str,
        *,
        actor_type: str,
        actor_id: str,
    ) -> ProjectResourceAttachmentData | None:
        existing = await get_project_resource_attachment(
            self._session, project_id, attachment_id
        )
        if existing is None:
            return None
        detail = await self._to_attachment(existing)
        row = await delete_project_resource_attachment(self._session, attachment_id)
        if row is None:
            return None
        await insert_activity_log(
            self._session,
            org_id=row.org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="project.resource.detached",
            entity_type="project_resource_attachment",
            entity_id=row.id,
            details={"resourceId": row.resource_id},
        )
        return detail

    async def _unique_name(
        self, org_id: str, name: str, *, excluding_id: str | None = None
    ) -> str:
        rows = await list_org_projects(self._session, org_id)
        used = {
            _derive_project_url_key(row.name, row.id)
            for row in rows
            if row.id != excluding_id
        }
        if _derive_project_url_key(name) not in used:
            return name
        suffix = 2
        while _derive_project_url_key(f"{name} {suffix}") in used:
            suffix += 1
        return f"{name} {suffix}"

    async def _replace_resources(
        self,
        project: Project,
        attachments: list[ProjectResourceAttachmentInput],
        inline_resources: Sequence[CreateProjectInlineResourceInput],
    ) -> None:
        combined_attachments = list(attachments)
        for inline in inline_resources:
            resource = await create_organization_resource(
                self._session,
                {
                    "org_id": project.org_id,
                    "name": str(inline["name"]).strip(),
                    "kind": inline["kind"],
                    "locator": str(inline["locator"]).strip(),
                    "description": inline.get("description"),
                    "metadata_json": inline.get("metadata"),
                },
            )
            combined_attachments = [
                *combined_attachments,
                {
                    "resourceId": resource.id,
                    "role": cast(
                        ProjectResourceAttachmentRole,
                        inline.get("role", "reference"),
                    ),
                    "note": cast(str | None, inline.get("note")),
                    "sortOrder": cast(
                        int, inline.get("sortOrder", len(combined_attachments))
                    ),
                },
            ]
        await delete_project_resource_attachments(self._session, project.id)
        for index, attachment in enumerate(combined_attachments):
            resource = await get_organization_resource_by_id(
                self._session, attachment["resourceId"]
            )
            if resource is None or resource.org_id != project.org_id:
                raise ValueError(
                    "Project resource must belong to the same organization"
                )
            await create_project_resource_attachment(
                self._session,
                {
                    "org_id": project.org_id,
                    "project_id": project.id,
                    "resource_id": resource.id,
                    "role": attachment.get("role", "reference"),
                    "note": attachment.get("note"),
                    "sort_order": attachment.get("sortOrder", index),
                },
            )

    async def _to_attachment(
        self, row: ProjectResourceAttachment
    ) -> ProjectResourceAttachmentData:
        resource = await get_organization_resource_by_id(self._session, row.resource_id)
        if resource is None:
            raise ValueError("Project resource attachment has no resource")
        return {
            "id": row.id,
            "orgId": row.org_id,
            "projectId": row.project_id,
            "resourceId": row.resource_id,
            "role": cast(ProjectResourceAttachmentRole, row.role),
            "note": row.note,
            "sortOrder": row.sort_order,
            "resource": _to_resource(resource),
            "createdAt": row.created_at.isoformat(),
            "updatedAt": row.updated_at.isoformat(),
        }

    async def _to_detail(self, row: Project) -> ProjectDetail:
        goal_rows = await list_project_goals(self._session, row.id)
        goal_refs: list[ProjectGoalRef] = [
            {"id": goal.id, "title": goal.title} for goal in goal_rows
        ]
        return {
            "id": row.id,
            "orgId": row.org_id,
            "urlKey": _derive_project_url_key(row.name, row.id),
            "goalId": row.goal_id,
            "goalIds": [goal["id"] for goal in goal_refs],
            "goals": goal_refs,
            "name": row.name,
            "description": row.description,
            "status": cast(ProjectStatus, row.status),
            "leadAgentId": row.lead_agent_id,
            "targetDate": _iso(row.target_date),
            "color": row.color,
            "pauseReason": cast(PauseReason | None, row.pause_reason),
            "pausedAt": _iso(row.paused_at),
            "executionWorkspacePolicy": row.execution_workspace_policy,
            "resources": await self.list_resources(row.id),
            "archivedAt": _iso(row.archived_at),
            "createdAt": row.created_at.isoformat(),
            "updatedAt": row.updated_at.isoformat(),
        }


def _to_resource(row: OrganizationResource) -> OrganizationResourceData:
    return {
        "id": row.id,
        "orgId": row.org_id,
        "name": row.name,
        "kind": cast(OrganizationResourceKind, row.kind),
        "locator": row.locator,
        "description": row.description,
        "metadata": row.metadata_json,
        "createdAt": row.created_at.isoformat(),
        "updatedAt": row.updated_at.isoformat(),
    }
