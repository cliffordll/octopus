import { jsonRequest, request } from "./client";
import type {
  CreateIssuePayload,
  IssueComment,
  IssueDetail,
  IssueFilters,
  IssueListItem,
  IssueReviewDecision,
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
  listComments: (issueId: string): Promise<IssueComment[]> =>
    request<IssueComment[]>(`${issueRoot(issueId)}/comments`, { method: "GET" }),
  addComment: (issueId: string, payload: { body: string }): Promise<IssueComment> =>
    jsonRequest<IssueComment>(`${issueRoot(issueId)}/comments`, "POST", payload),
  review: (
    issueId: string,
    payload: { decision: IssueReviewDecision; note?: string | null },
  ): Promise<IssueDetail> =>
    jsonRequest<IssueDetail>(`${issueRoot(issueId)}/review-decision`, "POST", payload),
};
