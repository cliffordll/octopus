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
  assigneeAgentId?: string | null;
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

export type ProjectStatus = "backlog" | "planned" | "in_progress" | "completed" | "cancelled";
export type ProjectResourceRole =
  | "working_set"
  | "reference"
  | "tracking"
  | "deliverable"
  | "background";

export interface OrganizationResource {
  id: string;
  orgId: string;
  name: string;
  kind: "file" | "directory" | "url" | "connector_object";
  locator: string;
  description: string | null;
  metadata: Record<string, unknown> | null;
  createdAt: string;
  updatedAt: string;
}

export interface ProjectResourceAttachment {
  id: string;
  orgId: string;
  projectId: string;
  resourceId: string;
  role: ProjectResourceRole;
  note: string | null;
  sortOrder: number;
  resource: OrganizationResource;
  createdAt: string;
  updatedAt: string;
}

export interface ProjectDetail {
  id: string;
  orgId: string;
  urlKey: string;
  goalId: string | null;
  name: string;
  description: string | null;
  status: ProjectStatus;
  leadAgentId: string | null;
  targetDate: string | null;
  color: string | null;
  pauseReason: "manual" | "budget" | "system" | null;
  pausedAt: string | null;
  executionWorkspacePolicy: Record<string, unknown> | null;
  resources: ProjectResourceAttachment[];
  archivedAt: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface CreateProjectPayload {
  name: string;
  description?: string | null;
  status?: ProjectStatus;
}

export interface UpdateProjectPayload {
  name?: string;
  description?: string | null;
  status?: ProjectStatus;
}

export interface ProjectResourceAttachmentInput {
  resourceId: string;
  role?: ProjectResourceRole;
  note?: string | null;
  sortOrder?: number;
}

export interface UpdateProjectResourceAttachmentPayload {
  role?: ProjectResourceRole;
  note?: string | null;
  sortOrder?: number;
}

export type AgentStatus =
  | "active"
  | "paused"
  | "idle"
  | "running"
  | "error"
  | "pending_approval"
  | "terminated";
export type AgentRole =
  | "ceo"
  | "cto"
  | "cmo"
  | "cfo"
  | "engineer"
  | "designer"
  | "pm"
  | "qa"
  | "devops"
  | "researcher"
  | "general";
export type AgentRuntimeType =
  | "process"
  | "http"
  | "claude_local"
  | "codex_local"
  | "gemini_local"
  | "opencode_local"
  | "pi_local"
  | "cursor"
  | "openclaw_gateway"
  | "hermes_local";

export interface Agent {
  id: string;
  orgId: string;
  name: string;
  urlKey: string;
  role: AgentRole;
  title: string | null;
  status: AgentStatus;
  agentRuntimeType: AgentRuntimeType;
  agentRuntimeConfig: Record<string, unknown>;
  runtimeConfig?: Record<string, unknown>;
  budgetMonthlyCents: number;
  lastHeartbeatAt: string | null;
  reportsTo?: string | null;
}

export interface AgentDetail extends Agent {
  capabilities?: string | null;
}

export interface CreateAgentPayload {
  name: string;
  role: AgentRole;
  agentRuntimeType: AgentRuntimeType;
  agentRuntimeConfig: Record<string, unknown>;
}

export interface UpdateAgentPayload {
  name?: string;
  title?: string | null;
  role?: AgentRole;
  reportsTo?: string | null;
  capabilities?: string | null;
  agentRuntimeType?: AgentRuntimeType;
  agentRuntimeConfig?: Record<string, unknown>;
  runtimeConfig?: Record<string, unknown>;
  budgetMonthlyCents?: number;
}

export interface AgentRuntimeState {
  agentId: string;
  agentRuntimeType: string;
  sessionDisplayId: string | null;
  lastRunStatus: string | null;
  totalInputTokens: number;
  totalOutputTokens: number;
  totalCostCents: number;
  lastError: string | null;
}

export interface HeartbeatRun {
  id: string;
  orgId: string;
  agentId: string;
  invocationSource: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled" | "timed_out";
  error?: string | null;
  createdAt?: string;
}

export interface HeartbeatRunEvent {
  id: number;
  orgId?: string;
  runId: string;
  agentId: string;
  seq: number;
  eventType: string;
  stream?: string | null;
  level?: string | null;
  message: string | null;
  payload?: Record<string, unknown> | null;
  createdAt: string;
}

export interface ChatConversation {
  id: string;
  orgId: string;
  title: string;
  status: "active" | "resolved" | "archived";
  preferredAgentId?: string | null;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  body: string;
  status: "streaming" | "completed" | "stopped" | "failed" | "interrupted";
}
