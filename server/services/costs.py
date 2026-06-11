from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, TypedDict
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
from packages.database.queries.runtime_providers import (
    get_global_runtime_model,
    get_runtime_model,
)
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


class EstimatedCost(TypedDict):
    costCents: int
    costUsd: float
    roundedUpToMinimumCent: bool


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
        from .budgets import BudgetService

        await BudgetService(self._session).evaluate_cost_event(row)
        return _to_cost_event(row)

    async def record_run_cost_if_present(self, run_id: str) -> CostEventType | None:
        run = await get_run(self._session, run_id)
        if run is None:
            return None
        result = run.result_json if isinstance(run.result_json, dict) else {}
        usage = run.usage_json if isinstance(run.usage_json, dict) else {}
        return await self.record_runtime_result_cost_if_present(
            org_id=run.org_id,
            agent_id=run.agent_id,
            source_type="run",
            source_id=run.id,
            runtime_type=_string(result.get("runtimeType")),
            result_json=result,
            usage_json=usage,
            occurred_at=run.finished_at or run.started_at or run.created_at,
        )

    async def record_runtime_result_cost_if_present(
        self,
        *,
        org_id: str,
        agent_id: str | None,
        source_type: str,
        source_id: str,
        runtime_type: str | None,
        result_json: dict[str, Any] | None,
        usage_json: dict[str, Any] | None,
        project_id: str | None = None,
        occurred_at: datetime | None = None,
    ) -> CostEventType | None:
        result = result_json if isinstance(result_json, dict) else {}
        usage = usage_json if isinstance(usage_json, dict) else {}
        cost_cents = _cost_cents_from(result, usage)
        estimated = False
        estimate: EstimatedCost | None = None
        pricing: dict[str, float] | None = None
        if cost_cents is None or cost_cents <= 0:
            pricing = await self._model_pricing(
                org_id=org_id,
                runtime_type=runtime_type,
                provider=_string(result.get("provider")),
                model=_string(result.get("model")),
            )
            estimate = _estimated_cost(usage, result, pricing)
            if estimate is not None:
                cost_cents = estimate["costCents"]
                estimated = True
        if cost_cents is None or cost_cents <= 0:
            return None
        metadata: dict[str, Any] = {"runtimeCostResult": result}
        if estimated:
            metadata["estimatedFromModelPricing"] = True
            metadata["pricing"] = pricing
            metadata["estimatedCostUsd"] = estimate["costUsd"] if estimate else None
            if estimate and estimate["roundedUpToMinimumCent"]:
                metadata["roundedUpToMinimumCent"] = True
        payload: CreateCostEventPayload = {
            "sourceType": source_type,
            "sourceId": source_id,
            "runtimeType": runtime_type,
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
            "metadata": metadata,
            "occurredAt": (occurred_at or datetime.now(UTC)).isoformat(),
        }
        if estimated:
            payload["costUsd"] = (
                estimate["costUsd"] if estimate else round(cost_cents / 100, 6)
            )
        if agent_id is not None:
            payload["agentId"] = agent_id
        if project_id is not None:
            payload["projectId"] = project_id
        return await self.create_event(
            org_id,
            payload,
            actor_type="system",
            actor_id="runtime-cost-collector",
        )

    async def _model_pricing(
        self,
        *,
        org_id: str,
        runtime_type: str | None,
        provider: str | None,
        model: str | None,
    ) -> dict[str, float] | None:
        if not runtime_type or not provider or not model:
            return None
        provider_id, model_id = _model_lookup_parts(provider, model)
        row = await get_runtime_model(
            self._session,
            org_id,
            runtime_type,
            provider_id,
            model_id,
        )
        if row is None:
            row = await get_global_runtime_model(
                self._session,
                runtime_type,
                provider_id,
                model_id,
            )
        if row is None:
            return None
        metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
        raw_pricing = metadata.get("pricing")
        if not isinstance(raw_pricing, dict):
            return None
        return _pricing(raw_pricing)

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

    async def by_agent(self, org_id: str, query: CostQuery) -> list[CostDimensionRow]:
        return _group(rows=await self._list(org_id, query), keys=("agent_id",))

    async def by_provider(
        self, org_id: str, query: CostQuery
    ) -> list[CostDimensionRow]:
        return _group(rows=await self._list(org_id, query), keys=("provider",))

    async def by_biller(self, org_id: str, query: CostQuery) -> list[CostDimensionRow]:
        return _group(rows=await self._list(org_id, query), keys=("biller",))

    async def by_project(self, org_id: str, query: CostQuery) -> list[CostDimensionRow]:
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


def _group(
    *, rows: Iterable[CostEvent], keys: tuple[str, ...]
) -> list[CostDimensionRow]:
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


def _cost_cents_from(result: dict[str, object], usage: dict[str, object]) -> int | None:
    for source in (result, usage):
        value = source.get("costCents")
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    for source in (result, usage):
        value = source.get("costUsd")
        if isinstance(value, int | float) and not isinstance(value, bool):
            return int(round(float(value) * 100))
    return None


def _estimated_cost(
    usage: dict[str, object],
    result: dict[str, object],
    pricing: dict[str, float] | None,
) -> EstimatedCost | None:
    if not pricing:
        return None
    input_tokens = _optional_int(usage.get("inputTokens") or result.get("inputTokens"))
    output_tokens = _optional_int(
        usage.get("outputTokens") or result.get("outputTokens")
    )
    cached_input_tokens = _optional_int(
        usage.get("cachedInputTokens") or result.get("cachedInputTokens")
    )
    cost_usd = 0.0
    cost_usd += (input_tokens or 0) / 1_000_000 * pricing.get("inputCostPer1M", 0)
    cost_usd += (output_tokens or 0) / 1_000_000 * pricing.get("outputCostPer1M", 0)
    cost_usd += (
        (cached_input_tokens or 0) / 1_000_000 * pricing.get("cachedInputCostPer1M", 0)
    )
    if cost_usd <= 0:
        return None
    rounded_cents = int(round(cost_usd * 100))
    cost_cents = max(1, rounded_cents)
    return {
        "costCents": cost_cents,
        "costUsd": round(cost_usd, 6),
        "roundedUpToMinimumCent": rounded_cents == 0,
    }


def _pricing(value: dict[str, object]) -> dict[str, float] | None:
    result: dict[str, float] = {}
    for key in ("inputCostPer1M", "outputCostPer1M", "cachedInputCostPer1M"):
        amount = value.get(key)
        if isinstance(amount, bool) or not isinstance(amount, int | float):
            continue
        normalized = float(amount)
        if normalized < 0:
            continue
        result[key] = normalized
    return result or None


def _model_lookup_parts(provider: str, model: str) -> tuple[str, str]:
    if "/" not in model:
        return provider, model
    model_provider, model_id = model.split("/", 1)
    model_provider = model_provider.strip()
    model_id = model_id.strip()
    if model_provider and model_id:
        return model_provider, model_id
    return provider, model


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None
