export type OrganizationStatus = "active" | "paused" | "archived";

export interface OrganizationSummary {
  id: string;
  urlKey: string;
  name: string;
  status: OrganizationStatus;
}

export interface OrganizationDetail extends OrganizationSummary {
  description: string | null;
  issuePrefix: string;
  issueCounter: number;
  budgetMonthlyCents: number;
  spentMonthlyCents: number;
  brandColor: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface CreateOrganizationPayload {
  name: string;
  description?: string | null;
  budgetMonthlyCents?: number;
  brandColor?: string | null;
}

export type UpdateOrganizationPayload = Partial<CreateOrganizationPayload>;

export type IssueStatus =
  | "backlog"
  | "todo"
  | "in_progress"
  | "in_review"
  | "done"
  | "blocked"
  | "cancelled";
export type IssuePriority = "critical" | "high" | "medium" | "low";
export type IssueOriginKind = "manual" | "automation_execution";
export type IssueReviewDecision = "approve" | "request_changes" | "blocked" | "needs_followup";

export interface IssueListItem {
  id: string;
  orgId: string;
  identifier: string | null;
  title: string;
  status: IssueStatus;
  priority: IssuePriority;
  projectId: string | null;
  goalId: string | null;
  assigneeAgentId: string | null;
  assigneeUserId: string | null;
  originKind: IssueOriginKind;
  originId: string | null;
  updatedAt: string;
}

export interface IssueDetail extends IssueListItem {
  description: string | null;
  reviewerAgentId: string | null;
  reviewerUserId: string | null;
  parentId: string | null;
  issueNumber: number | null;
  requestDepth: number;
  startedAt: string | null;
  completedAt: string | null;
  createdAt: string;
}

export interface IssueComment {
  id: string;
  issueId: string;
  body: string;
  authorAgentId: string | null;
  authorUserId: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface IssueFilters {
  status?: IssueStatus;
  assigneeAgentId?: string;
  projectId?: string;
  goalId?: string;
  originKind?: IssueOriginKind;
  originId?: string;
}

export interface CreateIssuePayload {
  title: string;
  description?: string | null;
  status?: IssueStatus;
  priority?: IssuePriority;
}

export interface UpdateIssuePayload {
  title?: string;
  description?: string | null;
  status?: IssueStatus;
  priority?: IssuePriority;
}

export type ApprovalType =
  | "hire_agent"
  | "approve_ceo_strategy"
  | "budget_override_required"
  | "chat_issue_creation"
  | "chat_operation";
export type ApprovalStatus =
  | "pending"
  | "revision_requested"
  | "approved"
  | "rejected"
  | "cancelled";

export interface ApprovalListItem {
  id: string;
  orgId: string;
  type: ApprovalType;
  status: ApprovalStatus;
  requestedByAgentId: string | null;
  requestedByUserId: string | null;
  createdAt: string;
}

export interface ApprovalDetail extends ApprovalListItem {
  payload: Record<string, unknown>;
  decisionNote: string | null;
  decidedByUserId: string | null;
  decidedAt: string | null;
  updatedAt: string;
}

export interface CreateApprovalPayload {
  type: ApprovalType;
  payload: Record<string, unknown>;
  issueIds?: string[];
}

export interface ResubmitApprovalPayload {
  payload?: Record<string, unknown>;
  issueIds?: string[];
}
