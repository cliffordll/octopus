import { jsonRequest, request } from "./client";
import type {
  Agent,
  AgentConfigRevision,
  AgentConfiguration,
  AgentDetail,
  AgentRuntimeState,
  AgentTaskSession,
  CreateAgentPayload,
  ResetAgentSessionPayload,
  UpdateAgentPayload,
} from "./types";

function agentRoot(agentId: string): string {
  return `/api/agents/${encodeURIComponent(agentId)}`;
}

export const agentsApi = {
  list: (orgId: string): Promise<Agent[]> =>
    request<Agent[]>(`/api/orgs/${encodeURIComponent(orgId)}/agents`, { method: "GET" }),
  nameSuggestion: (orgId: string): Promise<{ name: string }> =>
    request<{ name: string }>(`/api/orgs/${encodeURIComponent(orgId)}/agents/name-suggestion`, { method: "GET" }),
  configurations: (orgId: string): Promise<AgentConfiguration[]> =>
    request<AgentConfiguration[]>(`/api/orgs/${encodeURIComponent(orgId)}/agent-configurations`, { method: "GET" }),
  get: (agentId: string): Promise<AgentDetail> =>
    request<AgentDetail>(agentRoot(agentId), { method: "GET" }),
  create: (orgId: string, payload: CreateAgentPayload): Promise<Agent> =>
    jsonRequest<Agent>(`/api/orgs/${encodeURIComponent(orgId)}/agents`, "POST", payload),
  update: (agentId: string, payload: UpdateAgentPayload): Promise<Agent> =>
    jsonRequest<Agent>(agentRoot(agentId), "PATCH", payload),
  configuration: (agentId: string): Promise<AgentConfiguration> =>
    request<AgentConfiguration>(`${agentRoot(agentId)}/configuration`, { method: "GET" }),
  configRevisions: (agentId: string): Promise<AgentConfigRevision[]> =>
    request<AgentConfigRevision[]>(`${agentRoot(agentId)}/config-revisions`, { method: "GET" }),
  configRevision: (agentId: string, revisionId: string): Promise<AgentConfigRevision> =>
    request<AgentConfigRevision>(
      `${agentRoot(agentId)}/config-revisions/${encodeURIComponent(revisionId)}`,
      { method: "GET" },
    ),
  rollbackConfigRevision: (agentId: string, revisionId: string): Promise<Agent> =>
    jsonRequest<Agent>(
      `${agentRoot(agentId)}/config-revisions/${encodeURIComponent(revisionId)}/rollback`,
      "POST",
      {},
    ),
  runtimeState: (agentId: string): Promise<AgentRuntimeState> =>
    request<AgentRuntimeState>(`${agentRoot(agentId)}/runtime-state`, { method: "GET" }),
  taskSessions: (agentId: string): Promise<AgentTaskSession[]> =>
    request<AgentTaskSession[]>(`${agentRoot(agentId)}/task-sessions`, { method: "GET" }),
  resetSession: (agentId: string, payload: ResetAgentSessionPayload): Promise<AgentRuntimeState> =>
    jsonRequest<AgentRuntimeState>(`${agentRoot(agentId)}/runtime-state/reset-session`, "POST", payload),
  pause: (agentId: string): Promise<Agent> =>
    jsonRequest<Agent>(`${agentRoot(agentId)}/pause`, "POST", {}),
  resume: (agentId: string): Promise<Agent> =>
    jsonRequest<Agent>(`${agentRoot(agentId)}/resume`, "POST", {}),
  terminate: (agentId: string): Promise<Agent> =>
    jsonRequest<Agent>(`${agentRoot(agentId)}/terminate`, "POST", {}),
};
