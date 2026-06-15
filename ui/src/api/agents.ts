import { jsonRequest, request } from "./client";
import type {
  Agent,
  AgentConfigRevision,
  AgentConfiguration,
  AgentInstructionsBundle,
  AgentInstructionsFileDetail,
  AgentInstructionsPathResult,
  AgentDetail,
  AgentHireResult,
  AgentInboxItem,
  AgentMemoryFileDetail,
  AgentMemoryFileList,
  AgentRuntimeEnvironmentTestResult,
  AgentRuntimeModel,
  AgentRuntimeState,
  AgentSkillAnalytics,
  AgentSkillSnapshot,
  AgentTaskSession,
  CreateAgentPayload,
  HireAgentPayload,
  PrivateSkillPayload,
  ProviderQuotaResult,
  ResetAgentSessionPayload,
  RuntimeAdapterMetadata,
  UpdateAgentInstructionsBundlePayload,
  UpdateAgentInstructionsFilePayload,
  UpdateAgentInstructionsPathPayload,
  UpdateAgentMemoryFilePayload,
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
  adapterModels: (orgId: string, runtime: string): Promise<AgentRuntimeModel[]> =>
    request<AgentRuntimeModel[]>(
      `/api/orgs/${encodeURIComponent(orgId)}/adapters/${encodeURIComponent(runtime)}/models`,
      { method: "GET" },
    ),
  adapterMetadata: (orgId: string, runtime: string): Promise<RuntimeAdapterMetadata> =>
    request<RuntimeAdapterMetadata>(
      `/api/orgs/${encodeURIComponent(orgId)}/adapters/${encodeURIComponent(runtime)}`,
      { method: "GET" },
    ),
  adapterQuotaWindows: (orgId: string, runtime: string): Promise<ProviderQuotaResult> =>
    request<ProviderQuotaResult>(
      `/api/orgs/${encodeURIComponent(orgId)}/adapters/${encodeURIComponent(runtime)}/quota-windows`,
      { method: "GET" },
    ),
  testAdapterEnvironment: (
    orgId: string,
    runtime: string,
    agentRuntimeConfig: Record<string, unknown>,
  ): Promise<AgentRuntimeEnvironmentTestResult> =>
    jsonRequest<AgentRuntimeEnvironmentTestResult>(
      `/api/orgs/${encodeURIComponent(orgId)}/adapters/${encodeURIComponent(runtime)}/test-environment`,
      "POST",
      { agentRuntimeConfig },
    ),
  get: (agentId: string): Promise<AgentDetail> =>
    request<AgentDetail>(agentRoot(agentId), { method: "GET" }),
  create: (orgId: string, payload: CreateAgentPayload): Promise<Agent> =>
    jsonRequest<Agent>(`/api/orgs/${encodeURIComponent(orgId)}/agents`, "POST", payload),
  hire: (orgId: string, payload: HireAgentPayload, actorAgentId?: string): Promise<AgentHireResult> =>
    jsonRequest<AgentHireResult>(
      `/api/orgs/${encodeURIComponent(orgId)}/agent-hires`,
      "POST",
      payload,
      actorAgentId
        ? { headers: { "x-test-agent-id": actorAgentId, "x-test-org-id": orgId } }
        : {},
    ),
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
  inbox: (agentId: string): Promise<AgentInboxItem[]> =>
    request<AgentInboxItem[]>(`${agentRoot(agentId)}/inbox-lite`, { method: "GET" }),
  taskSessions: (agentId: string): Promise<AgentTaskSession[]> =>
    request<AgentTaskSession[]>(`${agentRoot(agentId)}/task-sessions`, { method: "GET" }),
  resetSession: (agentId: string, payload: ResetAgentSessionPayload): Promise<AgentRuntimeState> =>
    jsonRequest<AgentRuntimeState>(`${agentRoot(agentId)}/runtime-state/reset-session`, "POST", payload),
  skills: (agentId: string): Promise<AgentSkillSnapshot> =>
    request<AgentSkillSnapshot>(`${agentRoot(agentId)}/skills`, { method: "GET" }),
  syncSkills: (agentId: string, desiredSkills: string[]): Promise<AgentSkillSnapshot> =>
    jsonRequest<AgentSkillSnapshot>(`${agentRoot(agentId)}/skills/sync`, "POST", { desiredSkills }),
  enableSkills: (agentId: string, skills: string[]): Promise<AgentSkillSnapshot> =>
    jsonRequest<AgentSkillSnapshot>(`${agentRoot(agentId)}/skills/enable`, "POST", { skills }),
  createPrivateSkill: (agentId: string, payload: PrivateSkillPayload): Promise<Record<string, unknown>> =>
    jsonRequest<Record<string, unknown>>(`${agentRoot(agentId)}/skills/private`, "POST", payload),
  skillsAnalytics: (agentId: string, windowDays = 30): Promise<AgentSkillAnalytics> =>
    request<AgentSkillAnalytics>(
      `${agentRoot(agentId)}/skills/analytics?windowDays=${encodeURIComponent(String(windowDays))}`,
      { method: "GET" },
    ),
  instructionsBundle: (agentId: string): Promise<AgentInstructionsBundle> =>
    request<AgentInstructionsBundle>(`${agentRoot(agentId)}/instructions-bundle`, { method: "GET" }),
  updateInstructionsBundle: (
    agentId: string,
    payload: UpdateAgentInstructionsBundlePayload,
  ): Promise<AgentInstructionsBundle> =>
    jsonRequest<AgentInstructionsBundle>(`${agentRoot(agentId)}/instructions-bundle`, "PATCH", payload),
  updateInstructionsPath: (
    agentId: string,
    payload: UpdateAgentInstructionsPathPayload,
  ): Promise<AgentInstructionsPathResult> =>
    jsonRequest<AgentInstructionsPathResult>(`${agentRoot(agentId)}/instructions-path`, "PATCH", payload),
  readInstructionFile: (agentId: string, path: string): Promise<AgentInstructionsFileDetail> =>
    request<AgentInstructionsFileDetail>(
      `${agentRoot(agentId)}/instructions-bundle/file?path=${encodeURIComponent(path)}`,
      { method: "GET" },
    ),
  upsertInstructionFile: (
    agentId: string,
    payload: UpdateAgentInstructionsFilePayload,
  ): Promise<AgentInstructionsFileDetail> =>
    request<AgentInstructionsFileDetail>(`${agentRoot(agentId)}/instructions-bundle/file`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  deleteInstructionFile: (agentId: string, path: string): Promise<AgentInstructionsBundle> =>
    request<AgentInstructionsBundle>(
      `${agentRoot(agentId)}/instructions-bundle/file?path=${encodeURIComponent(path)}`,
      { method: "DELETE" },
    ),
  memoryFiles: (agentId: string, layer: "memory" | "life", path = ""): Promise<AgentMemoryFileList> =>
    request<AgentMemoryFileList>(
      `${agentRoot(agentId)}/memory/files?layer=${encodeURIComponent(layer)}&path=${encodeURIComponent(path)}`,
      { method: "GET" },
    ),
  readMemoryFile: (agentId: string, layer: "memory" | "life", path: string): Promise<AgentMemoryFileDetail> =>
    request<AgentMemoryFileDetail>(
      `${agentRoot(agentId)}/memory/file?layer=${encodeURIComponent(layer)}&path=${encodeURIComponent(path)}`,
      { method: "GET" },
    ),
  upsertMemoryFile: (agentId: string, payload: UpdateAgentMemoryFilePayload): Promise<AgentMemoryFileDetail> =>
    request<AgentMemoryFileDetail>(`${agentRoot(agentId)}/memory/file`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  deleteMemoryFile: (agentId: string, layer: "memory" | "life", path: string): Promise<AgentMemoryFileList> =>
    request<AgentMemoryFileList>(
      `${agentRoot(agentId)}/memory/file?layer=${encodeURIComponent(layer)}&path=${encodeURIComponent(path)}`,
      { method: "DELETE" },
    ),
  pause: (agentId: string): Promise<Agent> =>
    jsonRequest<Agent>(`${agentRoot(agentId)}/pause`, "POST", {}),
  resume: (agentId: string): Promise<Agent> =>
    jsonRequest<Agent>(`${agentRoot(agentId)}/resume`, "POST", {}),
  terminate: (agentId: string): Promise<Agent> =>
    jsonRequest<Agent>(`${agentRoot(agentId)}/terminate`, "POST", {}),
  archive: (agentId: string): Promise<Agent> =>
    jsonRequest<Agent>(`${agentRoot(agentId)}/archive`, "POST", {}),
};
