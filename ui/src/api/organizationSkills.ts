import { jsonRequest, request } from "./client";
import type {
  CreateOrganizationSkillPayload,
  ImportOrganizationSkillPayload,
  OrganizationSkill,
  OrganizationSkillDetail,
  OrganizationSkillFileDetail,
  OrganizationSkillListItem,
  OrganizationSkillScanLocalResult,
  OrganizationSkillUpdateStatus,
  ScanLocalOrganizationSkillsPayload,
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
  import: (orgId: string, payload: ImportOrganizationSkillPayload): Promise<OrganizationSkill> =>
    jsonRequest<OrganizationSkill>(`${root(orgId)}/import`, "POST", payload),
  scanLocal: (orgId: string, payload: ScanLocalOrganizationSkillsPayload): Promise<OrganizationSkillScanLocalResult> =>
    jsonRequest<OrganizationSkillScanLocalResult>(`${root(orgId)}/scan-local`, "POST", payload),
  get: (orgId: string, skillId: string): Promise<OrganizationSkillDetail> =>
    request<OrganizationSkillDetail>(`${root(orgId)}/${encodeURIComponent(skillId)}`, { method: "GET" }),
  installUpdate: (orgId: string, skillId: string): Promise<OrganizationSkill> =>
    jsonRequest<OrganizationSkill>(`${root(orgId)}/${encodeURIComponent(skillId)}/install-update`, "POST", {}),
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
