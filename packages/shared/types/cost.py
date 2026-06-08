from __future__ import annotations

from typing import Any, NotRequired, TypedDict


class CreateCostEventPayload(TypedDict, total=False):
    agentId: str
    projectId: str | None
    sourceType: str | None
    sourceId: str | None
    runtimeType: str | None
    provider: str | None
    model: str | None
    biller: str | None
    costCents: int
    costUsd: float
    inputTokens: int | None
    outputTokens: int | None
    totalTokens: int | None
    usage: dict[str, Any] | None
    metadata: dict[str, Any] | None
    occurredAt: str


class CostEvent(TypedDict):
    id: str
    orgId: str
    agentId: str | None
    projectId: str | None
    sourceType: str | None
    sourceId: str | None
    runtimeType: str | None
    provider: str | None
    model: str | None
    biller: str | None
    costCents: int
    costUsd: float | None
    inputTokens: int | None
    outputTokens: int | None
    totalTokens: int | None
    usage: dict[str, Any] | None
    metadata: dict[str, Any] | None
    occurredAt: str
    createdAt: str


class CostQuery(TypedDict, total=False):
    agentId: str
    projectId: str
    provider: str
    biller: str
    model: str
    startTime: str
    endTime: str
    limit: int


class CostSummary(TypedDict):
    orgId: str
    totalCostCents: int
    eventCount: int
    inputTokens: int
    outputTokens: int
    totalTokens: int


class CostDimensionRow(TypedDict):
    costCents: int
    eventCount: int
    inputTokens: int
    outputTokens: int
    totalTokens: int
    agentId: NotRequired[str | None]
    projectId: NotRequired[str | None]
    provider: NotRequired[str]
    biller: NotRequired[str]
    model: NotRequired[str]
    runtimeType: NotRequired[str | None]


class CostTrendRow(TypedDict):
    bucket: str
    costCents: int
    eventCount: int


class CostWindowSpend(TypedDict):
    orgId: str
    costCents: int
    eventCount: int
    startTime: str | None
    endTime: str | None
