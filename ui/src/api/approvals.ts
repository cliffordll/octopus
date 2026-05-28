import { jsonRequest, request } from "./client";
import type {
  ApprovalDetail,
  ApprovalListItem,
  ApprovalStatus,
  CreateApprovalPayload,
  ResolveApprovalPayload,
  ResubmitApprovalPayload,
} from "./types";

function approvalRoot(approvalId: string): string {
  return `/api/approvals/${encodeURIComponent(approvalId)}`;
}

export const approvalsApi = {
  list: (orgId: string, status?: ApprovalStatus): Promise<ApprovalListItem[]> => {
    const suffix = status ? `?status=${encodeURIComponent(status)}` : "";
    return request<ApprovalListItem[]>(
      `/api/orgs/${encodeURIComponent(orgId)}/approvals${suffix}`,
      { method: "GET" },
    );
  },
  get: (approvalId: string): Promise<ApprovalDetail> =>
    request<ApprovalDetail>(approvalRoot(approvalId), { method: "GET" }),
  create: (orgId: string, payload: CreateApprovalPayload): Promise<ApprovalDetail> =>
    jsonRequest<ApprovalDetail>(
      `/api/orgs/${encodeURIComponent(orgId)}/approvals`,
      "POST",
      payload,
    ),
  approve: (approvalId: string, payload?: string | ResolveApprovalPayload): Promise<ApprovalDetail> =>
    jsonRequest<ApprovalDetail>(
      `${approvalRoot(approvalId)}/approve`,
      "POST",
      typeof payload === "string" ? { decisionNote: payload } : payload ?? {},
    ),
  reject: (approvalId: string, payload?: string | ResolveApprovalPayload): Promise<ApprovalDetail> =>
    jsonRequest<ApprovalDetail>(
      `${approvalRoot(approvalId)}/reject`,
      "POST",
      typeof payload === "string" ? { decisionNote: payload } : payload ?? {},
    ),
  requestRevision: (approvalId: string, payload?: string | ResolveApprovalPayload): Promise<ApprovalDetail> =>
    jsonRequest<ApprovalDetail>(
      `${approvalRoot(approvalId)}/request-revision`,
      "POST",
      typeof payload === "string" ? { decisionNote: payload } : payload ?? {},
    ),
  resubmit: (approvalId: string, payload: ResubmitApprovalPayload): Promise<ApprovalDetail> =>
    jsonRequest<ApprovalDetail>(`${approvalRoot(approvalId)}/resubmit`, "POST", payload),
};
