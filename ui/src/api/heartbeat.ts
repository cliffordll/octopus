import { jsonRequest, request } from "./client";
import type { HeartbeatRun, HeartbeatRunEvent, LogReadResult, WakeAgentPayload, WorkspaceOperation } from "./types";

interface EventOptions {
  afterSeq?: number;
  limit?: number;
}

interface LogOptions {
  limitBytes?: number;
  offset?: number;
}

export const heartbeatApi = {
  wakeup: (agentId: string, options: WakeAgentPayload = {}): Promise<HeartbeatRun> =>
    jsonRequest<HeartbeatRun>(
      `/api/agents/${encodeURIComponent(agentId)}/wakeup`,
      "POST",
      options,
    ),
  invoke: (agentId: string, options: WakeAgentPayload = {}): Promise<HeartbeatRun> =>
    jsonRequest<HeartbeatRun>(
      `/api/agents/${encodeURIComponent(agentId)}/heartbeat/invoke`,
      "POST",
      options,
    ),
  list: (orgId: string, agentId?: string): Promise<HeartbeatRun[]> => {
    const query = agentId ? `?agentId=${encodeURIComponent(agentId)}` : "";
    return request<HeartbeatRun[]>(
      `/api/orgs/${encodeURIComponent(orgId)}/heartbeat-runs${query}`,
      { method: "GET" },
    );
  },
  get: (runId: string): Promise<HeartbeatRun> =>
    request<HeartbeatRun>(`/api/heartbeat-runs/${encodeURIComponent(runId)}`, { method: "GET" }),
  listEvents: (runId: string, options: EventOptions = {}): Promise<HeartbeatRunEvent[]> => {
    const params = new URLSearchParams();
    if (options.afterSeq !== undefined) params.set("afterSeq", String(options.afterSeq));
    if (options.limit !== undefined) params.set("limit", String(options.limit));
    const query = params.size > 0 ? `?${params.toString()}` : "";
    return request<HeartbeatRunEvent[]>(`/api/heartbeat-runs/${encodeURIComponent(runId)}/events${query}`, {
      method: "GET",
    });
  },
  getLog: (runId: string, options: LogOptions = {}): Promise<LogReadResult> => {
    const params = new URLSearchParams();
    if (options.offset !== undefined) params.set("offset", String(options.offset));
    if (options.limitBytes !== undefined) params.set("limitBytes", String(options.limitBytes));
    const query = params.size > 0 ? `?${params.toString()}` : "";
    return request<LogReadResult>(`/api/heartbeat-runs/${encodeURIComponent(runId)}/log${query}`, {
      method: "GET",
    });
  },
  listWorkspaceOperations: (runId: string): Promise<WorkspaceOperation[]> =>
    request<WorkspaceOperation[]>(`/api/heartbeat-runs/${encodeURIComponent(runId)}/workspace-operations`, {
      method: "GET",
    }),
  cancel: (runId: string): Promise<HeartbeatRun> =>
    jsonRequest<HeartbeatRun>(`/api/heartbeat-runs/${encodeURIComponent(runId)}/cancel`, "POST", {}),
  retry: (runId: string): Promise<HeartbeatRun> =>
    jsonRequest<HeartbeatRun>(`/api/heartbeat-runs/${encodeURIComponent(runId)}/retry`, "POST", {}),
};
