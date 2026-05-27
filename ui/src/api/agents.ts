import { jsonRequest, request } from "./client";
import type { Agent, AgentDetail, CreateAgentPayload } from "./types";

function agentRoot(agentId: string): string {
  return `/api/agents/${encodeURIComponent(agentId)}`;
}

export const agentsApi = {
  list: (orgId: string): Promise<Agent[]> =>
    request<Agent[]>(`/api/orgs/${encodeURIComponent(orgId)}/agents`, { method: "GET" }),
  get: (agentId: string): Promise<AgentDetail> =>
    request<AgentDetail>(agentRoot(agentId), { method: "GET" }),
  create: (orgId: string, payload: CreateAgentPayload): Promise<Agent> =>
    jsonRequest<Agent>(`/api/orgs/${encodeURIComponent(orgId)}/agents`, "POST", payload),
  pause: (agentId: string): Promise<Agent> =>
    jsonRequest<Agent>(`${agentRoot(agentId)}/pause`, "POST", {}),
  resume: (agentId: string): Promise<Agent> =>
    jsonRequest<Agent>(`${agentRoot(agentId)}/resume`, "POST", {}),
  terminate: (agentId: string): Promise<Agent> =>
    jsonRequest<Agent>(`${agentRoot(agentId)}/terminate`, "POST", {}),
};
