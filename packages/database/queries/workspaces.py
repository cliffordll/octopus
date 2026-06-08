from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.schema import (
    ExecutionWorkspace,
    IssueWorkProduct,
    ProjectWorkspace,
    WorkspaceRuntimeService,
    WorkspaceOperation,
)
from ._compat import delete_returning_one, update_returning_one


async def list_project_workspaces(
    session: AsyncSession, project_id: str
) -> Sequence[ProjectWorkspace]:
    result = await session.execute(
        select(ProjectWorkspace)
        .where(ProjectWorkspace.project_id == project_id)
        .order_by(
            desc(ProjectWorkspace.is_primary),
            ProjectWorkspace.created_at,
            ProjectWorkspace.id,
        )
    )
    return result.scalars().all()


async def create_project_workspace(
    session: AsyncSession, fields: Mapping[str, Any]
) -> ProjectWorkspace:
    row = ProjectWorkspace(**dict(fields))
    session.add(row)
    await session.flush()
    return row


async def get_project_workspace(
    session: AsyncSession, project_id: str, workspace_id: str
) -> ProjectWorkspace | None:
    result = await session.execute(
        select(ProjectWorkspace).where(
            ProjectWorkspace.project_id == project_id,
            ProjectWorkspace.id == workspace_id,
        )
    )
    return result.scalar_one_or_none()


async def update_project_workspace(
    session: AsyncSession, workspace_id: str, fields: Mapping[str, Any]
) -> ProjectWorkspace | None:
    values = dict(fields)
    values["updated_at"] = datetime.now(UTC)
    return await update_returning_one(
        session,
        ProjectWorkspace,
        ProjectWorkspace.id == workspace_id,
        values,
    )


async def delete_project_workspace(
    session: AsyncSession, workspace_id: str
) -> ProjectWorkspace | None:
    return await delete_returning_one(
        session,
        ProjectWorkspace,
        ProjectWorkspace.id == workspace_id,
    )


async def clear_primary_project_workspace(
    session: AsyncSession, *, org_id: str, project_id: str
) -> None:
    await session.execute(
        update(ProjectWorkspace)
        .where(
            ProjectWorkspace.org_id == org_id,
            ProjectWorkspace.project_id == project_id,
        )
        .values(is_primary=False, updated_at=datetime.now(UTC))
    )


async def list_execution_workspaces(
    session: AsyncSession,
    org_id: str,
    *,
    project_id: str | None = None,
    project_workspace_id: str | None = None,
    issue_id: str | None = None,
    status: str | None = None,
    reuse_eligible: bool = False,
) -> Sequence[ExecutionWorkspace]:
    statement = select(ExecutionWorkspace).where(ExecutionWorkspace.org_id == org_id)
    if project_id is not None:
        statement = statement.where(ExecutionWorkspace.project_id == project_id)
    if project_workspace_id is not None:
        statement = statement.where(
            ExecutionWorkspace.project_workspace_id == project_workspace_id
        )
    if issue_id is not None:
        statement = statement.where(ExecutionWorkspace.source_issue_id == issue_id)
    if status is not None:
        statuses = [item.strip() for item in status.split(",") if item.strip()]
        if len(statuses) == 1:
            statement = statement.where(ExecutionWorkspace.status == statuses[0])
        elif statuses:
            statement = statement.where(ExecutionWorkspace.status.in_(statuses))
    if reuse_eligible:
        statement = statement.where(
            ExecutionWorkspace.status.in_(("active", "idle", "in_review"))
        )
    result = await session.execute(
        statement.order_by(
            desc(ExecutionWorkspace.last_used_at), desc(ExecutionWorkspace.created_at)
        )
    )
    return result.scalars().all()


async def get_execution_workspace_by_id(
    session: AsyncSession, workspace_id: str
) -> ExecutionWorkspace | None:
    result = await session.execute(
        select(ExecutionWorkspace).where(ExecutionWorkspace.id == workspace_id)
    )
    return result.scalar_one_or_none()


async def create_execution_workspace(
    session: AsyncSession, fields: Mapping[str, Any]
) -> ExecutionWorkspace:
    row = ExecutionWorkspace(**dict(fields))
    session.add(row)
    await session.flush()
    return row


async def update_execution_workspace(
    session: AsyncSession, workspace_id: str, fields: Mapping[str, Any]
) -> ExecutionWorkspace | None:
    if not fields:
        return await get_execution_workspace_by_id(session, workspace_id)
    values = dict(fields)
    values["updated_at"] = datetime.now(UTC)
    return await update_returning_one(
        session,
        ExecutionWorkspace,
        ExecutionWorkspace.id == workspace_id,
        values,
    )


async def create_workspace_runtime_service(
    session: AsyncSession, fields: Mapping[str, Any]
) -> WorkspaceRuntimeService:
    row = WorkspaceRuntimeService(**dict(fields))
    session.add(row)
    await session.flush()
    return row


async def update_workspace_runtime_service(
    session: AsyncSession, service_id: str, fields: Mapping[str, Any]
) -> WorkspaceRuntimeService | None:
    values = dict(fields)
    values["updated_at"] = datetime.now(UTC)
    return await update_returning_one(
        session,
        WorkspaceRuntimeService,
        WorkspaceRuntimeService.id == service_id,
        values,
    )


async def list_workspace_runtime_services_for_run(
    session: AsyncSession, run_id: str
) -> Sequence[WorkspaceRuntimeService]:
    result = await session.execute(
        select(WorkspaceRuntimeService)
        .where(WorkspaceRuntimeService.started_by_run_id == run_id)
        .order_by(
            desc(WorkspaceRuntimeService.updated_at),
            desc(WorkspaceRuntimeService.created_at),
        )
    )
    return result.scalars().all()


async def list_workspace_runtime_services_for_workspace(
    session: AsyncSession, execution_workspace_id: str
) -> Sequence[WorkspaceRuntimeService]:
    result = await session.execute(
        select(WorkspaceRuntimeService)
        .where(WorkspaceRuntimeService.execution_workspace_id == execution_workspace_id)
        .order_by(
            desc(WorkspaceRuntimeService.updated_at),
            desc(WorkspaceRuntimeService.created_at),
        )
    )
    return result.scalars().all()


async def create_workspace_operation(
    session: AsyncSession, fields: Mapping[str, Any]
) -> WorkspaceOperation:
    row = WorkspaceOperation(**dict(fields))
    session.add(row)
    await session.flush()
    return row


async def update_workspace_operation(
    session: AsyncSession, operation_id: str, fields: Mapping[str, Any]
) -> WorkspaceOperation | None:
    values = dict(fields)
    values["updated_at"] = datetime.now(UTC)
    return await update_returning_one(
        session,
        WorkspaceOperation,
        WorkspaceOperation.id == operation_id,
        values,
    )


async def get_workspace_operation(
    session: AsyncSession, operation_id: str
) -> WorkspaceOperation | None:
    return await session.get(WorkspaceOperation, operation_id)


async def list_workspace_operations_for_run(
    session: AsyncSession, run_id: str
) -> Sequence[WorkspaceOperation]:
    result = await session.execute(
        select(WorkspaceOperation)
        .where(WorkspaceOperation.heartbeat_run_id == run_id)
        .order_by(WorkspaceOperation.started_at, WorkspaceOperation.created_at)
    )
    return result.scalars().all()


async def list_running_workspace_operations_for_run(
    session: AsyncSession, run_id: str
) -> Sequence[WorkspaceOperation]:
    result = await session.execute(
        select(WorkspaceOperation)
        .where(
            WorkspaceOperation.heartbeat_run_id == run_id,
            WorkspaceOperation.status == "running",
        )
        .order_by(WorkspaceOperation.started_at, WorkspaceOperation.created_at)
    )
    return result.scalars().all()


async def list_workspace_operations_for_execution_workspace(
    session: AsyncSession, execution_workspace_id: str
) -> Sequence[WorkspaceOperation]:
    result = await session.execute(
        select(WorkspaceOperation)
        .where(WorkspaceOperation.execution_workspace_id == execution_workspace_id)
        .order_by(
            desc(WorkspaceOperation.started_at), desc(WorkspaceOperation.created_at)
        )
    )
    return result.scalars().all()


async def list_issue_work_products(
    session: AsyncSession, issue_id: str
) -> Sequence[IssueWorkProduct]:
    result = await session.execute(
        select(IssueWorkProduct)
        .where(IssueWorkProduct.issue_id == issue_id)
        .order_by(desc(IssueWorkProduct.is_primary), desc(IssueWorkProduct.updated_at))
    )
    return result.scalars().all()


async def get_issue_work_product(
    session: AsyncSession, product_id: str
) -> IssueWorkProduct | None:
    result = await session.execute(
        select(IssueWorkProduct).where(IssueWorkProduct.id == product_id)
    )
    return result.scalar_one_or_none()


async def create_issue_work_product(
    session: AsyncSession, fields: Mapping[str, Any]
) -> IssueWorkProduct:
    if fields.get("is_primary"):
        await session.execute(
            update(IssueWorkProduct)
            .where(
                IssueWorkProduct.org_id == fields["org_id"],
                IssueWorkProduct.issue_id == fields["issue_id"],
                IssueWorkProduct.type == fields["type"],
            )
            .values(is_primary=False, updated_at=datetime.now(UTC))
        )
    row = IssueWorkProduct(**dict(fields))
    session.add(row)
    await session.flush()
    return row


async def update_issue_work_product(
    session: AsyncSession, product_id: str, fields: Mapping[str, Any]
) -> IssueWorkProduct | None:
    existing = await get_issue_work_product(session, product_id)
    if existing is None:
        return None
    if fields.get("is_primary"):
        await session.execute(
            update(IssueWorkProduct)
            .where(
                IssueWorkProduct.org_id == existing.org_id,
                IssueWorkProduct.issue_id == existing.issue_id,
                IssueWorkProduct.type == existing.type,
            )
            .values(is_primary=False, updated_at=datetime.now(UTC))
        )
    values = dict(fields)
    values["updated_at"] = datetime.now(UTC)
    await session.execute(
        update(IssueWorkProduct)
        .where(IssueWorkProduct.id == product_id)
        .values(**values)
    )
    await session.flush()
    return await get_issue_work_product(session, product_id)


async def delete_issue_work_product(
    session: AsyncSession, product_id: str
) -> IssueWorkProduct | None:
    existing = await get_issue_work_product(session, product_id)
    if existing is None:
        return None
    await session.execute(
        delete(IssueWorkProduct).where(IssueWorkProduct.id == product_id)
    )
    await session.flush()
    return existing
