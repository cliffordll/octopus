import { jsonRequest, request } from "./client";
import type { HeartbeatRun, HeartbeatRunEvent } from "./types";

export const heartbeatApi = {
  invoke: (agentId: string): Promise<HeartbeatRun> =>
    jsonRequest<HeartbeatRun>(
      `/api/agents/${encodeURIComponent(agentId)}/heartbeat/invoke`,
      "POST",
      {},
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
  listEvents: (runId: string): Promise<HeartbeatRunEvent[]> =>
    request<HeartbeatRunEvent[]>(`/api/heartbeat-runs/${encodeURIComponent(runId)}/events`, {
      method: "GET",
    }),
};
