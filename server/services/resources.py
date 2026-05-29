from __future__ import annotations

from collections.abc import Mapping
import uuid
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.activity_log import insert_activity_log
from packages.database.queries.resources import (
    create_organization_resource,
    delete_organization_resource,
    get_organization_resource_by_org,
    list_organization_resources,
    update_organization_resource,
)
from packages.database.schema import OrganizationResource
from packages.shared.constants.project import OrganizationResourceKind
from packages.shared.types.resource import (
    OrganizationResource as OrganizationResourceData,
)


class ResourceService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_org_resources(self, org_id: str) -> list[OrganizationResourceData]:
        rows = await list_organization_resources(self._session, org_id)
        return [_to_resource(row) for row in rows]

    async def create_org_resource(
        self,
        org_id: str,
        payload: Mapping[str, Any],
        *,
        actor_type: str,
        actor_id: str,
    ) -> OrganizationResourceData:
        row = await create_organization_resource(
            self._session,
            {
                "id": str(uuid.uuid4()),
                "org_id": org_id,
                "name": payload["name"],
                "kind": payload["kind"],
                "locator": payload["locator"],
                "description": payload.get("description"),
                "metadata_json": payload.get("metadata"),
            },
        )
        await insert_activity_log(
            self._session,
            org_id=org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="organization.resource.created",
            entity_type="organization_resource",
            entity_id=row.id,
            details={
                "name": row.name,
                "kind": row.kind,
                "locator": row.locator,
            },
        )
        return _to_resource(row)

    async def update_org_resource(
        self,
        org_id: str,
        resource_id: str,
        payload: Mapping[str, Any],
        *,
        actor_type: str,
        actor_id: str,
    ) -> OrganizationResourceData | None:
        existing = await get_organization_resource_by_org(
            self._session, org_id, resource_id
        )
        if existing is None:
            return None
        values = _resource_update_columns(payload)
        if values:
            row = await update_organization_resource(
                self._session, org_id, resource_id, values
            )
            if row is None:
                return None
        else:
            row = existing
        await insert_activity_log(
            self._session,
            org_id=org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="organization.resource.updated",
            entity_type="organization_resource",
            entity_id=resource_id,
            details=dict(payload),
        )
        return _to_resource(row)

    async def delete_org_resource(
        self,
        org_id: str,
        resource_id: str,
        *,
        actor_type: str,
        actor_id: str,
    ) -> OrganizationResourceData | None:
        existing = await get_organization_resource_by_org(
            self._session, org_id, resource_id
        )
        if existing is None:
            return None
        detail = _to_resource(existing)
        row = await delete_organization_resource(self._session, org_id, resource_id)
        if row is None:
            return None
        await insert_activity_log(
            self._session,
            org_id=org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="organization.resource.deleted",
            entity_type="organization_resource",
            entity_id=resource_id,
            details={"name": row.name, "kind": row.kind},
        )
        return detail


def _resource_update_columns(payload: Mapping[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    if "name" in payload:
        values["name"] = payload["name"]
    if "kind" in payload:
        values["kind"] = payload["kind"]
    if "locator" in payload:
        values["locator"] = payload["locator"]
    if "description" in payload:
        values["description"] = payload["description"]
    if "metadata" in payload:
        values["metadata_json"] = payload["metadata"]
    return values


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
