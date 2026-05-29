import { jsonRequest, request } from "./client";
import type {
  CreateOrganizationSkillPayload,
  OrganizationSkill,
  OrganizationSkillDetail,
  OrganizationSkillFileDetail,
  OrganizationSkillListItem,
  OrganizationSkillUpdateStatus,
  UpdateOrganizationSkillFilePayload,
} from "./types";

function root(orgId: string): string {
  return `/api/orgs/${encodeURIComponent(orgId)}/skills`;
}

export const organizationSkillsApi = {
  list: (orgId: string): Promise<OrganizationSkillListItem[]> =>
    request<OrganizationSkillListItem[]>(root(orgId), { method: "GET" }),
  create: (orgId: string, payload: CreateOrganizationSkillPayload): Promise<OrganizationSkill> =>
    jsonRequest<OrganizationSkill>(root(orgId), "POST", payload),
  get: (orgId: string, skillId: string): Promise<OrganizationSkillDetail> =>
    request<OrganizationSkillDetail>(`${root(orgId)}/${encodeURIComponent(skillId)}`, { method: "GET" }),
  updateStatus: (orgId: string, skillId: string): Promise<OrganizationSkillUpdateStatus> =>
    request<OrganizationSkillUpdateStatus>(
      `${root(orgId)}/${encodeURIComponent(skillId)}/update-status`,
      { method: "GET" },
    ),
  readFile: (orgId: string, skillId: string, path = "SKILL.md"): Promise<OrganizationSkillFileDetail> =>
    request<OrganizationSkillFileDetail>(
      `${root(orgId)}/${encodeURIComponent(skillId)}/files?path=${encodeURIComponent(path)}`,
      { method: "GET" },
    ),
  updateFile: (
    orgId: string,
    skillId: string,
    payload: UpdateOrganizationSkillFilePayload,
  ): Promise<OrganizationSkillFileDetail> =>
    jsonRequest<OrganizationSkillFileDetail>(
      `${root(orgId)}/${encodeURIComponent(skillId)}/files`,
      "PATCH",
      payload,
    ),
  delete: (orgId: string, skillId: string): Promise<OrganizationSkill> =>
    request<OrganizationSkill>(`${root(orgId)}/${encodeURIComponent(skillId)}`, { method: "DELETE" }),
};
