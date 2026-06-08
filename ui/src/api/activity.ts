import { jsonRequest, request } from "./client";
import type { ActivityEvent, ActivityQuery, CreateActivityPayload, HeartbeatRun, IssueListItem } from "./types";

function queryString(query: ActivityQuery = {}): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== "") params.set(key, String(value));
  }
  const value = params.toString();
  return value ? `?${value}` : "";
}

export const activityApi = {
  listOrg: (orgId: string, query: ActivityQuery = {}): Promise<ActivityEvent[]> =>
    request<ActivityEvent[]>(
      `/api/orgs/${encodeURIComponent(orgId)}/activity${queryString(query)}`,
      { method: "GET" },
    ),
  create: (orgId: string, payload: CreateActivityPayload): Promise<ActivityEvent> =>
    jsonRequest<ActivityEvent>(`/api/orgs/${encodeURIComponent(orgId)}/activity`, "POST", payload),
  listIssue: (issueId: string, query: ActivityQuery = {}): Promise<ActivityEvent[]> =>
    request<ActivityEvent[]>(
      `/api/issues/${encodeURIComponent(issueId)}/activity${queryString(query)}`,
      { method: "GET" },
    ),
  issueRuns: (issueId: string): Promise<HeartbeatRun[]> =>
    request<HeartbeatRun[]>(`/api/issues/${encodeURIComponent(issueId)}/runs`, { method: "GET" }),
  runIssues: (runId: string): Promise<IssueListItem[]> =>
    request<IssueListItem[]>(`/api/heartbeat-runs/${encodeURIComponent(runId)}/issues`, { method: "GET" }),
};
