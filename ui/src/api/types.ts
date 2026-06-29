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
  requireBoardApprovalForNewAgents?: boolean;
  defaultChatIssueCreationMode?: string;
  createdAt: string;
  updatedAt: string;
}

export interface CreateOrganizationPayload {
  name: string;
  description?: string | null;
  budgetMonthlyCents?: number;
  brandColor?: string | null;
  requireBoardApprovalForNewAgents?: boolean;
  defaultChatIssueCreationMode?: string;
}

export type UpdateOrganizationPayload = Partial<CreateOrganizationPayload>;

export interface CostEvent {
  id: string;
  orgId: string;
  agentId: string | null;
  projectId: string | null;
  sourceType: string | null;
  sourceId: string | null;
  runtimeType: string | null;
  provider: string | null;
  model: string | null;
  biller: string | null;
  costCents: number;
  costUsd: number | null;
  inputTokens: number | null;
  outputTokens: number | null;
  totalTokens: number | null;
  usage: Record<string, unknown> | null;
  metadata: Record<string, unknown> | null;
  occurredAt: string;
  createdAt: string;
}

export interface CreateCostEventPayload {
  agentId?: string;
  projectId?: string | null;
  sourceType?: string | null;
  sourceId?: string | null;
  runtimeType?: string | null;
  provider?: string | null;
  model?: string | null;
  biller?: string | null;
  costCents?: number;
  costUsd?: number;
  inputTokens?: number | null;
  outputTokens?: number | null;
  totalTokens?: number | null;
  usage?: Record<string, unknown> | null;
  metadata?: Record<string, unknown> | null;
  occurredAt?: string;
}

export interface CostQuery {
  agentId?: string;
  projectId?: string;
  provider?: string;
  biller?: string;
  model?: string;
  startTime?: string;
  endTime?: string;
  limit?: number;
}

export interface CostSummary {
  orgId: string;
  totalCostCents: number;
  eventCount: number;
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
}

export interface CostDimensionRow {
  costCents: number;
  eventCount: number;
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
  agentId?: string | null;
  projectId?: string | null;
  provider?: string;
  biller?: string;
  model?: string;
  runtimeType?: string | null;
}

export interface CostTrendRow {
  bucket: string;
  costCents: number;
  eventCount: number;
}

export interface CostWindowSpend {
  orgId: string;
  costCents: number;
  eventCount: number;
  startTime: string | null;
  endTime: string | null;
}

export interface OrganizationWorkspaceFileEntry {
  name: string;
  path: string;
  isDirectory: boolean;
  displayLabel?: string | null;
  entityType?: string | null;
  agentId?: string | null;
  agentIcon?: string | null;
  agentRole?: string | null;
  workspaceKey?: string | null;
}

export interface OrganizationWorkspaceFileList {
  source: string;
  rootPath: string;
  repoUrl: string | null;
  directoryPath: string;
  rootExists: boolean;
  entries: OrganizationWorkspaceFileEntry[];
  message: string | null;
}

export interface OrganizationWorkspaceFileDetail {
  source: string;
  rootPath: string;
  repoUrl: string | null;
  filePath: string;
  rootExists: boolean;
  content: string | null;
  contentType: string | null;
  previewKind: "text" | "image" | "binary";
  contentPath: string | null;
  message: string | null;
  truncated: boolean;
}

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
  createdByAgentId: string | null;
  createdByUserId: string | null;
  originKind: IssueOriginKind;
  originId: string | null;
  updatedAt: string;
}

export interface StorageHealthConfig {
  provider?: "local_disk" | "minio" | "s3" | string | null;
  bucket?: string | null;
  endpoint?: string | null;
  pathStyle?: boolean | null;
  forcePathStyle?: boolean | null;
}

export interface ServerHealth {
  status: string;
  storage?: StorageHealthConfig | null;
  storageProvider?: string | null;
  storageBucket?: string | null;
  storageEndpoint?: string | null;
  storagePathStyle?: boolean | null;
}

export type PluginStatus =
  | "installed"
  | "ready"
  | "disabled"
  | "error"
  | "upgrade_pending"
  | "uninstalled";

export interface PluginManifest {
  id: string;
  apiVersion: number;
  version: string;
  displayName: string;
  description?: string;
  author?: string;
  categories?: string[];
  capabilities: string[];
  entrypoints: Record<string, string | undefined>;
  instanceConfigSchema?: Record<string, unknown>;
  ui?: {
    slots?: Array<Record<string, unknown>>;
  };
  jobs?: Array<Record<string, unknown>>;
  webhooks?: Array<Record<string, unknown>>;
  tools?: Array<Record<string, unknown>>;
}

export interface PluginSummary {
  id: string;
  pluginKey: string;
  displayName: string;
  version: string;
  status: PluginStatus;
  sourceType: string;
  sourceLocator: string;
  manifest: PluginManifest;
  installedAt: string | null;
  enabledAt: string | null;
  disabledAt: string | null;
  uninstalledAt: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface AvailablePluginItem {
  id: string;
  displayName: string;
  version: string;
  sourcePath: string;
  example: boolean;
  manifest: PluginManifest;
}

export interface PluginCatalogResponse {
  items: AvailablePluginItem[];
  errors: Array<{ id: string; manifestPath: string; message: string }>;
}

export interface PluginJob {
  id: string;
  pluginId: string;
  jobKey: string;
  displayName: string;
  schedule: string | null;
  enabled: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface PluginLog {
  id: string;
  pluginId: string;
  level: string;
  message: string;
  detailsJson: Record<string, unknown> | null;
  createdAt: string;
}

export interface PluginConfig {
  pluginId: string;
  configJson: Record<string, unknown>;
  updatedAt: string | null;
}

export interface PluginConfigTestResult {
  valid: boolean;
  missing?: string[];
  source?: string;
  message?: string;
}

export interface PluginHealth {
  pluginId: string;
  pluginKey: string;
  status: PluginStatus;
  workerRunning: boolean;
  healthy: boolean;
}

export interface PluginDashboard {
  plugin?: PluginSummary;
  counts: {
    jobs: number;
    logs: number;
    uiSlots: number;
    tools: number;
    webhooks: number;
  };
  health: {
    status: PluginStatus;
    workerRunning: boolean;
  };
  recentLogs: PluginLog[];
  jobs: PluginJob[];
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
  cancelledAt?: string | null;
  workProducts?: IssueWorkProduct[];
  documentSummaries?: IssueDocumentSummary[];
  createdAt: string;
}

export interface IssueDocumentSummary {
  id: string;
  orgId: string;
  issueId: string;
  key: string;
  title: string | null;
  format: string;
  latestRevisionId: string | null;
  latestRevisionNumber: number;
  createdByAgentId: string | null;
  createdByUserId: string | null;
  updatedByAgentId: string | null;
  updatedByUserId: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface IssueDocument extends IssueDocumentSummary {
  body: string;
}

export interface IssueDocumentRevision {
  id: string;
  orgId: string;
  documentId: string;
  issueId: string;
  key: string;
  revisionNumber: number;
  body: string;
  changeSummary: string | null;
  createdByAgentId: string | null;
  createdByUserId: string | null;
  createdAt: string;
}

export interface UpsertIssueDocumentPayload {
  title?: string | null;
  format: "markdown";
  body: string;
  changeSummary?: string | null;
  baseRevisionId?: string | null;
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

export interface IssueAttachment {
  id: string;
  orgId: string;
  issueId: string;
  issueCommentId: string | null;
  assetId: string;
  usage: string;
  provider: string;
  objectKey: string;
  contentType: string;
  byteSize: number;
  sha256: string;
  originalFilename: string | null;
  createdAt: string;
  updatedAt: string;
  contentPath?: string | null;
}

export interface IssueFilters {
  status?: IssueStatus;
  assigneeAgentId?: string;
  projectId?: string;
  goalId?: string;
  parentId?: string;
  originKind?: IssueOriginKind;
  originId?: string;
}

export interface ActivityEvent {
  id: string;
  orgId: string;
  actorType?: string;
  actorId?: string;
  action: string;
  entityType: string;
  entityId: string;
  agentId?: string | null;
  runId?: string | null;
  details?: Record<string, unknown> | null;
  summary?: string | null;
  createdAt: string;
}

export interface ActivityQuery {
  agentId?: string;
  userId?: string;
  actorType?: string;
  actorId?: string;
  action?: string;
  entityType?: string;
  entityId?: string;
  runId?: string;
  startTime?: string;
  endTime?: string;
  limit?: number;
  offset?: number;
}

export interface CreateActivityPayload {
  actorId: string;
  action: string;
  entityType: string;
  entityId: string;
  actorType?: "agent" | "user" | "system" | "board";
  agentId?: string | null;
  runId?: string | null;
  details?: Record<string, unknown> | null;
}

export interface CreateIssuePayload {
  title: string;
  description?: string | null;
  status?: IssueStatus;
  priority?: IssuePriority;
  projectId?: string | null;
  goalId?: string | null;
  parentId?: string | null;
  assigneeAgentId?: string | null;
  assigneeUserId?: string | null;
  reviewerAgentId?: string | null;
  reviewerUserId?: string | null;
  createdByAgentId?: string | null;
  createdByUserId?: string | null;
  originKind?: IssueOriginKind;
  originId?: string | null;
  requestDepth?: number;
}

export interface CheckoutIssuePayload {
  agentId: string;
  expectedStatuses: IssueStatus[];
}

export interface UpdateIssuePayload {
  title?: string;
  description?: string | null;
  status?: IssueStatus;
  priority?: IssuePriority;
  projectId?: string | null;
  goalId?: string | null;
  parentId?: string | null;
  assigneeAgentId?: string | null;
  assigneeUserId?: string | null;
  reviewerAgentId?: string | null;
  reviewerUserId?: string | null;
}

export type GoalLevel = "organization" | "team" | "agent" | "task";
export type GoalStatus = "planned" | "active" | "achieved" | "cancelled";

export interface Goal {
  id: string;
  orgId: string;
  title: string;
  description: string | null;
  level: GoalLevel;
  status: GoalStatus;
  parentId: string | null;
  ownerAgentId: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface GoalDependencyPreview {
  id: string;
  title: string;
}

export interface GoalDependencies {
  goalId: string;
  blockers: string[];
  isLastRootOrganizationGoal: boolean;
  counts: {
    childGoals: number;
    linkedProjects: number;
    linkedIssues: number;
    automations: number;
    costEvents: number;
    financeEvents: number;
  };
  previews: {
    childGoals: GoalDependencyPreview[];
    linkedProjects: GoalDependencyPreview[];
    linkedIssues: GoalDependencyPreview[];
    automations: GoalDependencyPreview[];
  };
}

export interface CreateGoalPayload {
  title: string;
  description?: string | null;
  level?: GoalLevel;
  status?: GoalStatus;
  parentId?: string | null;
  ownerAgentId?: string | null;
}

export type UpdateGoalPayload = Partial<CreateGoalPayload>;

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

export interface ApprovalComment {
  id: string;
  approvalId: string;
  body: string;
  authorAgentId: string | null;
  authorUserId: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface CreateApprovalPayload {
  type: ApprovalType;
  payload: Record<string, unknown>;
  requestedByAgentId?: string | null;
  issueIds?: string[];
}

export interface ResolveApprovalPayload {
  decisionNote?: string;
  decidedByUserId?: string;
  payload?: Record<string, unknown>;
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

export interface CreateOrganizationResourcePayload {
  name: string;
  kind: OrganizationResource["kind"];
  locator: string;
  description?: string | null;
  metadata?: Record<string, unknown> | null;
}

export type UpdateOrganizationResourcePayload = Partial<CreateOrganizationResourcePayload>;

export interface OrganizationSkillFileInventoryEntry {
  path: string;
  kind: string;
}

export interface OrganizationSkill {
  id: string;
  orgId: string;
  key: string;
  slug: string;
  name: string;
  description: string | null;
  markdown: string;
  sourceType: string;
  sourceLocator: string | null;
  sourceRef: string | null;
  trustLevel: string;
  compatibility: string;
  fileInventory: OrganizationSkillFileInventoryEntry[];
  metadata: Record<string, unknown> | null;
  createdAt: string;
  updatedAt: string;
}

export interface OrganizationSkillListItem extends OrganizationSkill {
  attachedAgentCount: number;
  editable: boolean;
  editableReason: string | null;
  sourceLabel: string | null;
  sourceBadge: string;
  sourcePath: string | null;
  workspaceEditPath: string | null;
}

export interface OrganizationSkillUsageAgent {
  id: string;
  name: string;
  urlKey: string;
  agentRuntimeType: string;
  desired: boolean;
  actualState: string | null;
}

export interface OrganizationSkillDetail extends OrganizationSkillListItem {
  usedByAgents: OrganizationSkillUsageAgent[];
}

export interface OrganizationSkillFileDetail {
  skillId: string;
  path: string;
  kind: string;
  content: string;
  language: string | null;
  markdown: boolean;
  editable: boolean;
}

export interface OrganizationSkillUpdateStatus {
  supported: boolean;
  reason: string | null;
  trackingRef: string | null;
  currentRef: string | null;
  latestRef: string | null;
  hasUpdate: boolean;
}

export interface OrganizationSkillScanCandidate {
  sourcePath: string;
  slug: string;
  name: string;
  description: string | null;
  sourceRef: string;
  alreadyImported: boolean;
  skillId: string | null;
}

export interface OrganizationSkillScanLocalResult {
  candidates: OrganizationSkillScanCandidate[];
  imported: OrganizationSkill[];
}

export interface CreateOrganizationSkillPayload {
  name: string;
  slug?: string | null;
  description?: string | null;
  markdown?: string | null;
}

export interface ImportOrganizationSkillPayload {
  sourcePath: string;
  slug?: string | null;
  name?: string | null;
  description?: string | null;
  overwrite?: boolean;
}

export interface ScanLocalOrganizationSkillsPayload {
  rootPath: string;
  importDiscovered?: boolean;
  overwrite?: boolean;
}

export interface UpdateOrganizationSkillFilePayload {
  path: string;
  content: string;
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

export interface WorkspaceRuntimeService {
  id: string;
  orgId: string;
  projectId: string | null;
  projectWorkspaceId: string | null;
  executionWorkspaceId: string | null;
  issueId: string | null;
  scopeType: string;
  scopeId: string | null;
  serviceName: string;
  status: string;
  lifecycle: string;
  reuseKey: string | null;
  command: string | null;
  cwd: string | null;
  port: number | null;
  url: string | null;
  provider: string;
  providerRef: string | null;
  ownerAgentId: string | null;
  startedByRunId: string | null;
  lastUsedAt: string;
  startedAt: string;
  stoppedAt: string | null;
  stopPolicy: Record<string, unknown> | null;
  healthStatus: string;
  createdAt: string;
  updatedAt: string;
}

export interface ProjectWorkspace {
  id: string;
  orgId: string;
  projectId: string;
  name: string;
  sourceType: string;
  cwd: string | null;
  repoUrl: string | null;
  repoRef: string | null;
  defaultRef: string | null;
  visibility: string;
  setupCommand: string | null;
  cleanupCommand: string | null;
  remoteProvider: string | null;
  remoteWorkspaceRef: string | null;
  sharedWorkspaceKey: string | null;
  metadata: Record<string, unknown> | null;
  isPrimary: boolean;
  runtimeServices?: WorkspaceRuntimeService[];
  createdAt: string;
  updatedAt: string;
}

export interface CreateProjectWorkspacePayload {
  name: string;
  sourceType?: string;
  cwd?: string | null;
  repoUrl?: string | null;
  repoRef?: string | null;
  defaultRef?: string | null;
  visibility?: string;
  setupCommand?: string | null;
  cleanupCommand?: string | null;
  remoteProvider?: string | null;
  remoteWorkspaceRef?: string | null;
  sharedWorkspaceKey?: string | null;
  metadata?: Record<string, unknown> | null;
  isPrimary?: boolean;
}

export type UpdateProjectWorkspacePayload = Partial<CreateProjectWorkspacePayload>;

export interface ProjectCodebase {
  configured: boolean;
  scope: string;
  workspaceId: string | null;
  repoUrl: string | null;
  repoRef: string | null;
  defaultRef: string | null;
  repoName: string | null;
  localFolder: string | null;
  managedFolder: string;
  effectiveLocalFolder: string;
  origin: string;
}

export interface IssueWorkProduct {
  id: string;
  orgId: string;
  projectId: string | null;
  issueId: string;
  executionWorkspaceId: string | null;
  runtimeServiceId: string | null;
  type: string;
  provider: string;
  externalId: string | null;
  assetId?: string | null;
  contentPath?: string | null;
  contentType?: string | null;
  byteSize?: number | null;
  sha256?: string | null;
  title: string;
  url: string | null;
  status: string;
  reviewState: string;
  isPrimary: boolean;
  healthStatus: string;
  summary: string | null;
  metadata: Record<string, unknown> | null;
  createdByRunId: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface ProjectDetail {
  id: string;
  orgId: string;
  urlKey: string;
  goalId: string | null;
  goalIds?: string[];
  goals?: GoalDependencyPreview[];
  name: string;
  description: string | null;
  status: ProjectStatus;
  leadAgentId: string | null;
  targetDate: string | null;
  color: string | null;
  pauseReason: "manual" | "budget" | "system" | null;
  pausedAt: string | null;
  executionWorkspacePolicy: Record<string, unknown> | null;
  codebase?: ProjectCodebase;
  resources: ProjectResourceAttachment[];
  workspaces?: ProjectWorkspace[];
  primaryWorkspace?: ProjectWorkspace | null;
  archivedAt: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface CreateProjectPayload {
  name: string;
  description?: string | null;
  status?: ProjectStatus;
  goalIds?: string[];
  leadAgentId?: string | null;
  targetDate?: string | null;
  executionWorkspacePolicy?: Record<string, unknown> | null;
  resourceAttachments?: ProjectResourceAttachmentInput[];
  newResources?: CreateProjectInlineResourceInput[];
}

export type UpdateProjectPayload = Partial<CreateProjectPayload>;

export interface CreateProjectInlineResourceInput {
  name: string;
  kind: OrganizationResource["kind"];
  locator: string;
  description?: string | null;
  metadata?: Record<string, unknown> | null;
  role?: ProjectResourceRole;
  note?: string | null;
  sortOrder?: number;
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
  | "openclaw_local"
  | "hermes_local";

export interface Agent {
  id: string;
  orgId: string;
  name: string;
  urlKey: string;
  role: AgentRole;
  title: string | null;
  status: AgentStatus;
  desiredSkills?: string[];
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

export type AgentInboxRelationship = "assignee" | "reviewer" | "mentioned";

export interface AgentInboxItem {
  relationship: AgentInboxRelationship;
  issueId: string;
  identifier: string | null;
  title: string;
  status: IssueStatus;
  priority: IssuePriority;
  checkoutRunId: string | null;
  executionRunId: string | null;
  wakeReason: string | null;
  wakeCommentId: string | null;
  commentPreview: string | null;
  updatedAt: string;
}

export interface AgentConfiguration {
  id?: string;
  agentId?: string;
  orgId?: string;
  name?: string;
  role?: AgentRole;
  title?: string | null;
  status?: AgentStatus;
  reportsTo?: string | null;
  capabilities?: string | null;
  desiredSkills?: string[];
  agentRuntimeType?: AgentRuntimeType;
  agentRuntimeConfig?: Record<string, unknown>;
  runtimeConfig: Record<string, unknown>;
  permissions?: Record<string, boolean>;
  updatedAt?: string;
}

export interface AgentConfigRevision {
  id: string;
  orgId?: string;
  agentId: string;
  createdByAgentId?: string | null;
  createdByUserId?: string | null;
  source?: string;
  rolledBackFromRevisionId?: string | null;
  changedKeys?: string[];
  beforeConfig?: Record<string, unknown>;
  afterConfig?: Record<string, unknown>;
  runtimeConfig?: Record<string, unknown>;
  createdAt: string;
}

export interface CreateAgentPayload {
  name?: string;
  role: AgentRole;
  title?: string | null;
  icon?: string | null;
  reportsTo?: string | null;
  capabilities?: string | null;
  desiredSkills?: string[];
  agentRuntimeType: AgentRuntimeType;
  agentRuntimeConfig: Record<string, unknown>;
  runtimeConfig?: Record<string, unknown>;
  budgetMonthlyCents?: number;
  metadata?: Record<string, unknown> | null;
}

export interface HireAgentPayload extends CreateAgentPayload {
  sourceIssueId?: string | null;
  sourceIssueIds?: string[];
}

export interface AgentHireResult {
  agent: Agent;
  approval: ApprovalDetail | null;
}

export interface UpdateAgentPayload {
  name?: string;
  title?: string | null;
  icon?: string | null;
  role?: AgentRole;
  reportsTo?: string | null;
  capabilities?: string | null;
  desiredSkills?: string[];
  agentRuntimeType?: AgentRuntimeType;
  agentRuntimeConfig?: Record<string, unknown>;
  runtimeConfig?: Record<string, unknown>;
  budgetMonthlyCents?: number;
  replaceAgentRuntimeConfig?: boolean;
  status?: AgentStatus;
  spentMonthlyCents?: number;
  metadata?: Record<string, unknown> | null;
}

export interface RuntimeProvider {
  scope?: RuntimeProviderScope;
  orgId?: string;
  runtimeType?: AgentRuntimeType | null;
  providerId: string;
  name?: string | null;
  protocol?: string | null;
  npmPackage?: string | null;
  baseUrl?: string | null;
  apiKey?: string | null;
  hasApiKey?: boolean;
  config?: Record<string, unknown>;
  enabled?: boolean;
  createdAt?: string;
  updatedAt?: string;
}

export interface RuntimeModel {
  scope?: RuntimeProviderScope;
  orgId?: string;
  runtimeType?: AgentRuntimeType | null;
  providerId: string;
  modelId: string;
  displayName?: string | null;
  metadata?: Record<string, unknown>;
  enabled?: boolean;
  createdAt?: string;
  updatedAt?: string;
}

export type RuntimeProviderScope = "instance" | "global" | "organization";

export interface CreateRuntimeProviderPayload {
  scope?: RuntimeProviderScope;
  providerId: string;
  name?: string | null;
  protocol?: string | null;
  npmPackage?: string | null;
  baseUrl?: string | null;
  apiKey?: string | null;
  config?: Record<string, unknown>;
  enabled?: boolean;
}

export type UpdateRuntimeProviderPayload = Partial<Omit<CreateRuntimeProviderPayload, "providerId">>;

export interface CreateRuntimeModelPayload {
  scope?: RuntimeProviderScope;
  modelId: string;
  displayName?: string | null;
  metadata?: Record<string, unknown>;
  enabled?: boolean;
}

export type UpdateRuntimeModelPayload = Partial<Omit<CreateRuntimeModelPayload, "modelId">>;

export interface AgentRuntimeState {
  agentId: string;
  orgId?: string;
  agentRuntimeType: string;
  sessionId?: string | null;
  stateJson?: Record<string, unknown>;
  sessionDisplayId: string | null;
  lastRunStatus: string | null;
  totalInputTokens: number;
  totalOutputTokens: number;
  totalCachedInputTokens?: number;
  totalCostCents: number;
  lastError: string | null;
  createdAt?: string;
  updatedAt?: string;
  sessionParamsJson?: Record<string, unknown> | null;
}

export interface AgentTaskSession {
  id: string;
  orgId?: string;
  agentId: string;
  agentRuntimeType?: string;
  taskKey: string;
  sessionParamsJson?: Record<string, unknown> | null;
  sessionDisplayId: string | null;
  lastRunId?: string | null;
  lastError?: string | null;
  status: string;
  createdAt: string;
  updatedAt: string;
}

export interface ResetAgentSessionPayload {
  taskKey?: string | null;
}

export interface AgentRuntimeModel {
  id: string;
  label: string;
}

export interface AgentRuntimeEnvironmentCheck {
  id?: string;
  label?: string;
  status?: string;
  message?: string;
  hint?: string | null;
}

export interface AgentRuntimeEnvironmentTestResult {
  agentRuntimeType: string;
  status: string;
  checks: AgentRuntimeEnvironmentCheck[];
}

export interface RuntimeAdapterMetadata {
  type: string;
  capabilities: Record<string, boolean>;
  supportsLocalAgentJwt?: boolean;
  agentConfigurationDoc?: string | null;
}

export interface RuntimeAdapterListItem {
  type: AgentRuntimeType;
  displayName: string;
  metadata: RuntimeAdapterMetadata;
}

export interface ProviderQuotaResult {
  provider?: string;
  source?: string | null;
  ok?: boolean;
  error?: string;
  windows?: Array<Record<string, unknown>>;
}

export interface AgentSkillSnapshot {
  agentRuntimeType?: string;
  supported?: boolean;
  mode?: string;
  desiredSkills: string[];
  entries: Array<Record<string, unknown>>;
  warnings?: string[];
}

export interface PrivateSkillPayload {
  name: string;
  slug?: string | null;
  description?: string | null;
  markdown?: string | null;
}

export interface WakeAgentPayload {
  source?: string;
  triggerDetail?: string;
  reason?: string | null;
  payload?: Record<string, unknown> | null;
  idempotencyKey?: string | null;
  forceFreshSession?: boolean;
}

export interface AgentSkillAnalytics {
  agentId?: string;
  orgId?: string;
  windowDays?: number;
  startDate?: string;
  endDate?: string;
  totalCount?: number;
  totalRunsWithSkills?: number;
  evidenceCounts?: Record<string, number>;
  skills: Array<Record<string, unknown>>;
  days?: Array<Record<string, unknown>>;
}

export interface AgentInstructionsFileSummary {
  content?: string;
  path: string;
  size: number;
  language: string;
  markdown: boolean;
  isEntryFile: boolean;
  editable: boolean;
  deprecated: boolean;
  virtual: boolean;
}

export interface AgentInstructionsFileDetail extends AgentInstructionsFileSummary {
  content: string;
}

export interface AgentInstructionsBundle {
  agentId: string;
  orgId: string;
  mode: string | null;
  rootPath: string | null;
  managedRootPath: string;
  entryFile: string;
  resolvedEntryPath: string | null;
  editable: boolean;
  warnings: string[];
  legacyPromptTemplateActive: boolean;
  legacyBootstrapPromptTemplateActive: boolean;
  files: AgentInstructionsFileSummary[];
}

export interface UpdateAgentInstructionsBundlePayload {
  mode?: "managed" | "external";
  rootPath?: string | null;
  entryFile?: string;
  clearLegacyPromptTemplate?: boolean;
}

export interface AgentInstructionsPathResult {
  agentId: string;
  agentRuntimeType: AgentRuntimeType;
  agentRuntimeConfigKey: string;
  path: string | null;
}

export interface UpdateAgentInstructionsPathPayload {
  path: string | null;
  agentRuntimeConfigKey?: string;
}

export interface UpdateAgentInstructionsFilePayload {
  path: string;
  content: string;
  clearLegacyPromptTemplate?: boolean;
}

export interface AgentMemoryFileEntry {
  name: string;
  path: string;
  isDirectory: boolean;
  size: number | null;
  updatedAt: string | null;
}

export interface AgentMemoryFileList {
  agentId: string;
  orgId: string;
  layer: "memory" | "life";
  rootPath: string;
  directoryPath: string;
  entries: AgentMemoryFileEntry[];
  message: string | null;
}

export interface AgentMemoryFileDetail {
  agentId: string;
  orgId: string;
  layer: "memory" | "life";
  rootPath: string;
  filePath: string;
  content: string;
  size: number;
  updatedAt: string | null;
}

export interface UpdateAgentMemoryFilePayload {
  layer: "memory" | "life";
  path: string;
  content: string;
}

export interface HeartbeatRun {
  id: string;
  runId?: string;
  orgId: string;
  agentId: string;
  issueId?: string | null;
  issueIdentifier?: string | null;
  issueTitle?: string | null;
  projectId?: string | null;
  goalId?: string | null;
  invocationSource: string;
  runPurpose?: "task_execution" | "closeout_followup" | "review" | "heartbeat";
  triggerDetail?: string | null;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled" | "timed_out";
  error?: string | null;
  startedAt?: string | null;
  finishedAt?: string | null;
  wakeupRequestId?: string | null;
  exitCode?: number | null;
  signal?: string | null;
  usageJson?: Record<string, unknown> | null;
  resultJson?: Record<string, unknown> | null;
  summary?: string | null;
  sessionIdBefore?: string | null;
  sessionIdAfter?: string | null;
  stdoutExcerpt?: string | null;
  stderrExcerpt?: string | null;
  errorCode?: string | null;
  externalRunId?: string | null;
  processPid?: number | null;
  processStartedAt?: string | null;
  retryOfRunId?: string | null;
  processLossRetryCount?: number;
  contextSnapshot?: Record<string, unknown> | null;
  createdAt?: string;
  updatedAt?: string;
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

export interface InstanceSchedulerHeartbeatAgent {
  id: string;
  orgId: string;
  organizationName: string;
  organizationIssuePrefix: string;
  agentName: string;
  agentUrlKey: string;
  role: AgentRole;
  title: string | null;
  status: AgentStatus;
  agentRuntimeType: AgentRuntimeType;
  intervalSec: number;
  heartbeatEnabled: boolean;
  schedulerActive: boolean;
  lastHeartbeatAt: string | null;
}

export interface LogReadResult {
  content: string;
  endOffset?: number;
  eof?: boolean;
  nextOffset?: number;
}

export interface WorkspaceOperation {
  id: string;
  orgId: string;
  executionWorkspaceId?: string | null;
  heartbeatRunId?: string | null;
  phase: string;
  command?: string | null;
  cwd?: string | null;
  status: string;
  exitCode?: number | null;
  logStore?: string | null;
  logRef?: string | null;
  logBytes?: number | null;
  logSha256?: string | null;
  logCompressed?: boolean;
  stdoutExcerpt?: string | null;
  stderrExcerpt?: string | null;
  metadata?: Record<string, unknown> | null;
  startedAt?: string | null;
  finishedAt?: string | null;
  createdAt?: string;
  updatedAt?: string;
}

export interface ChatConversation {
  id: string;
  orgId: string;
  title: string;
  summary?: string | null;
  latestReplyPreview?: string | null;
  searchPreview?: string | null;
  status: "active" | "resolved" | "archived";
  preferredAgentId?: string | null;
  routedAgentId?: string | null;
  primaryIssueId?: string | null;
  primaryIssue?: {
    id: string;
    identifier: string | null;
    title: string;
    status: string;
    priority: string;
  } | null;
  issueCreationMode?: "manual_approval" | "auto_create";
  planMode?: boolean;
  lastMessageAt?: string | null;
  lastReadAt?: string | null;
  isPinned?: boolean;
  isUnread?: boolean;
  unreadCount?: number;
  needsAttention?: boolean;
  resolvedAt?: string | null;
  contextLinks?: ChatContextLink[];
  chatRuntime?: {
    sourceType: string;
    sourceLabel: string;
    runtimeAgentId: string | null;
    agentRuntimeType: string | null;
    model: string | null;
    available: boolean;
    error: string | null;
  };
  createdAt?: string;
  updatedAt?: string;
}

export interface ChatMessage {
  id: string;
  orgId?: string;
  conversationId?: string;
  role: "user" | "assistant" | "system";
  kind?: "message" | "ask_user" | "issue_proposal" | "operation_proposal" | "system_event";
  body: string;
  status: "streaming" | "completed" | "stopped" | "failed" | "interrupted";
  structuredPayload?: Record<string, unknown> | null;
  approvalId?: string | null;
  replyingAgentId?: string | null;
  chatTurnId?: string | null;
  turnVariant?: number;
  supersededAt?: string | null;
  attachments?: ChatAttachment[];
  createdAt?: string;
  updatedAt?: string;
}

export interface ChatAttachment {
  id: string;
  orgId: string;
  conversationId: string;
  messageId: string;
  assetId: string;
  provider: string;
  objectKey: string;
  contentType: string;
  byteSize: number;
  sha256: string;
  originalFilename: string | null;
  createdByAgentId: string | null;
  createdByUserId: string | null;
  createdAt: string;
  updatedAt: string;
  contentPath?: string | null;
}

export interface ChatContextLink {
  id: string;
  orgId: string;
  conversationId: string;
  entityType: "issue" | "project" | "agent" | "approval" | "goal";
  entityId: string;
  metadata: Record<string, unknown> | null;
  entity: {
    type: string;
    id: string;
    label: string;
    subtitle: string | null;
    identifier: string | null;
    status: string | null;
    parentId?: string | null;
    href: string;
  } | null;
  createdAt: string;
  updatedAt: string;
}

export interface MessengerThreadSummary {
  threadKey: string;
  kind: "chat" | "issues" | "approvals" | "failed-runs" | "budget-alerts" | "join-requests";
  title: string;
  subtitle: string | null;
  preview: string | null;
  latestActivityAt: string | null;
  lastReadAt: string | null;
  unreadCount: number;
  needsAttention: boolean;
  isPinned: boolean;
  href: string;
}

export interface MessengerThreadBundle {
  summary: MessengerThreadSummary;
  detail: {
    threadKey: string;
    kind: MessengerThreadSummary["kind"];
    title: string;
    subtitle: string | null;
    preview: string | null;
    latestActivityAt: string | null;
    lastReadAt: string | null;
    unreadCount: number;
    needsAttention: boolean;
    isPinned: boolean;
    href: string;
    description: string | null;
    items: Array<Record<string, unknown>>;
  };
}

export interface MessengerChatThreadDetail {
  conversation: ChatConversation;
  messages: ChatMessage[];
}
