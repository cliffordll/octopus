import { jsonRequest, request } from "./client";
import type {
  ApprovalDetail,
  ApprovalListItem,
  ApprovalStatus,
  CreateApprovalPayload,
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
  approve: (approvalId: string, decisionNote?: string): Promise<ApprovalDetail> =>
    jsonRequest<ApprovalDetail>(
      `${approvalRoot(approvalId)}/approve`,
      "POST",
      decisionNote ? { decisionNote } : {},
    ),
  reject: (approvalId: string, decisionNote?: string): Promise<ApprovalDetail> =>
    jsonRequest<ApprovalDetail>(
      `${approvalRoot(approvalId)}/reject`,
      "POST",
      decisionNote ? { decisionNote } : {},
    ),
  requestRevision: (approvalId: string, decisionNote?: string): Promise<ApprovalDetail> =>
    jsonRequest<ApprovalDetail>(
      `${approvalRoot(approvalId)}/request-revision`,
      "POST",
      decisionNote ? { decisionNote } : {},
    ),
  resubmit: (approvalId: string, payload: ResubmitApprovalPayload): Promise<ApprovalDetail> =>
    jsonRequest<ApprovalDetail>(`${approvalRoot(approvalId)}/resubmit`, "POST", payload),
};
