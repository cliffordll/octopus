import { jsonRequest, request } from "./client";
import type {
  CreateOrganizationPayload,
  CreateOrganizationResourcePayload,
  OrganizationDetail,
  OrganizationResource,
  OrganizationSummary,
  OrganizationWorkspaceFileDetail,
  OrganizationWorkspaceFileList,
  UpdateOrganizationPayload,
  UpdateOrganizationResourcePayload,
} from "./types";

const root = "/api/orgs";

export const organizationsApi = {
  list: (): Promise<OrganizationSummary[]> =>
    request<OrganizationSummary[]>(root, { method: "GET" }),
  get: (orgId: string): Promise<OrganizationDetail> =>
    request<OrganizationDetail>(`${root}/${encodeURIComponent(orgId)}`, { method: "GET" }),
  create: (payload: CreateOrganizationPayload): Promise<OrganizationDetail> =>
    jsonRequest<OrganizationDetail>(root, "POST", payload),
  update: (orgId: string, payload: UpdateOrganizationPayload): Promise<OrganizationDetail> =>
    jsonRequest<OrganizationDetail>(`${root}/${encodeURIComponent(orgId)}`, "PATCH", payload),
  archive: (orgId: string): Promise<OrganizationDetail> =>
    jsonRequest<OrganizationDetail>(`${root}/${encodeURIComponent(orgId)}/archive`, "POST", {}),
  resources: (orgId: string): Promise<OrganizationResource[]> =>
    request<OrganizationResource[]>(`${root}/${encodeURIComponent(orgId)}/resources`, { method: "GET" }),
  createResource: (orgId: string, payload: CreateOrganizationResourcePayload): Promise<OrganizationResource> =>
    jsonRequest<OrganizationResource>(`${root}/${encodeURIComponent(orgId)}/resources`, "POST", payload),
  updateResource: (
    orgId: string,
    resourceId: string,
    payload: UpdateOrganizationResourcePayload,
  ): Promise<OrganizationResource> =>
    jsonRequest<OrganizationResource>(
      `${root}/${encodeURIComponent(orgId)}/resources/${encodeURIComponent(resourceId)}`,
      "PATCH",
      payload,
    ),
  deleteResource: (orgId: string, resourceId: string): Promise<OrganizationResource> =>
    request<OrganizationResource>(
      `${root}/${encodeURIComponent(orgId)}/resources/${encodeURIComponent(resourceId)}`,
      { method: "DELETE" },
    ),
  workspaceFiles: (orgId: string, path = ""): Promise<OrganizationWorkspaceFileList> =>
    request<OrganizationWorkspaceFileList>(
      `${root}/${encodeURIComponent(orgId)}/workspace/files?path=${encodeURIComponent(path)}`,
      { method: "GET" },
    ),
  workspaceFile: (orgId: string, path: string): Promise<OrganizationWorkspaceFileDetail> =>
    request<OrganizationWorkspaceFileDetail>(
      `${root}/${encodeURIComponent(orgId)}/workspace/file?path=${encodeURIComponent(path)}`,
      { method: "GET" },
    ),
};
