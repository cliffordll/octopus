import { jsonRequest, request } from "./client";
import type { HeartbeatRun } from "./types";

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
};
