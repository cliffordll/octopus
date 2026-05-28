import { jsonRequest, request } from "./client";
import type { HeartbeatRun, HeartbeatRunEvent } from "./types";

interface InvokeOptions {
  idempotencyKey?: string;
  reason?: string;
  forceFreshSession?: boolean;
}

interface EventOptions {
  afterSeq?: number;
  limit?: number;
}

export const heartbeatApi = {
  wakeup: (agentId: string, options: InvokeOptions = {}): Promise<HeartbeatRun> =>
    jsonRequest<HeartbeatRun>(
      `/api/agents/${encodeURIComponent(agentId)}/wakeup`,
      "POST",
      options,
    ),
  invoke: (agentId: string, options: InvokeOptions = {}): Promise<HeartbeatRun> =>
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
  cancel: (runId: string): Promise<HeartbeatRun> =>
    jsonRequest<HeartbeatRun>(`/api/heartbeat-runs/${encodeURIComponent(runId)}/cancel`, "POST", {}),
  retry: (runId: string): Promise<HeartbeatRun> =>
    jsonRequest<HeartbeatRun>(`/api/heartbeat-runs/${encodeURIComponent(runId)}/retry`, "POST", {}),
};
