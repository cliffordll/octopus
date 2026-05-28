import type { IssueStatus } from "../api/types";

export interface RecentIssue {
  id: string;
  title: string;
  identifier: string | null;
  status: IssueStatus;
}

export const RECENT_ISSUES_EVENT = "octopus:recent-issues-updated";

export function recentIssuesKey(orgId: string): string {
  return `octopus:recent-issues:${orgId}`;
}

export function readRecentIssues(orgId: string): RecentIssue[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(recentIssuesKey(orgId)) ?? "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((item): item is RecentIssue => (
      typeof item?.id === "string"
      && typeof item?.title === "string"
      && (typeof item?.identifier === "string" || item?.identifier === null)
      && typeof item?.status === "string"
    ));
  } catch {
    return [];
  }
}

export function writeRecentIssue(orgId: string, issue: RecentIssue): void {
  const current = readRecentIssues(orgId);
  const next = [issue, ...current.filter((item) => item.id !== issue.id)].slice(0, 5);
  localStorage.setItem(recentIssuesKey(orgId), JSON.stringify(next));
  window.dispatchEvent(new CustomEvent(RECENT_ISSUES_EVENT, { detail: { orgId } }));
}
