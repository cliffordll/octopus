import { jsonRequest, request } from "./client";
import type {
  CostDimensionRow,
  CostEvent,
  CostQuery,
  CostSummary,
  CostTrendRow,
  CostWindowSpend,
  CreateCostEventPayload,
} from "./types";

function root(orgId: string) {
  return `/api/orgs/${encodeURIComponent(orgId)}`;
}

function query(params: CostQuery = {}) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && String(value).trim()) {
      search.set(key, String(value));
    }
  }
  const value = search.toString();
  return value ? `?${value}` : "";
}

export const costsApi = {
  report: (orgId: string, payload: CreateCostEventPayload): Promise<CostEvent> =>
    jsonRequest<CostEvent>(`${root(orgId)}/cost-events`, "POST", payload),
  summary: (orgId: string, params?: CostQuery): Promise<CostSummary> =>
    request<CostSummary>(`${root(orgId)}/costs/summary${query(params)}`, { method: "GET" }),
  byAgent: (orgId: string, params?: CostQuery): Promise<CostDimensionRow[]> =>
    request<CostDimensionRow[]>(`${root(orgId)}/costs/by-agent${query(params)}`, { method: "GET" }),
  byProvider: (orgId: string, params?: CostQuery): Promise<CostDimensionRow[]> =>
    request<CostDimensionRow[]>(`${root(orgId)}/costs/by-provider${query(params)}`, { method: "GET" }),
  byBiller: (orgId: string, params?: CostQuery): Promise<CostDimensionRow[]> =>
    request<CostDimensionRow[]>(`${root(orgId)}/costs/by-biller${query(params)}`, { method: "GET" }),
  byProject: (orgId: string, params?: CostQuery): Promise<CostDimensionRow[]> =>
    request<CostDimensionRow[]>(`${root(orgId)}/costs/by-project${query(params)}`, { method: "GET" }),
  byAgentModel: (orgId: string, params?: CostQuery): Promise<CostDimensionRow[]> =>
    request<CostDimensionRow[]>(`${root(orgId)}/costs/by-agent-model${query(params)}`, { method: "GET" }),
  trend: (orgId: string, params?: CostQuery): Promise<CostTrendRow[]> =>
    request<CostTrendRow[]>(`${root(orgId)}/costs/trend${query(params)}`, { method: "GET" }),
  windowSpend: (orgId: string, params?: CostQuery): Promise<CostWindowSpend> =>
    request<CostWindowSpend>(`${root(orgId)}/costs/window-spend${query(params)}`, { method: "GET" }),
};
