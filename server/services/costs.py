from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.activity_log import insert_activity_log
from packages.database.queries.agents import get_agent_by_id
from packages.database.queries.costs import (
    create_cost_event,
    increment_agent_spend,
    increment_organization_spend,
    list_cost_events,
)
from packages.database.queries.heartbeat import get_run
from packages.database.queries.organizations import get_organization_by_id
from packages.database.schema import CostEvent, Project
from packages.shared.types.cost import (
    CostDimensionRow,
    CostEvent as CostEventType,
    CostQuery,
    CostSummary,
    CostTrendRow,
    CostWindowSpend,
    CreateCostEventPayload,
)
from packages.shared.validators.cost import parse_cost_datetime

_UNATTRIBUTED = "unattributed"


class CostService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_event(
        self,
        org_id: str,
        payload: CreateCostEventPayload,
        *,
        actor_type: str,
        actor_id: str,
    ) -> CostEventType:
        organization = await get_organization_by_id(self._session, org_id)
        if organization is None:
            raise LookupError("Organization not found")

        agent_id = payload.get("agentId")
        if actor_type == "agent":
            if agent_id is None:
                agent_id = actor_id
            elif agent_id != actor_id:
                raise PermissionError("Agent actors can only report their own cost")
        elif actor_type not in {"board", "system"}:
            raise PermissionError("Board, system, or agent actor required")

        if agent_id is not None:
            agent = await get_agent_by_id(self._session, agent_id)
            if agent is None or agent.org_id != org_id:
                raise ValueError("Agent does not belong to this organization")

        project_id = payload.get("projectId")
        if project_id is not None:
            project = await self._session.get(Project, project_id)
            if project is None or project.org_id != org_id:
                raise ValueError("Project does not belong to this organization")

        cost_cents = int(payload.get("costCents", 0))
        occurred_at = parse_cost_datetime(payload.get("occurredAt")) or datetime.now(
            UTC
        )
        row = await create_cost_event(
            self._session,
            {
                "id": str(uuid.uuid4()),
                "org_id": org_id,
                "agent_id": agent_id,
                "project_id": project_id,
                "source_type": payload.get("sourceType"),
                "source_id": payload.get("sourceId"),
                "runtime_type": payload.get("runtimeType"),
                "provider": payload.get("provider"),
                "model": payload.get("model"),
                "biller": payload.get("biller"),
                "cost_cents": cost_cents,
                "cost_usd": payload.get("costUsd"),
                "input_tokens": payload.get("inputTokens"),
                "output_tokens": payload.get("outputTokens"),
                "total_tokens": payload.get("totalTokens"),
                "usage_json": payload.get("usage"),
                "metadata_json": payload.get("metadata"),
                "occurred_at": occurred_at,
            },
        )
        await increment_organization_spend(self._session, org_id, cost_cents)
        if agent_id is not None:
            await increment_agent_spend(self._session, agent_id, cost_cents)
        await insert_activity_log(
            self._session,
            org_id=org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="cost.reported",
            entity_type="cost_event",
            entity_id=row.id,
            agent_id=agent_id,
            details={
                "costCents": cost_cents,
                "sourceType": row.source_type,
                "sourceId": row.source_id,
                "provider": row.provider,
                "model": row.model,
                "biller": row.biller,
            },
        )
        return _to_cost_event(row)

    async def record_run_cost_if_present(self, run_id: str) -> CostEventType | None:
        run = await get_run(self._session, run_id)
        if run is None:
            return None
        result = run.result_json if isinstance(run.result_json, dict) else {}
        usage = run.usage_json if isinstance(run.usage_json, dict) else {}
        cost_cents = _cost_cents_from(result, usage)
        if cost_cents is None or cost_cents <= 0:
            return None
        return await self.create_event(
            run.org_id,
            {
                "agentId": run.agent_id,
                "sourceType": "run",
                "sourceId": run.id,
                "runtimeType": _string(result.get("runtimeType")),
                "provider": _string(result.get("provider")),
                "model": _string(result.get("model")),
                "biller": _string(result.get("biller")),
                "costCents": cost_cents,
                "inputTokens": _optional_int(
                    usage.get("inputTokens") or result.get("inputTokens")
                ),
                "outputTokens": _optional_int(
                    usage.get("outputTokens") or result.get("outputTokens")
                ),
                "totalTokens": _optional_int(
                    usage.get("totalTokens") or result.get("totalTokens")
                ),
                "usage": usage or None,
                "metadata": {"runtimeCostResult": result},
                "occurredAt": (
                    run.finished_at or run.started_at or run.created_at
                ).isoformat(),
            },
            actor_type="system",
            actor_id="runtime-cost-collector",
        )

    async def summary(self, org_id: str, query: CostQuery) -> CostSummary:
        rows = await self._list(org_id, query)
        totals = _totals(rows)
        return {
            "orgId": org_id,
            "totalCostCents": totals["totalCostCents"],
            "eventCount": totals["eventCount"],
            "inputTokens": totals["inputTokens"],
            "outputTokens": totals["outputTokens"],
            "totalTokens": totals["totalTokens"],
        }

    async def by_agent(
        self, org_id: str, query: CostQuery
    ) -> list[CostDimensionRow]:
        return _group(rows=await self._list(org_id, query), keys=("agent_id",))

    async def by_provider(
        self, org_id: str, query: CostQuery
    ) -> list[CostDimensionRow]:
        return _group(rows=await self._list(org_id, query), keys=("provider",))

    async def by_biller(
        self, org_id: str, query: CostQuery
    ) -> list[CostDimensionRow]:
        return _group(rows=await self._list(org_id, query), keys=("biller",))

    async def by_project(
        self, org_id: str, query: CostQuery
    ) -> list[CostDimensionRow]:
        return _group(rows=await self._list(org_id, query), keys=("project_id",))

    async def by_agent_model(
        self, org_id: str, query: CostQuery
    ) -> list[CostDimensionRow]:
        return _group(
            rows=await self._list(org_id, query),
            keys=("agent_id", "runtime_type", "provider", "model"),
        )

    async def trend(self, org_id: str, query: CostQuery) -> list[CostTrendRow]:
        rows = list(await self._list(org_id, query))
        grouped: dict[str, dict[str, int]] = {}
        for row in rows:
            bucket = row.occurred_at.date().isoformat()
            current = grouped.setdefault(bucket, {"costCents": 0, "eventCount": 0})
            current["costCents"] += row.cost_cents
            current["eventCount"] += 1
        result: list[CostTrendRow] = []
        for bucket, values in sorted(grouped.items(), reverse=True):
            result.append(
                {
                    "bucket": bucket,
                    "costCents": values["costCents"],
                    "eventCount": values["eventCount"],
                }
            )
        return result

    async def window_spend(self, org_id: str, query: CostQuery) -> CostWindowSpend:
        rows = list(await self._list(org_id, query))
        return {
            "orgId": org_id,
            "costCents": sum(row.cost_cents for row in rows),
            "eventCount": len(rows),
            "startTime": query.get("startTime"),
            "endTime": query.get("endTime"),
        }

    async def _list(self, org_id: str, query: CostQuery) -> Iterable[CostEvent]:
        return await list_cost_events(
            self._session,
            org_id,
            agent_id=query.get("agentId"),
            project_id=query.get("projectId"),
            provider=query.get("provider"),
            biller=query.get("biller"),
            model=query.get("model"),
            start_time=parse_cost_datetime(query.get("startTime")),
            end_time=parse_cost_datetime(query.get("endTime")),
            limit=query.get("limit"),
        )


def _to_cost_event(row: CostEvent) -> CostEventType:
    return {
        "id": row.id,
        "orgId": row.org_id,
        "agentId": row.agent_id,
        "projectId": row.project_id,
        "sourceType": row.source_type,
        "sourceId": row.source_id,
        "runtimeType": row.runtime_type,
        "provider": row.provider,
        "model": row.model,
        "biller": row.biller,
        "costCents": row.cost_cents,
        "costUsd": row.cost_usd,
        "inputTokens": row.input_tokens,
        "outputTokens": row.output_tokens,
        "totalTokens": row.total_tokens,
        "usage": row.usage_json,
        "metadata": row.metadata_json,
        "occurredAt": row.occurred_at.isoformat(),
        "createdAt": row.created_at.isoformat(),
    }


def _totals(rows: Iterable[CostEvent]) -> dict[str, int]:
    items = list(rows)
    return {
        "totalCostCents": sum(row.cost_cents for row in items),
        "eventCount": len(items),
        "inputTokens": sum(row.input_tokens or 0 for row in items),
        "outputTokens": sum(row.output_tokens or 0 for row in items),
        "totalTokens": sum(row.total_tokens or 0 for row in items),
    }


def _group(*, rows: Iterable[CostEvent], keys: tuple[str, ...]) -> list[CostDimensionRow]:
    grouped: dict[tuple[str | None, ...], dict[str, int]] = {}
    for row in rows:
        key = tuple(_row_value(row, item) for item in keys)
        current = grouped.setdefault(
            key,
            {
                "costCents": 0,
                "eventCount": 0,
                "inputTokens": 0,
                "outputTokens": 0,
                "totalTokens": 0,
            },
        )
        current["costCents"] += row.cost_cents
        current["eventCount"] += 1
        current["inputTokens"] += row.input_tokens or 0
        current["outputTokens"] += row.output_tokens or 0
        current["totalTokens"] += row.total_tokens or 0

    result: list[CostDimensionRow] = []
    for key, totals in grouped.items():
        item: CostDimensionRow = {
            "costCents": totals["costCents"],
            "eventCount": totals["eventCount"],
            "inputTokens": totals["inputTokens"],
            "outputTokens": totals["outputTokens"],
            "totalTokens": totals["totalTokens"],
        }
        for name, value in zip(keys, key, strict=True):
            _assign_dimension(item, name, value)
        result.append(item)
    return sorted(result, key=lambda item: int(item["costCents"]), reverse=True)


def _row_value(row: CostEvent, name: str) -> str | None:
    value = getattr(row, name)
    if value is None and name in {"provider", "biller", "model"}:
        return _UNATTRIBUTED
    return value


def _assign_dimension(item: CostDimensionRow, name: str, value: str | None) -> None:
    if name == "agent_id":
        item["agentId"] = value
    elif name == "project_id":
        item["projectId"] = value
    elif name == "runtime_type":
        item["runtimeType"] = value
    elif name == "provider":
        item["provider"] = value or _UNATTRIBUTED
    elif name == "biller":
        item["biller"] = value or _UNATTRIBUTED
    elif name == "model":
        item["model"] = value or _UNATTRIBUTED
    else:
        raise ValueError(f"Unsupported cost dimension {name}")


def _cost_cents_from(
    result: dict[str, object], usage: dict[str, object]
) -> int | None:
    for source in (result, usage):
        value = source.get("costCents")
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    for source in (result, usage):
        value = source.get("costUsd")
        if isinstance(value, int | float) and not isinstance(value, bool):
            return int(round(float(value) * 100))
    return None


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None
