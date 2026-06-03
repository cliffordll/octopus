import { jsonRequest, request } from "./client";
import type {
  CreateOrganizationPayload,
  CreateOrganizationResourcePayload,
  OrganizationDetail,
  OrganizationResource,
  OrganizationSummary,
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
};
