import { jsonRequest, request } from "./client";
import type {
  CreateOrganizationPayload,
  OrganizationDetail,
  OrganizationSummary,
  UpdateOrganizationPayload,
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
};
