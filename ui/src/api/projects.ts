import { jsonRequest, request } from "./client";
import type {
  CreateProjectPayload,
  CreateProjectWorkspacePayload,
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
