import { jsonRequest, request } from "./client";
import type {
  CreateIssuePayload,
  IssueAttachment,
  IssueComment,
  IssueDetail,
  IssueFilters,
  IssueListItem,
  IssueReviewDecision,
  HeartbeatRun,
  CheckoutIssuePayload,
  UpdateIssuePayload,
} from "./types";

function issueRoot(issueId: string): string {
  return `/api/issues/${encodeURIComponent(issueId)}`;
}

export const issuesApi = {
  list: (orgId: string, filters: IssueFilters = {}): Promise<IssueListItem[]> => {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(filters)) {
      if (value !== undefined && value !== "") {
        query.set(key, value);
      }
    }
    const suffix = query.size ? `?${query.toString()}` : "";
    return request<IssueListItem[]>(
      `/api/orgs/${encodeURIComponent(orgId)}/issues${suffix}`,
      { method: "GET" },
    );
  },
  get: (issueId: string): Promise<IssueDetail> =>
    request<IssueDetail>(issueRoot(issueId), { method: "GET" }),
  create: (orgId: string, payload: CreateIssuePayload): Promise<IssueDetail> =>
    jsonRequest<IssueDetail>(`/api/orgs/${encodeURIComponent(orgId)}/issues`, "POST", payload),
  update: (issueId: string, payload: UpdateIssuePayload): Promise<IssueDetail> =>
    jsonRequest<IssueDetail>(issueRoot(issueId), "PATCH", payload),
  checkout: (issueId: string, payload: CheckoutIssuePayload): Promise<IssueDetail> =>
    jsonRequest<IssueDetail>(`${issueRoot(issueId)}/checkout`, "POST", payload),
  execute: (issueId: string): Promise<HeartbeatRun> =>
    jsonRequest<HeartbeatRun>(`${issueRoot(issueId)}/execute`, "POST", {}),
  heartbeatContext: (issueId: string): Promise<Record<string, unknown>> =>
    request<Record<string, unknown>>(`${issueRoot(issueId)}/heartbeat-context`, { method: "GET" }),
  listRuns: (issueId: string): Promise<HeartbeatRun[]> =>
    request<HeartbeatRun[]>(`${issueRoot(issueId)}/heartbeat-runs`, { method: "GET" }),
  listComments: (issueId: string): Promise<IssueComment[]> =>
    request<IssueComment[]>(`${issueRoot(issueId)}/comments`, { method: "GET" }),
  listAttachments: (issueId: string): Promise<IssueAttachment[]> =>
    request<IssueAttachment[]>(`${issueRoot(issueId)}/attachments`, { method: "GET" }),
  uploadAttachment: (
    orgId: string,
    issueId: string,
    payload: { file: File; issueCommentId?: string | null; usage?: string },
  ): Promise<IssueAttachment> => {
    const form = new FormData();
    form.set("file", payload.file);
    if (payload.usage) form.set("usage", payload.usage);
    if (payload.issueCommentId) form.set("issueCommentId", payload.issueCommentId);
    return request<IssueAttachment>(
      `/api/orgs/${encodeURIComponent(orgId)}/issues/${encodeURIComponent(issueId)}/attachments`,
      { method: "POST", body: form },
    );
  },
  deleteAttachment: (attachmentId: string): Promise<Record<string, never>> =>
    request<Record<string, never>>(`/api/attachments/${encodeURIComponent(attachmentId)}`, { method: "DELETE" }),
  addComment: (issueId: string, payload: { body: string }): Promise<IssueComment> =>
    jsonRequest<IssueComment>(`${issueRoot(issueId)}/comments`, "POST", payload),
  review: (
    issueId: string,
    payload: { decision: IssueReviewDecision; note?: string | null },
  ): Promise<IssueDetail> =>
    jsonRequest<IssueDetail>(`${issueRoot(issueId)}/review-decision`, "POST", payload),
};
