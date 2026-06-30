import { jsonRequest, request } from "./client";
import type {
  CreateProjectPayload,
  CreateProjectWorkspacePayload,
  ExecutionWorkspace,
  ExecutionWorkspaceDiff,
  ExecutionWorkspaceMergePreview,
  ExecutionWorkspaceMergeResult,
  ExecutionWorkspacePullRequestPlan,
  ExecutionWorkspacePullRequestResult,
  ExecutionWorkspaceStatus,
  ProjectDetail,
  ProjectResourceAttachment,
  ProjectResourceAttachmentInput,
  ProjectWorkspace,
  UpdateProjectPayload,
  UpdateProjectResourceAttachmentPayload,
  UpdateProjectWorkspacePayload,
} from "./types";

function projectRoot(projectId: string): string {
  return `/api/projects/${encodeURIComponent(projectId)}`;
}

function executionWorkspaceRoot(workspaceId: string): string {
  return `/api/execution-workspaces/${encodeURIComponent(workspaceId)}`;
}

export const projectsApi = {
  list: (orgId: string): Promise<ProjectDetail[]> =>
    request<ProjectDetail[]>(`/api/orgs/${encodeURIComponent(orgId)}/projects`, { method: "GET" }),
  get: (projectId: string): Promise<ProjectDetail> =>
    request<ProjectDetail>(projectRoot(projectId), { method: "GET" }),
  create: (orgId: string, payload: CreateProjectPayload): Promise<ProjectDetail> =>
    jsonRequest<ProjectDetail>(
      `/api/orgs/${encodeURIComponent(orgId)}/projects`,
      "POST",
      payload,
    ),
  update: (projectId: string, payload: UpdateProjectPayload): Promise<ProjectDetail> =>
    jsonRequest<ProjectDetail>(projectRoot(projectId), "PATCH", payload),
  remove: (projectId: string): Promise<ProjectDetail> =>
    request<ProjectDetail>(projectRoot(projectId), { method: "DELETE" }),
  listWorkspaces: (projectId: string): Promise<ProjectWorkspace[]> =>
    request<ProjectWorkspace[]>(`${projectRoot(projectId)}/workspaces`, { method: "GET" }),
  createWorkspace: (projectId: string, payload: CreateProjectWorkspacePayload): Promise<ProjectWorkspace> =>
    jsonRequest<ProjectWorkspace>(`${projectRoot(projectId)}/workspaces`, "POST", payload),
  updateWorkspace: (
    projectId: string,
    workspaceId: string,
    payload: UpdateProjectWorkspacePayload,
  ): Promise<ProjectWorkspace> =>
    jsonRequest<ProjectWorkspace>(
      `${projectRoot(projectId)}/workspaces/${encodeURIComponent(workspaceId)}`,
      "PATCH",
      payload,
    ),
  removeWorkspace: (projectId: string, workspaceId: string): Promise<ProjectWorkspace> =>
    request<ProjectWorkspace>(
      `${projectRoot(projectId)}/workspaces/${encodeURIComponent(workspaceId)}`,
      { method: "DELETE" },
    ),
  listExecutionWorkspaces: (orgId: string, projectId: string): Promise<ExecutionWorkspace[]> =>
    request<ExecutionWorkspace[]>(`/api/execution-workspaces?orgId=${encodeURIComponent(orgId)}&projectId=${encodeURIComponent(projectId)}`, { method: "GET" }),
  listIssueExecutionWorkspaces: (orgId: string, issueId: string): Promise<ExecutionWorkspace[]> =>
    request<ExecutionWorkspace[]>(`/api/execution-workspaces?orgId=${encodeURIComponent(orgId)}&issueId=${encodeURIComponent(issueId)}`, { method: "GET" }),
  executionWorkspaceStatus: (workspaceId: string): Promise<ExecutionWorkspaceStatus> =>
    request<ExecutionWorkspaceStatus>(`${executionWorkspaceRoot(workspaceId)}/status`, { method: "GET" }),
  executionWorkspaceDiff: (workspaceId: string): Promise<ExecutionWorkspaceDiff> =>
    request<ExecutionWorkspaceDiff>(`${executionWorkspaceRoot(workspaceId)}/diff`, { method: "GET" }),
  executionWorkspaceMergePreview: (workspaceId: string, targetRef?: string | null): Promise<ExecutionWorkspaceMergePreview> =>
    jsonRequest<ExecutionWorkspaceMergePreview>(`${executionWorkspaceRoot(workspaceId)}/merge-preview`, "POST", { targetRef }),
  mergeExecutionWorkspace: (workspaceId: string, targetRef?: string | null): Promise<ExecutionWorkspaceMergeResult> =>
    jsonRequest<ExecutionWorkspaceMergeResult>(`${executionWorkspaceRoot(workspaceId)}/merge`, "POST", { targetRef }),
  prepareExecutionWorkspacePr: (workspaceId: string, targetRef?: string | null): Promise<ExecutionWorkspacePullRequestPlan> =>
    jsonRequest<ExecutionWorkspacePullRequestPlan>(`${executionWorkspaceRoot(workspaceId)}/prepare-pr`, "POST", { targetRef }),
  createExecutionWorkspacePr: (workspaceId: string, targetRef?: string | null): Promise<ExecutionWorkspacePullRequestResult> =>
    jsonRequest<ExecutionWorkspacePullRequestResult>(`${executionWorkspaceRoot(workspaceId)}/create-pr`, "POST", { targetRef }),
  pushExecutionWorkspace: (workspaceId: string): Promise<Record<string, unknown>> =>
    jsonRequest<Record<string, unknown>>(`${executionWorkspaceRoot(workspaceId)}/push`, "POST", {}),
  archiveExecutionWorkspace: (workspaceId: string): Promise<ExecutionWorkspace> =>
    jsonRequest<ExecutionWorkspace>(`${executionWorkspaceRoot(workspaceId)}/archive`, "POST", {}),
  abandonExecutionWorkspace: (workspaceId: string): Promise<ExecutionWorkspace> =>
    jsonRequest<ExecutionWorkspace>(`${executionWorkspaceRoot(workspaceId)}/abandon`, "POST", {}),
  cleanupExecutionWorkspace: (workspaceId: string, discardDirty = false): Promise<ExecutionWorkspace> =>
    jsonRequest<ExecutionWorkspace>(`${executionWorkspaceRoot(workspaceId)}/cleanup`, "POST", { discardDirty }),
  listResources: (projectId: string): Promise<ProjectResourceAttachment[]> =>
    request<ProjectResourceAttachment[]>(`${projectRoot(projectId)}/resources`, { method: "GET" }),
  addResource: (
    projectId: string,
    payload: ProjectResourceAttachmentInput,
  ): Promise<ProjectResourceAttachment> =>
    jsonRequest<ProjectResourceAttachment>(`${projectRoot(projectId)}/resources`, "POST", payload),
  updateResource: (
    projectId: string,
    attachmentId: string,
    payload: UpdateProjectResourceAttachmentPayload,
  ): Promise<ProjectResourceAttachment> =>
    jsonRequest<ProjectResourceAttachment>(
      `${projectRoot(projectId)}/resources/${encodeURIComponent(attachmentId)}`,
      "PATCH",
      payload,
    ),
  removeResource: (projectId: string, attachmentId: string): Promise<ProjectResourceAttachment> =>
    request<ProjectResourceAttachment>(
      `${projectRoot(projectId)}/resources/${encodeURIComponent(attachmentId)}`,
      { method: "DELETE" },
    ),
};
