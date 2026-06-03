import { request } from "./client";
import type { LogReadResult } from "./types";

export interface RunIntelligenceFilters {
  agentId?: string;
  createdBefore?: string;
  issueId?: string;
  limit?: number;
  runIdPrefix?: string;
  runtime?: string;
  status?: string;
  updatedAfter?: string;
}

export type RunIntelligenceRecord = Record<string, unknown>;

function runRoot(runId: string): string {
  return `/api/run-intelligence/runs/${encodeURIComponent(runId)}`;
}

export const runIntelligenceApi = {
  list: (orgId: string, filters: RunIntelligenceFilters = {}): Promise<RunIntelligenceRecord[]> => {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(filters)) {
      if (value !== undefined && value !== "") params.set(key, String(value));
    }
    const query = params.size ? `?${params.toString()}` : "";
    return request<RunIntelligenceRecord[]>(`/api/run-intelligence/orgs/${encodeURIComponent(orgId)}/runs${query}`, {
      method: "GET",
    });
  },
  get: (runId: string): Promise<RunIntelligenceRecord> =>
    request<RunIntelligenceRecord>(runRoot(runId), { method: "GET" }),
  events: (runId: string): Promise<RunIntelligenceRecord[]> =>
    request<RunIntelligenceRecord[]>(`${runRoot(runId)}/events`, { method: "GET" }),
  log: (runId: string): Promise<LogReadResult> =>
    request<LogReadResult>(`${runRoot(runId)}/log`, { method: "GET" }),
};
