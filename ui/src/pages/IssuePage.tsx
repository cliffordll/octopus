import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { useEffect, useRef, useState, type ChangeEvent, type FormEvent, type KeyboardEvent, type ReactNode } from "react";

import { Link, useParams } from "react-router-dom";

import { activityApi } from "../api/activity";

import { accessApi, authApi, type OrganizationHierarchyMember } from "../api/access";

import { AUTH_SESSION_STALE_TIME_MS } from "../auth/sessionCache";

import { organizationMembersWithAgentFallback } from "../utils/organizationMembers";

import { agentsApi } from "../api/agents";

import { goalsApi } from "../api/goals";

import { heartbeatApi } from "../api/heartbeat";

import { issuesApi } from "../api/issues";

import { projectsApi } from "../api/projects";

import type {

  Agent,

  ActivityEvent,

  Goal,

  HeartbeatRun,

  HeartbeatRunEvent,

  IssueComment,

  IssueDetail,



  IssuePriority,

  IssueReviewDecision,

  IssueStatus,

  IssueWorkProduct,

  ExecutionWorkspace,

  LogReadResult,

  ProjectDetail,

  UpdateIssuePayload,

  WorkspaceOperation,

} from "../api/types";

import { Badge } from "../components/Badge";

import { IssuesWorkspace } from "../components/ContextWorkspace";

import { ErrorNotice } from "../components/ErrorNotice";

import { StatusPill } from "../components/StatusPill";

import { formatBytes, formatDateTime, formatMoneyCents, priorityLabel, runErrorMessage, sourceLabel, statusLabel } from "../utils/display";

import { isPassiveFollowupRun, isTaskExecutionRun, runDescriptor, runIssueLabel, runPhaseLabel, runPurposeLabel, runStatusLabel, runTerminalReasonLabel, runWakeReason } from "../utils/runDisplay";

import { writeRecentIssue } from "../utils/recentIssues";

import { formatRuntimeLog } from "../utils/runtimeLog";

const ISSUE_STATUSES: IssueStatus[] = ["backlog", "todo", "in_progress", "in_review", "done", "blocked", "cancelled"];

const HUMAN_EXECUTION_STATUSES = new Set<IssueStatus>(["todo", "in_progress", "done", "blocked"]);

const ISSUE_PRIORITIES: IssuePriority[] = ["critical", "high", "medium", "low"];

const LIVE_RUN_REFETCH_MS = 1000;

const AGENT_REPLY_COLLAPSE_CHARS = 600;

const AGENT_REPLY_COLLAPSE_LINES = 8;

const RUN_SUMMARY_PREVIEW_CHARS = 110;

interface RunStreamCursor {

  lastSeq: number;

  nextOffset: number;

}

function issueDisplayId(issue: IssueDetail): string {

  return issue.identifier ?? issue.id.slice(0, 8);

}

function nullableSelectValue(value: string | null | undefined): string {

  return value ?? "";

}

function agentName(agentId: string | null | undefined, agentsById: Map<string, Agent>): string {

  if (!agentId) return "-";

  return agentsById.get(agentId)?.name ?? agentId;

}

function issueAssigneeLabel(
  issue: Pick<IssueDetail, "assigneeAgentId" | "assigneeUserId">,
  membersByPrincipal: Map<string, OrganizationHierarchyMember>,
  agentsById: Map<string, Agent>,
): string {
  if (issue.assigneeUserId) {
    const member = membersByPrincipal.get(`user:${issue.assigneeUserId}`);
    return `Human · ${member?.displayName ?? issue.assigneeUserId}`;
  }
  if (issue.assigneeAgentId) {
    const member = membersByPrincipal.get(`agent:${issue.assigneeAgentId}`);
    return `Agent · ${member?.displayName ?? agentName(issue.assigneeAgentId, agentsById)}`;
  }
  return "未分配";
}

function agentMentionToken(agent: Agent): string {

  const candidates = [agent.urlKey, agent.name, agent.id];

  for (const candidate of candidates) {

    if (typeof candidate === "string" && /^[A-Za-z0-9][A-Za-z0-9_.-]*$/.test(candidate)) return candidate;

  }

  return agent.id;

}

function mentionQueryAtCursor(value: string, cursor: number): { start: number; query: string } | null {

  const prefix = value.slice(0, cursor);

  const match = /(^|\s)@([A-Za-z0-9_.-]*)$/.exec(prefix);

  if (!match) return null;

  return { start: prefix.length - match[2].length - 1, query: match[2].toLowerCase() };

}

function issueRunStorageKey(orgId: string, issueId: string): string {

  return `octopus:issue-run:${orgId}:${issueId}`;

}

function reviewDecisionBlockReason(issue: IssueDetail): string {

  if (!issue.reviewerAgentId) return "请先设置 Reviewer，当前任务不能评审。";

  if (!["in_review", "blocked"].includes(issue.status)) return "任务进入 in_review 或 blocked 后才能评审。";

  return "";

}

function reviewDecisionLabel(decision: IssueReviewDecision): string {

  switch (decision) {

    case "approve":

      return "通过评审";

    case "request_changes":

      return "请求修改";

    case "needs_followup":

      return "需要人工处理";

    case "blocked":

      return "标记阻塞";

  }

}

function reviewStatusText(issue: IssueDetail, agentsById: Map<string, Agent>): string {

  if (!["in_review", "blocked"].includes(issue.status)) return "当前任务不在评审阶段。";

  if (!issue.reviewerAgentId) return "未设置 Reviewer，无法提交评审结论。";

  const reviewer = agentName(issue.reviewerAgentId, agentsById);

  return issue.status === "blocked"

    ? `任务已阻塞，等待 ${reviewer} 给出 closeout 或后续处理意见。`

    : `任务正在评审中，等待 ${reviewer} 给出 closeout。`;

}

function markReviewBlockReason(issue: IssueDetail): string {

  if (!issue.reviewerAgentId) return "请先设置 Reviewer，当前任务不能标记为待评审。";

  if (issue.status === "in_review") return "当前任务已经是待评审状态。";

  return "";

}

function isLiveRun(status?: string | null): boolean {
  return status === "queued" || status === "running";
}

function isOpenIssueStatus(status?: string | null): boolean {
  return status === "todo" || status === "in_progress" || status === "in_review" || status === "blocked";
}

function isRerunnableRun(status?: string | null): boolean {
  return status === "failed" || status === "timed_out" || status === "cancelled";
}

function isTerminalRun(status?: string | null): boolean {
  return status === "succeeded" || isRerunnableRun(status);
}

function heartbeatRunId(run: HeartbeatRun | null | undefined): string {

  return run?.id || run?.runId || "";

}

function runContextIssueId(run: HeartbeatRun | null | undefined): string | null {

  const value = run?.contextSnapshot?.issueId ?? run?.contextSnapshot?.primaryIssueId;

  return typeof value === "string" && value ? value : null;

}

function runBelongsToIssue(run: HeartbeatRun | null | undefined, issueId: string, listedRunIds: Set<string>): boolean {

  if (!run) return false;

  const runId = heartbeatRunId(run);

  if (runId && listedRunIds.has(runId)) return true;

  return run.issueId === issueId || runContextIssueId(run) === issueId;

}

function runSortTime(run: HeartbeatRun): number {

  const value = run.createdAt ?? run.startedAt ?? run.updatedAt ?? "";

  const time = Date.parse(value);

  return Number.isNaN(time) ? 0 : time;

}

function activeQueueRunsForAgent(runs: HeartbeatRun[], agentId: string | null | undefined): HeartbeatRun[] {

  if (!agentId) return [];

  return runs

    .filter((run) => run.agentId === agentId && isLiveRun(run.status))

    .sort((left, right) => runSortTime(left) - runSortTime(right));

}

function queueRunsAhead(activeRuns: HeartbeatRun[], currentRun: HeartbeatRun | null): number {

  if (!currentRun) return 0;

  const currentRunId = heartbeatRunId(currentRun);

  const currentIndex = activeRuns.findIndex((run) => heartbeatRunId(run) === currentRunId);

  if (currentIndex >= 0) return currentIndex;

  const currentTime = runSortTime(currentRun);

  return activeRuns.filter((run) => runSortTime(run) <= currentTime).length;

}

function queueSourceCounts(runs: HeartbeatRun[]): Array<{ count: number; source: string }> {

  const counts = new Map<string, number>();

  for (const run of runs) counts.set(run.invocationSource, (counts.get(run.invocationSource) ?? 0) + 1);

  return Array.from(counts.entries())

    .map(([source, count]) => ({ count, source }))

    .sort((left, right) => right.count - left.count || sourceLabel(left.source).localeCompare(sourceLabel(right.source)));

}

function latestIssueRun(runs: HeartbeatRun[], currentRun: HeartbeatRun | null, issueId: string): HeartbeatRun | null {

  const merged = new Map<string, HeartbeatRun>();

  const listedRunIds = new Set<string>();

  for (const run of runs) {

    const id = heartbeatRunId(run);

    if (id) {

      listedRunIds.add(id);

      merged.set(id, run);

    }

  }

  if (currentRun && runBelongsToIssue(currentRun, issueId, listedRunIds)) {

    const id = heartbeatRunId(currentRun);

    if (id) {

      const listedRun = merged.get(id);

      merged.set(id, listedRun ? { ...listedRun, ...currentRun } : currentRun);

    }

  }

  const sorted = Array.from(merged.values())

    .filter(isTaskExecutionRun)

    .sort((left, right) => runSortTime(right) - runSortTime(left));

  return sorted[0] ?? null;

}

function latestTerminalRunForIssue(runs: HeartbeatRun[], issueId: string): HeartbeatRun | null {
  const listedRunIds = new Set(runs.map(heartbeatRunId).filter(Boolean));
  const sorted = runs
    .filter((run) => isTerminalRun(run.status) && runBelongsToIssue(run, issueId, listedRunIds))
    .sort((left, right) => runSortTime(right) - runSortTime(left));
  return sorted[0] ?? null;
}

function latestAnyRunForIssue(runs: HeartbeatRun[], issueId: string): HeartbeatRun | null {
  const listedRunIds = new Set(runs.map(heartbeatRunId).filter(Boolean));
  const sorted = runs
    .filter((run) => runBelongsToIssue(run, issueId, listedRunIds))
    .sort((left, right) => runSortTime(right) - runSortTime(left));
  return sorted[0] ?? null;
}

function nextLogOffset(log: LogReadResult): number | null {

  if (typeof log.nextOffset === "number") return log.nextOffset;

  if (typeof log.endOffset === "number") return log.endOffset;

  return null;

}

function AutoScrollPre({

  className,

  content,

}: {

  className: string;

  content: string;

}) {

  const ref = useRef<HTMLPreElement | null>(null);

  useEffect(() => {

    const node = ref.current;

    if (!node) return;

    node.scrollTop = node.scrollHeight;

  }, [content]);

  return <pre className={className} ref={ref}>{content}</pre>;

}

function compactLatestSummary(content: string | null | undefined, maxLength = 180): string {
  const lines = (content ?? "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  const latest = lines.at(-1) ?? "";
  if (latest.length <= maxLength) return latest;
  return `${latest.slice(0, Math.max(0, maxLength - 3))}...`;
}
function streamLogDelta(streamLog: string, persistedLog: string | undefined): string {

  if (!streamLog) return "";

  const persisted = persistedLog ?? "";

  if (!persisted) return streamLog;

  if (persisted.includes(streamLog)) return "";

  if (streamLog.startsWith(persisted)) return streamLog.slice(persisted.length);

  return streamLog;

}

function runElapsedText(run: HeartbeatRun | null): string {

  const startedAt = run?.startedAt ?? run?.createdAt;

  if (!startedAt) return "";

  const startedTime = Date.parse(startedAt);

  if (Number.isNaN(startedTime)) return "";

  const endTime = run?.finishedAt ? Date.parse(run.finishedAt) : Date.now();

  if (Number.isNaN(endTime) || endTime <= startedTime) return "";

  const elapsedSeconds = Math.floor((endTime - startedTime) / 1000);

  if (elapsedSeconds < 60) return `${elapsedSeconds} 秒`;

  const minutes = Math.floor(elapsedSeconds / 60);

  const seconds = elapsedSeconds % 60;

  if (minutes < 60) return seconds ? `${minutes} 分 ${seconds} 秒` : `${minutes} 分`;

  const hours = Math.floor(minutes / 60);

  const restMinutes = minutes % 60;

  return restMinutes ? `${hours} 小时 ${restMinutes} 分` : `${hours} 小时`;

}

function metadataString(metadata: Record<string, unknown> | null | undefined, key: string): string | null {

  const value = metadata?.[key];

  return typeof value === "string" && value.trim() ? value.trim() : null;

}

function pathBasename(value: string | null | undefined): string {

  if (!value?.trim()) return "";

  const normalized = value.replace(/\\/g, "/");

  const parts = normalized.split("/").filter(Boolean);

  return parts.at(-1) ?? value;

}

function workProductDisplayName(product: IssueWorkProduct): string {

  return (

    pathBasename(product.title) ||

    pathBasename(metadataString(product.metadata, "workspacePath")) ||

    pathBasename(product.externalId) ||

    product.id

  );

}

function workspaceModeNotice(mode: string | null | undefined): string {
  if (mode !== "shared_workspace") return "";
  return "共享工作区不会隔离文件；多个任务可以操作同一目录，覆盖由路径约定、diff 审核和 closeout 控制。";
}

function closeoutPolicyLabel(mode: string | null | undefined): string | null {
  if (mode === "child_outputs_are_final") return "子任务产出即完成";
  if (mode === "parent_output_required") return "父任务还需产出";
  return null;
}
type PushCredentials = { username: string; password: string };

function promptForPushCredentials(): PushCredentials | null {
  const username = window.prompt("Git 用户名（留空则使用本机已有凭据）", "");
  if (username === null) return null;
  if (!username.trim()) return null;
  const password = window.prompt("GitHub token/PAT（不会保存，仅用于本次 push）", "");
  if (password === null || !password.trim()) return null;
  return { username: username.trim(), password };
}

function childPrimaryProductTitle(child: { workProducts?: IssueWorkProduct[] }): string {
  const primary = child.workProducts?.find((product) => product.isPrimary) ?? child.workProducts?.[0];
  return primary ? workProductDisplayName(primary) : "";
}

function isParentOwnedPrimary(product: IssueWorkProduct): boolean {
  return product.isPrimary && product.metadata?.parentAggregated !== true;
}
function activityEntityTypeLabel(type: string | null | undefined): string {
  switch (type) {
    case "issue":
      return "任务";
    case "run":
    case "heartbeat_run":
      return "运行";
    case "agent":
      return "智能体";
    case "project":
      return "项目";
    case "goal":
      return "目标";
    case "work_product":
      return "产物";
    case "chat":
    case "conversation":
      return "会话";
    default:
      return "对象";
  }
}
function activityActorTypeLabel(type: string | null | undefined): string {
  switch (type) {
    case "agent":
      return "智能体";
    case "system":
      return "系统";
    case "user":
      return "用户";
    default:
      return "操作者";
  }
}
function pushUniqueIdPart(parts: Array<{ label: string; value: string }>, label: string, value: string | null | undefined) {
  if (!value) return;
  if (parts.some((part) => part.label === label && part.value === value)) return;
  parts.push({ label, value });
}
function activityMetaIdParts(event: ActivityEvent, currentIssueId?: string): Array<{ label: string; value: string }> {
  const parts: Array<{ label: string; value: string }> = [];
  if (!(event.entityType === "issue" && event.entityId === currentIssueId)) pushUniqueIdPart(parts, `${activityEntityTypeLabel(event.entityType)} ID`, event.entityId);
  pushUniqueIdPart(parts, "运行 ID", event.runId);
  const detailRunId = typeof event.details?.runId === "string" ? event.details.runId : null;
  pushUniqueIdPart(parts, "运行 ID", detailRunId);
  const detailAgentId = typeof event.details?.agentId === "string" ? event.details.agentId : null;
  const agentId = detailAgentId ?? event.agentId ?? (event.actorType === "agent" ? event.actorId : null);
  pushUniqueIdPart(parts, "智能体 ID", agentId);
  return parts;
}
function activityActorText(event: ActivityEvent): string {
  if (!event.actorId || event.actorType === "agent") return "";
  return `${activityActorTypeLabel(event.actorType)} ID：${event.actorId}`;
}
function activitySummary(event: ActivityEvent): string {

  if (event.action === "issue.closure_needs_operator_review") return issueCloseoutReviewSummary(event);

  if (event.action === "issue.review_closeout_missing") return issueCloseoutReviewSummary(event);

  if (event.action === "issue.convergence_review_requested") return issueConvergenceReviewSummary(event);
  if (event.action === "issue.closeout_requested") return "父任务已提交完成请求，正在验证声明的任务产物。";
  if (event.action === "issue.child_outputs_closeout_completed") return "子任务产物已通过验证，父任务已自动完成。";
  if (event.action === "issue.child_outputs_closeout_failed") {
    const error = event.details?.error;
    return typeof error === "string" && error.trim() ? error : "子任务产物验证失败，父任务已阻塞。";
  }
  if (event.action === "issue.children_settled") return "所有子任务已进入终态，父任务已被唤醒继续汇总。";

  if (typeof event.summary === "string" && event.summary.trim()) return event.summary;

  const details = event.details ?? {};

  for (const key of ["summary", "message", "title", "note"]) {

    const value = details[key];

    if (typeof value === "string" && value.trim()) return value;

  }

  return `${activityEntityTypeLabel(event.entityType)}记录已更新。`;
}

function activityTitle(event: ActivityEvent): string {

  switch (event.action) {

    case "issue.executed":

      return "执行任务";

    case "issue.status_changed":

      return "状态变更";

    case "issue.created":

      return "创建任务";

    case "issue.updated":

      return "更新任务";

    case "issue.reviewed":

      return "评审任务";

    case "issue.closure_needs_operator_review":

      return "需要人工确认收口";

    case "issue.review_closeout_missing":

      return "缺少评审结论";

    case "issue.convergence_review_requested":

      return "需要收敛评审";

    case "issue.closeout_requested":

      return "正在验证任务产物";

    case "issue.child_outputs_closeout_completed":

      return "父任务自动完成";

    case "issue.child_outputs_closeout_failed":

      return "子任务产物验证失败";

    case "issue.children_settled":

      return "子任务已完成";

    case "heartbeat.invoked":

      return "启动运行";

    case "heartbeat.retried":

      return "重试运行";

    default:

      return statusLabel(event.action);

  }

}

function activityIcon(event: ActivityEvent): string {

  if (event.action === "issue.closure_needs_operator_review") return "!";

  if (event.action === "issue.review_closeout_missing") return "!";

  if (event.action === "issue.convergence_review_requested") return "!";

  if (event.action === "issue.child_outputs_closeout_failed") return "!";

  if (event.action === "issue.closeout_requested") return "V";

  if (event.action === "issue.children_settled") return "S";

  if (event.action.includes("executed") || event.action.includes("heartbeat")) return "R";

  if (event.action.includes("status")) return "S";

  if (event.action.includes("review")) return "V";

  return event.actorType === "agent" ? "A" : "U";

}

function activityTone(event: ActivityEvent): string {

  if (event.action === "issue.closure_needs_operator_review") return "needs-attention";

  if (event.action === "issue.review_closeout_missing") return "needs-attention";

  if (event.action === "issue.convergence_review_requested") return "needs-review";

  if (event.action === "issue.child_outputs_closeout_failed") return "needs-attention";

  if (event.action === "issue.closeout_requested") return "needs-review";

  if (event.action === "issue.children_settled") return "status";

  if (event.action.includes("heartbeat") || event.action === "issue.executed") return "run";

  if (event.action.includes("review")) return "review";

  if (event.action.includes("status") || event.action === "issue.updated") return "status";

  if (event.action === "issue.created") return "created";

  return event.actorType === "agent" ? "agent" : "default";

}

function activityMeta(event: ActivityEvent, currentIssueId: string): string {
  const idParts = activityMetaIdParts(event, currentIssueId).map((part) => `${part.label} ${part.value}`);
  return [...idParts, formatIssueTime(event.createdAt)].join(" · ");
}

function activityNumber(event: ActivityEvent, key: string): number | null {

  const value = event.details?.[key];

  return typeof value === "number" && Number.isFinite(value) ? value : null;

}

function issueCloseoutReviewSummary(event: ActivityEvent): string {

  const attempts = activityNumber(event, "attempts");

  const maxAttempts = activityNumber(event, "maxAttempts");

  const attemptText = attempts !== null && maxAttempts !== null ? ` ${attempts}/${maxAttempts} 次` : "";

  if (event.action === "issue.review_closeout_missing") {

    return `Reviewer 收口已尝试${attemptText}，但仍未提交结构化评审结论。`;

  }

  return `自动收口已尝试${attemptText}，智能体仍未明确完成、阻塞或提交评审。`;

}

function issueConvergenceReviewSummary(event: ActivityEvent): string {

  const attempts = activityNumber(event, "attempts");

  const maxAttempts = activityNumber(event, "maxAttempts");

  const attemptText = attempts !== null && maxAttempts !== null ? ` ${attempts}/${maxAttempts} 次` : "";

  return `自动收口已尝试${attemptText}，已转交 Reviewer 判断下一步。`;

}

function issueCloseoutReviewActivity(
  issue: IssueDetail,
  events: ActivityEvent[] | undefined,
  latestRun: HeartbeatRun | null,
): ActivityEvent | null {
  if (!Array.isArray(events) || !latestRun || !isTerminalRun(latestRun.status)) return null;
  const latestRunId = heartbeatRunId(latestRun);
  if (!latestRunId) return null;
  const matchesLatestRun = (event: ActivityEvent, action: string) =>
    event.action === action && event.entityType === "issue" && event.entityId === issue.id && event.runId === latestRunId;
  if (issue.status === "in_review") {
    return events.find((event) => matchesLatestRun(event, "issue.review_closeout_missing")) ?? null;
  }
  if (issue.status !== "in_progress") return null;
  return events.find((event) => matchesLatestRun(event, "issue.closure_needs_operator_review")) ?? null;
}

function runHasExplicitCloseoutSignal(run: HeartbeatRun | null, events: ActivityEvent[] | undefined, issueId: string): boolean {

  if (!run || !Array.isArray(events)) return false;

  const runId = heartbeatRunId(run);

  return events.some((event) => {

    if (event.entityType !== "issue" || event.entityId !== issueId || event.runId !== runId) return false;

    if (event.action === "issue.comment_added") return true;

    if (event.action !== "issue.updated") return false;

    const status = event.details?.status;

    return typeof status === "string" && ["done", "blocked", "in_review"].includes(status);

  });

}

type IssueTimelineItem =

  | { id: string; item: ActivityEvent; kind: "activity"; timestamp: string }

  | { id: string; item: IssueComment; kind: "comment"; timestamp: string };

function timelineTime(value: string): number {

  const time = Date.parse(value);

  return Number.isNaN(time) ? 0 : time;

}

function issueTimelineItems(

  events: ActivityEvent[] | undefined,

  comments: IssueComment[] | undefined,

): IssueTimelineItem[] {

  const items: IssueTimelineItem[] = [

    ...(Array.isArray(events)

      ? events.map((item) => ({

          id: `activity:${item.id}`,

          item,

          kind: "activity" as const,

          timestamp: item.createdAt,

        }))

      : []),

    ...(Array.isArray(comments)

      ? comments.map((item) => ({

          id: `comment:${item.id}`,

          item,

          kind: "comment" as const,

          timestamp: item.createdAt,

        }))

      : []),

  ];

  return items.sort((left, right) => timelineTime(left.timestamp) - timelineTime(right.timestamp));

}

function workProductPathLabel(product: IssueWorkProduct): string {
  if (product.type === "commit" || product.type === "pull_request") {
    const external = product.externalId ? `#${product.externalId}` : null;
    const provider = product.provider && product.provider !== "octopus" ? product.provider : null;
    return [provider, external].filter(Boolean).join(" ") || product.url || product.title;
  }
  const contentPath = product.contentPath?.includes("/api/assets/") ? null : product.contentPath;
  return contentPath
    ?? metadataString(product.metadata, "workspacePath")
    ?? metadataString(product.metadata, "workspaceBrowserPath")
    ?? product.url
    ?? product.externalId
    ?? product.title;
}

function isDisplayableWorkProduct(product: IssueWorkProduct): boolean {
  return product.type !== "commit";
}

function workProductIcon(type: string): string {
  switch (type) {
    case "pull_request":
      return "P";
    case "report":
      return "R";
    case "preview":
      return "V";
    case "document":
    case "artifact":
    default:
      return "F";
  }
}

function workProductTypeLabel(type: string): string {
  switch (type) {
    case "commit":
      return "代码提交";
    case "pull_request":
      return "Pull Request";
    case "document":
      return "文档";
    case "artifact":
      return "文件产物";
    case "preview":
      return "预览";
    case "report":
      return "报告";
    default:
      return type;
  }
}

function workProductTime(product: IssueWorkProduct): number {
  const time = Date.parse(product.updatedAt || product.createdAt || "");
  return Number.isNaN(time) ? 0 : time;
}

type WorkProductTreeNode = {
  children: Map<string, WorkProductTreeNode>;
  name: string;
  products: IssueWorkProduct[];
};

function newWorkProductTreeNode(name: string): WorkProductTreeNode {
  return { children: new Map(), name, products: [] };
}

function workProductFileName(product: IssueWorkProduct): string {
  if (product.contentPath && !product.contentPath.includes("/api/assets/")) {
    const normalized = product.contentPath.replace(/\\/g, "/");
    return normalized.split("/").filter(Boolean).at(-1) || workProductDisplayName(product);
  }
  return workProductDisplayName(product);
}

function sortWorkProductsForTree(products: IssueWorkProduct[]): IssueWorkProduct[] {
  return [...products].sort((left, right) => {
    const finalDelta = Number(isParentOwnedPrimary(right)) - Number(isParentOwnedPrimary(left));
    const primaryDelta = Number(right.isPrimary) - Number(left.isPrimary);
    return finalDelta || primaryDelta || workProductTime(right) - workProductTime(left);
  });
}

function buildWorkProductTree(products: IssueWorkProduct[]): WorkProductTreeNode {
  const root = newWorkProductTreeNode("root");
  for (const product of sortWorkProductsForTree(products)) {
    const normalized = workProductPathLabel(product).replace(/\\/g, "/").replace(/^\/+/, "");
    const parts = normalized.split("/").map((part) => part.trim()).filter(Boolean);
    const directories = parts.length > 1 ? parts.slice(0, -1) : [workProductTypeLabel(product.type) || "未归档"];
    let node = root;
    for (const directory of directories) {
      const key = directory || "未归档";
      let child = node.children.get(key);
      if (!child) {
        child = newWorkProductTreeNode(key);
        node.children.set(key, child);
      }
      node = child;
    }
    node.products.push(product);
  }
  return root;
}

function countWorkProductTreeProducts(node: WorkProductTreeNode): number {
  let count = node.products.length;
  for (const child of node.children.values()) count += countWorkProductTreeProducts(child);
  return count;
}

type WorkProductTreeEntry = {
  key: string;
  path: string;
  node: WorkProductTreeNode;
};

function compactWorkProductTreeEntry(node: WorkProductTreeNode): WorkProductTreeEntry {
  const names = [node.name];
  let current = node;
  while (current.products.length === 0 && current.children.size === 1) {
    current = [...current.children.values()][0];
    names.push(current.name);
  }
  return { key: names.join("/"), path: names.join(" / "), node: current };
}

function sortedWorkProductTreeEntries(node: WorkProductTreeNode): WorkProductTreeEntry[] {
  return [...node.children.values()]
    .sort((left, right) => left.name.localeCompare(right.name))
    .map(compactWorkProductTreeEntry);
}

function WorkProductRow({
  canDelete,
  deleting,
  issue,
  onDelete,
  product,
}: {
  canDelete: boolean;
  deleting: boolean;
  issue: IssueDetail;
  onDelete: (productId: string) => void;
  product: IssueWorkProduct;
}) {
  const workspaceBrowserPath = metadataString(product.metadata, "workspaceBrowserPath");
  const isParentAggregated = product.metadata?.parentAggregated === true;
  const isFinalDeliverable = isParentOwnedPrimary(product);
  return (
    <article className={`issue-work-product-row${isFinalDeliverable ? " primary" : ""}`}>
      <div className="issue-work-product-row-main">
        <div className="issue-work-product-icon" aria-hidden="true">{workProductIcon(product.type)}</div>
        <div className="issue-work-product-copy">
          <strong>{workProductFileName(product)}</strong>
          <span title={workProductPathLabel(product)}>{workProductPathLabel(product)}</span>
        </div>
      </div>
      <div className="issue-work-product-row-meta">
        <Badge>{workProductTypeLabel(product.type)}</Badge>
        <span className="sr-only">{product.type}</span>
        {product.createdByRunId && <Badge>{product.createdByRunId.slice(0, 8)}</Badge>}
        {(product.isPrimary || isFinalDeliverable) && <Badge>交付物</Badge>}
        {isParentAggregated && <Badge>来自子任务</Badge>}
      </div>
      <div className="issue-work-product-actions">
        {product.contentPath ? (
          <>
            <a className="button secondary small-button" href={product.contentPath}>下载</a>
            <a className="button secondary small-button" href={product.contentPath} target="_blank" rel="noreferrer">预览</a>
          </>
        ) : (
          <span className="download-unavailable">不可下载</span>
        )}
        {workspaceBrowserPath && (
          <Link className="button secondary small-button" to={`/orgs/${issue.orgId}/workspaces?path=${encodeURIComponent(workspaceBrowserPath)}`}>
            工作区
          </Link>
        )}
        {product.url && <a className="button secondary small-button" href={product.url}>打开</a>}
        {canDelete && !isParentAggregated && (
          <button className="danger small-button" disabled={deleting} onClick={() => onDelete(product.id)} type="button">
            删除
          </button>
        )}
      </div>
    </article>
  );
}

function IssueWorkProductTree({
  canDelete,
  deleting,
  issue,
  node,
  onDelete,
}: {
  canDelete: boolean;
  deleting: boolean;
  issue: IssueDetail;
  node: WorkProductTreeNode;
  onDelete: (productId: string) => void;
}) {
  return (
    <div className="issue-work-product-flat-tree">
      {sortedWorkProductTreeEntries(node).map((entry) => {
        const child = entry.node;
        return (
          <section className="issue-work-product-path-group" key={entry.key}>
            <div className="artifact-path-row">
              <span className="project-artifact-folder" aria-hidden="true">/</span>
              <span className="artifact-path-prefix" title={entry.path}>{entry.path}</span>
              <Badge>{countWorkProductTreeProducts(child)} 项</Badge>
            </div>
            {child.products.filter(isDisplayableWorkProduct).length > 0 && (
              <div className="issue-work-product-list compact">
                {sortWorkProductsForTree(child.products.filter(isDisplayableWorkProduct)).map((product) => (
                  <WorkProductRow canDelete={canDelete} deleting={deleting} issue={issue} key={product.id} onDelete={onDelete} product={product} />
                ))}
              </div>
            )}
            {child.children.size > 0 && <IssueWorkProductTree canDelete={canDelete} deleting={deleting} issue={issue} node={child} onDelete={onDelete} />}
          </section>
        );
      })}
    </div>
  );
}
function mergeRunEvents(left: HeartbeatRunEvent[], right: HeartbeatRunEvent[]): HeartbeatRunEvent[] {

  const next = new Map<number, HeartbeatRunEvent>();

  for (const event of left) next.set(event.id, event);

  for (const event of right) next.set(event.id, event);

  return Array.from(next.values()).sort((leftEvent, rightEvent) => leftEvent.seq - rightEvent.seq);

}

function hasJsonObject(value: unknown): value is Record<string, unknown> {

  return Boolean(value && typeof value === "object" && !Array.isArray(value));

}

function formattedJson(value: unknown): string {

  return JSON.stringify(value, null, 2);

}

function runEventDetails(event: HeartbeatRunEvent): Record<string, unknown> {
  return { ...event };
}

function runSummary(run: HeartbeatRun | null): string {

  if (!run) return "暂无运行记录";

  const terminalReason = runTerminalReasonLabel(run);

  if (terminalReason) return terminalReason;

  const error = runErrorMessage(run.error);

  if (run.status === "cancelled" && error === "run cancelled") return isPassiveFollowupRun(run) ? "已停止" : "已取消";

  if (error) return error;

  if (run.summary?.trim()) return run.summary.trim();

  const result = hasJsonObject(run.resultJson) ? run.resultJson : null;

  for (const key of ["summary", "result", "message"]) {

    const value = result?.[key];

    if (typeof value === "string" && value.trim()) return value.trim();

  }

  return statusLabel(run.status);

}

function latestRunBadgeLabel(run: HeartbeatRun | null | undefined): string {

  if (!run) return "";

  return isPassiveFollowupRun(run) ? "补充关闭信号运行" : "最新运行";

}

function latestRunStatusText(run: HeartbeatRun | null | undefined): string {

  if (!run) return "";

  if (run.status === "cancelled") return runTerminalReasonLabel(run) ?? (isPassiveFollowupRun(run) ? "已停止" : "已取消");

  return statusLabel(run.status);

}

function isExpectedCancelledRun(run: HeartbeatRun | null | undefined): boolean {

  return Boolean(
    run &&
    run.status === "cancelled" &&
    (runErrorMessage(run.error) === "run cancelled" || runTerminalReasonLabel(run)),
  );

}

function previewRunSummary(summary: string): string {

  if (summary.length <= RUN_SUMMARY_PREVIEW_CHARS) return summary;

  return `${summary.slice(0, RUN_SUMMARY_PREVIEW_CHARS).trimEnd()}...`;

}

function eventPayloadText(payload: Record<string, unknown> | null | undefined): string {

  if (!payload) return "";

  for (const key of ["text", "content", "message", "delta", "output"]) {

    const value = payload[key];

    if (typeof value === "string" && value.trim()) return value.trim();

  }

  return "";

}

function isLowValueRunEvent(event: HeartbeatRunEvent): boolean {

  const eventType = event.eventType.toLowerCase();

  return (

    eventType.includes("step_start") ||

    eventType.includes("step_finish") ||

    eventType.includes("step.start") ||

    eventType.includes("step.finish") ||

    eventType.includes("step.started") ||

    eventType.includes("step.finished")

  );

}

function isErrorRunEvent(event: HeartbeatRunEvent): boolean {

  const eventType = event.eventType.toLowerCase();

  return (

    event.level === "error" ||

    event.stream === "stderr" ||

    eventType.includes("stderr") ||

    eventType.includes("error") ||

    eventType.includes("failed")

  );

}

function isTextRunEvent(event: HeartbeatRunEvent): boolean {

  const eventType = event.eventType.toLowerCase();

  return (

    event.stream === "stdout" ||

    eventType.includes("text") ||

    eventType.includes("message") ||

    eventType.includes("output") ||

    Boolean(eventPayloadText(event.payload))

  );

}

function runEventLabel(event: HeartbeatRunEvent): string {

  const eventType = event.eventType.toLowerCase();

  if (eventType.includes("issue_review_requested")) return "请求评审";

  if (eventType.includes("issue_review_closeout_missing")) return "缺少评审结论";

  if (eventType.includes("issue_passive_followup")) return "补充关闭信号";

  if (eventType.includes("issue_execution_promoted")) return "延期任务已恢复执行";

  if (isErrorRunEvent(event)) return "错误";

  if (runEventPayloadType(event)) return "Agent 事件";

  if (isTextRunEvent(event)) return "Agent 回复";

  if (eventType.includes("queued")) return "入队";

  if (eventType.includes("started") || eventType.includes("running")) return "开始";

  if (eventType.includes("progress")) return "进度更新";

  if (eventType.includes("adapter") || eventType.includes("runtime")) return "调用 adapter";

  if (eventType.includes("succeeded") || eventType.includes("completed")) return "成功";

  if (eventType.includes("cancel")) return "取消";

  return "Agent 事件";

}

function runEventBody(event: HeartbeatRunEvent): string {

  return eventPayloadText(event.payload) || event.message || "";

}

function jsonTextRecord(value: string | null | undefined): Record<string, unknown> | null {

  if (!value?.trim()) return null;

  for (const line of value.split(/\r?\n/)) {

    const trimmed = line.trim();

    if (!trimmed || !["{", "["].includes(trimmed[0] ?? "")) continue;

    try {

      const parsed = JSON.parse(trimmed);

      if (parsed && !Array.isArray(parsed) && typeof parsed === "object") return parsed as Record<string, unknown>;

    } catch {

      continue;

    }

  }

  return null;

}

function jsonTextType(value: string | null | undefined): string | null {

  const type = jsonTextRecord(value)?.type;

  return typeof type === "string" && type.trim() ? type.trim() : null;

}

function runEventPayloadType(event: HeartbeatRunEvent): string | null {

  const payloadType = event.payload?.type;

  if (typeof payloadType === "string" && payloadType.trim()) return payloadType.trim();

  return jsonTextType(eventPayloadText(event.payload)) ?? jsonTextType(event.message);

}

function runEventMessageJson(event: HeartbeatRunEvent): Record<string, unknown> | null {

  return jsonTextRecord(eventPayloadText(event.payload)) ?? jsonTextRecord(event.message);

}
function runEventSummary(event: HeartbeatRunEvent): string {

  const type = runEventPayloadType(event);

  if (type) return `"type": "${type}"`;

  return event.eventType;

}

function runEventTone(event: HeartbeatRunEvent): string {

  if (isErrorRunEvent(event)) return "tone-error";

  const type = (runEventPayloadType(event) ?? event.eventType).toLowerCase();

  if (type.includes("review") || type.includes("closeout") || type.includes("followup") || type.includes("promoted")) return "tone-review";

  if (type.includes("progress") || type.includes("heartbeat")) return "tone-progress";

  if (type.includes("tool") || type.includes("step") || type.includes("adapter")) return "tone-step";

  if (type.includes("text") || type.includes("output") || type.includes("message") || event.stream === "stdout") return "tone-reply";

  if (type.includes("queued") || type.includes("started") || type.includes("running") || type.includes("succeeded") || type.includes("completed") || type.includes("cancel")) return "tone-lifecycle";

  return "tone-system";

}




function agentReplyPreview(body: string): string {

  const lines = body.split(/\r?\n/);

  const linePreview = lines.slice(0, AGENT_REPLY_COLLAPSE_LINES).join("\n");

  const preview = linePreview.length > AGENT_REPLY_COLLAPSE_CHARS

    ? `${linePreview.slice(0, AGENT_REPLY_COLLAPSE_CHARS).trimEnd()}...`

    : linePreview;

  return lines.length > AGENT_REPLY_COLLAPSE_LINES && !preview.endsWith("...") ? `${preview}\n...` : preview;

}
function parseJsonReply(body: string): unknown | null {

  const trimmed = body.trim();

  if (!trimmed || !["{", "["].includes(trimmed[0] ?? "")) return null;

  try {

    const parsed = JSON.parse(trimmed);

    return parsed && typeof parsed === "object" ? parsed : null;

  } catch {

    return null;

  }

}


function jsonReplySummary(json: unknown): string | null {

  if (!json || Array.isArray(json) || typeof json !== "object") return null;

  const record = json as Record<string, unknown>;

  for (const key of ["summary", "message", "text", "title", "result", "content"]) {

    const value = record[key];

    if (typeof value === "string" && value.trim()) return agentReplyPreview(value);

  }

  return null;

}
function AgentReplyBody({ body }: { body: string }) {

  const json = parseJsonReply(body);

  const [detailsOpen, setDetailsOpen] = useState(false);

  const preview = jsonReplySummary(json) ?? agentReplyPreview(body);

  return (

    <div className="issue-run-agent-reply-block">

      <p className="issue-run-agent-reply issue-run-agent-reply-summary">{preview}</p>

      <details className="issue-run-inline-details issue-run-agent-reply-details" onToggle={(event) => setDetailsOpen(event.currentTarget.open)}>

        <summary>回复内容摘要</summary>

        {detailsOpen && (json !== null ? (

          <pre className="agent-run-json issue-run-agent-reply-json">{formattedJson(json)}</pre>

        ) : (

          <p className="issue-run-agent-reply">{body}</p>

        ))}

      </details>

    </div>

  );

}
function RunEventBody({ event }: { event: HeartbeatRunEvent }) {

  const body = runEventBody(event);

  if (!body) return null;

  if (!isErrorRunEvent(event) && runEventPayloadType(event)) {

    const parsedMessage = runEventMessageJson(event);

    return parsedMessage ? (

      <details className="issue-run-inline-details">

        <summary>消息 JSON</summary>

        <pre className="agent-run-json issue-run-event-payload">{formattedJson(parsedMessage)}</pre>

      </details>

    ) : null;

  }

  if (isTextRunEvent(event) && !isErrorRunEvent(event)) return <AgentReplyBody body={body} />;

  if (!isErrorRunEvent(event)) return <p className="issue-run-execution-item-summary muted">{body}</p>;

  return <pre className="issue-run-event-log error">{body}</pre>;

}

type IssueRunExecutionItemProps = {
  badges?: ReactNode;
  children?: ReactNode;
  className?: string;
  details?: ReactNode;
  meta?: ReactNode;
  summary?: ReactNode;
  title: string;
  variant: "context" | "workspace" | "agent" | "reply" | "error";
};

function IssueRunExecutionItem({ badges, children, className = "", details, meta, summary, title, variant }: IssueRunExecutionItemProps) {
  return (
    <article aria-label={typeof title === "string" ? title : undefined} className={`issue-run-execution-item ${variant} ${className}`.trim()}>
      <div className="issue-run-execution-item-header">
        <span className="issue-run-execution-item-title">
          <strong>{title}</strong>
          {badges}
        </span>
        {meta && <small className="muted issue-run-execution-item-meta">{meta}</small>}
      </div>
      {summary && <p className="issue-run-execution-item-summary muted">{summary}</p>}
      {children}
      {details}
    </article>
  );
}

function formatIssueTime(value: string | null | undefined): string {

  return formatDateTime(value);

}

function numericUsageValue(run: HeartbeatRun, key: string): number {

  const value = run.usageJson?.[key];

  if (typeof value === "number" && Number.isFinite(value)) return value;

  if (typeof value === "string" && value.trim()) {

    const parsed = Number(value);

    if (Number.isFinite(parsed)) return parsed;

  }

  return 0;

}

function runHasReportedUsage(run: HeartbeatRun): boolean {

  const usage = run.usageJson;

  if (!usage || typeof usage !== "object") return false;

  if (["costCents", "costUsd", "inputTokens", "outputTokens", "cachedInputTokens", "totalTokens"].some((key) => numericUsageValue(run, key) > 0)) {

    return true;

  }

  const stdout = typeof run.resultJson?.stdout === "string" ? run.resultJson.stdout : "";

  return stdout.includes('"type":"step_finish"') || stdout.includes('"type":"turn.completed"');

}

function issueRunCostSummary(runs: HeartbeatRun[]): {

  cachedInputTokens: number;

  inputTokens: number;

  outputTokens: number;

  reportedRuns: number;

  totalCostCents: number;

  totalTokens: number;

  unreportedRuns: number;

} {

  return runs.reduce(

    (summary, run) => {

      if (runHasReportedUsage(run)) {

        summary.reportedRuns += 1;

      } else if (run.usageJson || ["succeeded", "failed", "cancelled", "timed_out"].includes(run.status)) {
        summary.unreportedRuns += 1;

      }

      const costCents = numericUsageValue(run, "costCents");

      const costUsd = numericUsageValue(run, "costUsd");

      const inputTokens = numericUsageValue(run, "inputTokens");

      const outputTokens = numericUsageValue(run, "outputTokens");

      const totalTokens = numericUsageValue(run, "totalTokens") || inputTokens + outputTokens;

      summary.totalCostCents += costCents || Math.round(costUsd * 100);

      summary.totalTokens += totalTokens;

      summary.inputTokens += inputTokens;

      summary.outputTokens += outputTokens;

      summary.cachedInputTokens += numericUsageValue(run, "cachedInputTokens");

      return summary;

    },

    { cachedInputTokens: 0, inputTokens: 0, outputTokens: 0, reportedRuns: 0, totalCostCents: 0, totalTokens: 0, unreportedRuns: 0 },

  );

}

function issueStatusOptionDisabledReason(issue: IssueDetail, status: IssueStatus): string {

  if (status === issue.status) return "";

  if (status === "in_review" && !issue.reviewerAgentId) return "请先设置 Reviewer。";

  if (["in_review", "blocked"].includes(issue.status) && ["done", "in_progress", "todo"].includes(status)) {

    return "请通过评审结论推进或退回任务。";

  }

  if (issue.status === "done") return "已完成任务请使用重新打开流程。";

  if (issue.status === "cancelled") return "已取消任务请使用重新打开流程。";

  return "";

}

function IssueIdStrip({ issue }: { issue: IssueDetail }) {
  const items = [
    { label: "任务 ID", value: issue.id },
    { label: "任务阶段", value: statusLabel(issue.status) },
    { label: "优先级", value: priorityLabel(issue.priority) },
    ...(issue.originId ? [{ label: issue.originKind === "manual" ? "来源 ID" : "来源运行 ID", value: issue.originId }] : []),
  ];

  return (
    <dl aria-label="任务概览" className="issue-id-strip">
      {items.map((item) => (
        <div key={item.label}>
          <dt>{item.label}</dt>
          <dd title={item.value}>{item.value}</dd>
        </div>))}
    </dl>
  );
}
function IssuePropertiesPanel({

  agents,

  goals,

  issue,

  executionOnly,

  members,

  isUpdating,

  latestRunStatus,

  onUpdate,

  projects,

}: {

  agents: Agent[];

  goals: Goal[];

  issue: IssueDetail;

  executionOnly: boolean;

  members: OrganizationHierarchyMember[];

  isUpdating: boolean;

  latestRunStatus?: HeartbeatRun["status"];

  onUpdate: (payload: UpdateIssuePayload) => void;

  projects: ProjectDetail[];

}) {

  const agentsById = new Map(agents.map((agent) => [agent.id, agent]));

  const membersByPrincipal = new Map(
    members.map((member) => [`${member.principalType}:${member.principalId}`, member]),
  );

  const assigneeValue = issue.assigneeAgentId
    ? `agent:${issue.assigneeAgentId}`
    : issue.assigneeUserId
      ? `user:${issue.assigneeUserId}`
      : "";

  const reviewerValue = issue.reviewerAgentId ? `agent:${issue.reviewerAgentId}` : "";

  const statusSelectDisabledReason = isLiveRun(latestRunStatus) ? "当前任务已有运行在执行中，运行结束后再调整阶段。" : "";

  const statusSelectDisabled = isUpdating
    || Boolean(statusSelectDisabledReason)
    || (executionOnly && issue.status === "in_review");

  return (

    <section aria-label="任务属性" className="panel issue-properties-card">

      <div className="panel-heading">

        <div>

          <p className="eyebrow">Task Properties</p>

          <h2>属性</h2>

        </div>

      </div>

      <div className="issue-property-list">

        <label className="issue-property-row">

          <span>任务阶段</span>

          <select

            disabled={statusSelectDisabled}

            title={statusSelectDisabledReason || undefined}

            value={issue.status}

            onChange={(event) => onUpdate({ status: event.target.value as IssueStatus })}

          >

            {ISSUE_STATUSES.map((status) => {

              const disabledReason = executionOnly && !HUMAN_EXECUTION_STATUSES.has(status)
                ? "Human 负责人只能开始、继续、完成或阻塞自己的任务。"
                : issueStatusOptionDisabledReason(issue, status);

              return (

                <option disabled={Boolean(disabledReason)} key={status} title={disabledReason || undefined} value={status}>

                  {statusLabel(status)}

                </option>

              );

            })}

          </select>

        </label>

        <label className="issue-property-row">

          <span>优先级</span>

          <select disabled={isUpdating || executionOnly} value={issue.priority} onChange={(event) => onUpdate({ priority: event.target.value as IssuePriority })}>

            {ISSUE_PRIORITIES.map((priority) => <option key={priority} value={priority}>{priorityLabel(priority)}</option>)}

          </select>

        </label>

        <label className="issue-property-row">

          <span>负责人</span>

          <select

            disabled={isUpdating || executionOnly}

            value={assigneeValue}

            onChange={(event) => {

              const [principalType, principalId] = event.target.value.split(":", 2);

              onUpdate({

                assigneeAgentId: principalType === "agent" ? principalId : null,

                assigneeUserId: principalType === "user" ? principalId : null,

                ...(event.target.value && event.target.value === reviewerValue ? { reviewerAgentId: null, reviewerUserId: null } : {}),

              });

            }}

          >

            <option value="">未分配</option>

            {members.filter((member) => member.status === "active").map((member) => (
              <option key={member.id} value={`${member.principalType}:${member.principalId}`}>
                {member.displayName}{member.principalType === "user" ? "（Human）" : ""}
              </option>
            ))}

          </select>

        </label>

        {issue.assigneeAgentId && (

          <div className="issue-property-row issue-property-link-row">

            <span>负责人链接</span>

            <Link to={`/orgs/${issue.orgId}/agents/${issue.assigneeAgentId}`}>{agentName(issue.assigneeAgentId, agentsById)}</Link>

          </div>

        )}

        {issue.assigneeUserId && (

          <div className="issue-property-row issue-property-link-row">

            <span>Human 负责人</span>

            <strong>{membersByPrincipal.get(`user:${issue.assigneeUserId}`)?.displayName ?? issue.assigneeUserId}</strong>

          </div>

        )}

        <label className="issue-property-row">

          <span>Reviewer</span>

          <select

            disabled={isUpdating || executionOnly}

            value={reviewerValue}

            onChange={(event) => {
              const reviewerAgentId = event.target.value.slice(6);
              onUpdate({
                reviewerAgentId: reviewerAgentId || null,
                reviewerUserId: null,
              });
            }}

          >

            <option value="">不设置</option>

            {members.filter((member) => member.status === "active" && member.principalType === "agent").map((member) => {
              const value = `${member.principalType}:${member.principalId}`;
              return (
                <option disabled={value === assigneeValue} key={member.id} value={value}>
                  {member.displayName}
                </option>
              );
            })}

          </select>

        </label>

        {issue.reviewerAgentId && (

          <div className="issue-property-row issue-property-link-row">

            <span>Reviewer 链接</span>

            <Link to={`/orgs/${issue.orgId}/agents/${issue.reviewerAgentId}`}>{agentName(issue.reviewerAgentId, agentsById)}</Link>

          </div>

        )}

        {issue.reviewerUserId && (

          <div className="issue-property-row issue-property-link-row">

            <span>Human Reviewer</span>

            <strong>{membersByPrincipal.get(`user:${issue.reviewerUserId}`)?.displayName ?? issue.reviewerUserId}</strong>

          </div>

        )}

        <label className="issue-property-row">

          <span>项目</span>

          <select

            disabled={isUpdating || executionOnly}

            value={nullableSelectValue(issue.projectId)}

            onChange={(event) => onUpdate({ projectId: event.target.value || null })}

          >

            <option value="">未关联</option>

            {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}

          </select>

        </label>

        <label className="issue-property-row">

          <span>目标</span>

          <select

            disabled={isUpdating || executionOnly}

            value={nullableSelectValue(issue.goalId)}

            onChange={(event) => onUpdate({ goalId: event.target.value || null })}

          >

            <option value="">未关联</option>

            {goals.map((goal) => <option key={goal.id} value={goal.id}>{goal.title}</option>)}

          </select>

        </label>

        <label className="issue-property-row">

          <span>父任务</span>

          <input

            disabled={isUpdating}

            defaultValue={nullableSelectValue(issue.parentId)}

            key={issue.parentId ?? "empty-parent"}

            onBlur={(event) => {

              const nextParentId = event.target.value.trim() || null;

              if (nextParentId !== issue.parentId) onUpdate({ parentId: nextParentId });

            }}

            placeholder="父任务 ID"

          />

        </label>

        <div className="issue-property-row issue-property-disabled">

          <span>标签</span>

          <em>当前 server 未返回标签数据</em>

        </div>

        <hr className="issue-property-divider" />

        <div className="issue-property-row">

          <span>创建者</span>

          {issue.createdByAgentId ? (

            <Link to={`/orgs/${issue.orgId}/agents/${issue.createdByAgentId}`}>{agentName(issue.createdByAgentId, agentsById)}</Link>

          ) : (

            <strong>{issue.createdByUserId ?? "-"}</strong>

          )}

        </div>

        <div className="issue-property-row"><span>编号</span><strong>{issue.issueNumber ?? "-"}</strong></div>

        <div className="issue-property-row"><span>层级</span><strong>{issue.requestDepth}</strong></div>

        <div className="issue-property-row"><span>来源</span><strong>{issue.originKind}</strong></div>

        <div className="issue-property-row"><span>来源 ID</span><strong>{issue.originId ?? "-"}</strong></div>

        <div className="issue-property-row"><span>已启动</span><strong>{issue.startedAt ?? "-"}</strong></div>

        <div className="issue-property-row"><span>已完成</span><strong>{issue.completedAt ?? "-"}</strong></div>

        <div className="issue-property-row"><span>已创建</span><strong>{formatDateTime(issue.createdAt)}</strong></div>

        <div className="issue-property-row"><span>已更新</span><strong>{formatDateTime(issue.updatedAt)}</strong></div>

      </div>

    </section>

  );

}

function IssueCostPanel({ runs }: { runs: HeartbeatRun[] }) {

  const costSummary = issueRunCostSummary(runs);

  const hasReportedUsage = costSummary.reportedRuns > 0;

  const usageValue = (value: number) => hasReportedUsage ? value.toLocaleString() : "未上报";

  const costValue = hasReportedUsage ? formatMoneyCents(costSummary.totalCostCents) : "未上报";

  return (

    <section aria-label="任务成本" className="panel issue-cost-card">

      <div className="panel-heading">

        <div>

          <p className="eyebrow">Usage & Cost</p>

          <h2>成本</h2>

        </div>

      </div>

      <div className="issue-property-list">

        <div className="issue-property-row"><span>成本</span><strong>{costValue}</strong></div>

        <div className="issue-property-row"><span>Total tokens</span><strong>{usageValue(costSummary.totalTokens)}</strong></div>

        <div className="issue-property-row"><span>输入</span><strong>{usageValue(costSummary.inputTokens)}</strong></div>

        <div className="issue-property-row"><span>输出</span><strong>{usageValue(costSummary.outputTokens)}</strong></div>

        <div className="issue-property-row"><span>已缓存</span><strong>{usageValue(costSummary.cachedInputTokens)}</strong></div>

        {!hasReportedUsage && costSummary.unreportedRuns > 0 && (

          <p className="muted">当前运行未上报 token/cost 事件。</p>

        )}

      </div>

    </section>

  );

}

function IssueQueueStatusPanel({
  activeRuns,
  agentsById,
  currentRun,
  issue,
  orgId,
}: {
  activeRuns: HeartbeatRun[];
  agentsById: Map<string, Agent>;
  currentRun: HeartbeatRun | null;
  issue: IssueDetail;
  orgId: string;
}) {
  if (!currentRun || !isLiveRun(currentRun.status) || activeRuns.length === 0 || !issue.assigneeAgentId) return null;

  const aheadCount = queueRunsAhead(activeRuns, currentRun);

  const assigneeName = agentName(issue.assigneeAgentId, agentsById);

  const counts = queueSourceCounts(activeRuns);

  const previewRuns = activeRuns.slice(0, 4);

  function queueRunIssueLabel(run: HeartbeatRun): string {

    if (run.issueId === issue.id) return issue.identifier ?? issue.title ?? issue.id;

    return runIssueLabel(run) ?? "";

  }

  return (

    <section aria-label="运行队列状态" className="issue-queue-status">

      <div className="issue-queue-status-heading">

        <div>

          <p className="eyebrow">QUEUE</p>

          <h2>运行队列</h2>

        </div>

        <StatusPill status={currentRun.status}>{statusLabel(currentRun.status)}</StatusPill>

      </div>

      <p>

        {assigneeName} 正在处理 {activeRuns.length} 个活跃运行；当前任务前面还有 {aheadCount} 个运行。

      </p>

      <div className="issue-queue-source-list" aria-label="队列来源">

        {counts.map((item) => (

          <span key={item.source}>

            {sourceLabel(item.source)}

            <strong>{item.count}</strong>

          </span>
))}

      </div>

      <div className="issue-queue-run-list">

        {previewRuns.map((run) => (

          <article className={heartbeatRunId(run) === heartbeatRunId(currentRun) ? "current" : ""} key={heartbeatRunId(run)}>

            <span>{run.id.slice(0, 8)}</span>

            <Badge>{run.invocationSource}</Badge>

            <small title={runDescriptor(run)}>{runDescriptor(run)}</small>
            {queueRunIssueLabel(run) && <small>{queueRunIssueLabel(run)}</small>}
            <StatusPill status={run.status}>{runStatusLabel(run)}</StatusPill>
          </article>))}
      </div>
      <Link className="button secondary small-button" to={`/orgs/${orgId}/agents/${issue.assigneeAgentId}/runs`}>打开负责人运行页</Link>

    </section>

  );

}

type IssueRunCollapsibleSectionProps = {
  actionExtra?: ReactNode;
  children: ReactNode;
  className?: string;
  collapseLabel?: string;
  expanded: boolean;
  expandLabel: string;
  expandText: string;
  onToggle: () => void;
  summary: ReactNode;
  title: string;
};

function IssueRunCollapsibleSection({
  actionExtra,
  children,
  className = "",
  collapseLabel = "折叠",
  expanded,
  expandLabel,
  expandText,
  onToggle,
  summary,
  title,
}: IssueRunCollapsibleSectionProps) {
  const toggleLabel = expanded ? `折叠${title}` : expandLabel;
  return (
    <section aria-label={title} className={`issue-run-output-block issue-run-primary-block ${className}`.trim()}>
      <div className="issue-run-output-heading">
        <div>
          <h3>{title}</h3>
        </div>
        <div className="issue-run-operation-actions">
          {actionExtra}
          <button aria-label={toggleLabel} className="secondary small-button" type="button" onClick={onToggle}>
            {expanded ? collapseLabel : expandText}
          </button>
        </div>
      </div>
      {expanded ? children : <div className="issue-run-collapsed-summary muted">{summary}</div>}
    </section>
  );
}
function IssueWorkProductsPanel({ embedded = false, issue, latestRunStatus }: { embedded?: boolean; issue: IssueDetail; latestRunStatus?: HeartbeatRun["status"] }) {
  const queryClient = useQueryClient();
  const [workProductsExpanded, setWorkProductsExpanded] = useState(!embedded);
  const workProductsQuery = useQuery({
    queryKey: ["issue-work-products", issue.id],
    queryFn: () => issuesApi.listWorkProducts(issue.id),
    initialData: issue.workProducts ?? [],
  });
  const workProducts = (workProductsQuery.data ?? []).filter(isDisplayableWorkProduct);
  const hasParentFinalDeliverable = workProducts.some(isParentOwnedPrimary);
  const orderedWorkProducts = [...workProducts].sort((left, right) => {
    const primaryDelta = Number(isParentOwnedPrimary(right)) - Number(isParentOwnedPrimary(left));
    return primaryDelta || workProductTime(right) - workProductTime(left);
  });
  const workProductTree = buildWorkProductTree(orderedWorkProducts);
  const latestWorkProduct = orderedWorkProducts[0] ?? null;
  const collapsedWorkProductSummary = latestWorkProduct
    ? `${workProductTypeLabel(latestWorkProduct.type)}：${workProductFileName(latestWorkProduct)}${latestWorkProduct.summary ? ` - ${compactLatestSummary(latestWorkProduct.summary, 120)}` : ""}`
    : "暂无执行产物。";

  useEffect(() => {
    if (embedded && hasParentFinalDeliverable) setWorkProductsExpanded(true);
  }, [embedded, hasParentFinalDeliverable]);

  const deleteWorkProduct = useMutation({
    mutationFn: (workProductId: string) => issuesApi.deleteWorkProduct(workProductId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["issue-work-products", issue.id] });
      void queryClient.invalidateQueries({ queryKey: ["issue", issue.id] });
    },
  });

  const workProductsContent = (
    <>
      {workProductsQuery.error && <ErrorNotice error={workProductsQuery.error} />}
      {workProductsQuery.isLoading && <p className="muted">加载工作产物中...</p>}
      {!workProductsQuery.isLoading && workProducts.length === 0 && (
        <p className="muted">
          {latestRunStatus === "succeeded"
            ? "最新运行已成功，但 server 没有登记受管产物。可能没有生成文件，或文件写到了工作区 / artifacts 之外的路径。"
            : "暂无执行产物。任务执行成功后，server 会把受管工作区或 artifacts 中的产物登记到这里。"}
        </p>
      )}
      {workProducts.length > 0 && (
        <div className="issue-work-product-sections">
          <section className="issue-work-product-section" aria-label="本任务变更与产物">
            <div className="issue-work-product-section-heading">
              <h4>本任务变更与产物</h4>
              <span>{workProducts.length} 项记录</span>
            </div>
            <IssueWorkProductTree
              canDelete={true}
              deleting={deleteWorkProduct.isPending}
              issue={issue}
              node={workProductTree}
              onDelete={(id) => deleteWorkProduct.mutate(id)}
            />
          </section>
        </div>
      )}
      {deleteWorkProduct.error && <ErrorNotice error={deleteWorkProduct.error} />}
    </>
  );

  if (embedded) {
    return (
      <IssueRunCollapsibleSection
        className="issue-run-products-block"
        expanded={workProductsExpanded}
        expandLabel={`展开执行产物 ${workProducts.length}`}
        expandText={`展开 ${workProducts.length}`}
        onToggle={() => setWorkProductsExpanded((value) => !value)}
        summary={collapsedWorkProductSummary}
        title="执行产物"
      >
        {workProductsContent}
      </IssueRunCollapsibleSection>
    );
  }

  return (
    <section aria-label="执行产物" className="issue-section-card">
      <div className="issue-section-heading">
        <div>
          <p className="eyebrow">ARTIFACTS</p>
          <h2>工作产物</h2>
        </div>
      </div>
      {workProductsContent}
    </section>
  );
}
function issueWorkspaceText(value: string | null | undefined): string {

  return value && value.trim() ? value : "未设置";

}

function IssueCodeDeliveryPanel({ issue }: { issue: IssueDetail }) {

  const queryClient = useQueryClient();

  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState("");

  const [previewText, setPreviewText] = useState("");

  const [cleanupDiscardConfirmed, setCleanupDiscardConfirmed] = useState(false);

  const workspaces = useQuery({

    queryKey: ["issue-execution-workspaces", issue.orgId, issue.id],

    queryFn: () => projectsApi.listIssueExecutionWorkspaces(issue.orgId, issue.id),

  });

  const workspaceList = Array.isArray(workspaces.data) ? workspaces.data : [];

  useEffect(() => {

    const preferred = issue.executionWorkspaceId ?? workspaceList[0]?.id ?? "";

    if (!selectedWorkspaceId && preferred) setSelectedWorkspaceId(preferred);

  }, [issue.executionWorkspaceId, selectedWorkspaceId, workspaceList]);

  const selected = workspaceList.find((workspace: ExecutionWorkspace) => workspace.id === selectedWorkspaceId) ?? workspaceList[0];

  const status = useQuery({

    queryKey: ["issue-execution-workspace-status", selected?.id],

    queryFn: () => projectsApi.executionWorkspaceStatus(selected!.id),

    enabled: Boolean(selected?.id),

  });

  const refresh = () => {

    void queryClient.invalidateQueries({ queryKey: ["issue-execution-workspaces", issue.orgId, issue.id] });

    if (selected?.id) void queryClient.invalidateQueries({ queryKey: ["issue-execution-workspace-status", selected.id] });

  };

  const loadDiff = useMutation({

    mutationFn: (workspaceId: string) => projectsApi.executionWorkspaceDiff(workspaceId),

    onSuccess: (payload) => setPreviewText(payload.diff || payload.stat || payload.error || "无 diff"),

  });

  const mergePreview = useMutation({

    mutationFn: (workspaceId: string) => projectsApi.executionWorkspaceMergePreview(workspaceId),

    onSuccess: (payload) => {

      const title = payload.canMerge ? "可以 clean merge" : payload.conflict ? "存在 merge 冲突" : "不能 merge";

      const files = payload.conflictFiles.length > 0 ? `\n冲突文件：${payload.conflictFiles.join(", ")}` : "";

      setPreviewText(`${title}\n目标：${payload.targetRef ?? "未设置"}\n来源：${payload.sourceBranch ?? "未识别"}${files}\n\n${payload.preview || payload.error || "无详细输出"}`);

    },

  });

  const mergeWorkspace = useMutation({

    mutationFn: (workspaceId: string) => projectsApi.mergeExecutionWorkspace(workspaceId),

    onSuccess: (payload) => {

      setPreviewText(`已 merge 到 ${payload.targetRef}\nmerge commit: ${payload.mergedCommit ?? "未识别"}`);

      refresh();

    },

  });

  const preparePr = useMutation({

    mutationFn: (workspaceId: string) => projectsApi.prepareExecutionWorkspacePr(workspaceId),

    onSuccess: (payload) => setPreviewText(`PR 准备信息\n源分支：${payload.sourceBranch}\n目标：${payload.targetRef}\n命令：${payload.command}\n${payload.compareUrl ?? "未识别远端 compare URL"}`),

  });

  const createPr = useMutation({

    mutationFn: (workspaceId: string) => projectsApi.createExecutionWorkspacePr(workspaceId),

    onSuccess: (payload) => {

      setPreviewText(`已创建 PR：${payload.url ?? (payload.stdout || "未返回 URL")}`);

      refresh();

    },

  });

  const commitWorkspace = useMutation({

    mutationFn: ({ workspaceId, message }: { workspaceId: string; message: string }) => projectsApi.commitExecutionWorkspace(workspaceId, message),

    onSuccess: (payload) => {

      setPreviewText(`已提交：${payload.commit ?? "未识别"}\n${payload.stat || "无 diff 摘要"}`);

      refresh();

    },

  });

  const pushWorkspace = useMutation({ mutationFn: ({ workspaceId, credentials }: { workspaceId: string; credentials?: PushCredentials | null }) => projectsApi.pushExecutionWorkspace(workspaceId, credentials), onSuccess: refresh });

  const abandonWorkspace = useMutation({ mutationFn: (workspaceId: string) => projectsApi.abandonExecutionWorkspace(workspaceId), onSuccess: refresh });

  const cleanupWorkspace = useMutation({

    mutationFn: ({ workspaceId, discardDirty }: { workspaceId: string; discardDirty: boolean }) => projectsApi.cleanupExecutionWorkspace(workspaceId, discardDirty),

    onSuccess: () => {

      setPreviewText("");

      setCleanupDiscardConfirmed(false);

      refresh();

    },

  });

  const selectedDirty = Boolean(status.data?.git?.dirty);

  const gitAvailable = Boolean(status.data?.git?.available);

  const canCleanup = Boolean(status.data?.canArchive) || (selectedDirty && cleanupDiscardConfirmed && !status.data?.lease.locked);

  const error = workspaces.error || status.error || loadDiff.error || mergePreview.error || mergeWorkspace.error || preparePr.error || createPr.error || commitWorkspace.error || pushWorkspace.error || abandonWorkspace.error || cleanupWorkspace.error;

  return (

    <section aria-label="代码改动" className="issue-acceptance-subsection issue-code-delivery">

      <div className="issue-acceptance-subheading">

        <div>

          <p className="eyebrow">CODE CHANGES</p>

          <h3>代码改动</h3>

          <p className="muted">检查智能体产生的文件和 Git 改动，并决定如何提交、合并或放弃。</p>

        </div>

        <span className="muted">{workspaceList.length} 个工作区</span>

      </div>

      {error && <ErrorNotice error={error} />}

      {workspaces.isLoading && <p className="muted">加载执行工作区中...</p>}

      {!workspaces.isLoading && workspaceList.length === 0 && <p className="muted">当前任务暂无执行工作区。任务运行后会显示在这里。</p>}

      {workspaceList.length > 1 && (

        <div className="issue-workspace-selector">

          {workspaceList.map((workspace) => (

            <button className={workspace.id === selected?.id ? "active" : "secondary"} key={workspace.id} onClick={() => { setSelectedWorkspaceId(workspace.id); setPreviewText(""); setCleanupDiscardConfirmed(false); }} type="button">

              {workspace.name}

            </button>
))}

        </div>

      )}

      {selected && (

        <article className="issue-execution-workspace-card">

          <div className="project-workspace-name-row">

            <strong>{selected.name}</strong>

            <div className="project-workspace-badges">

              <Badge>{selected.mode}</Badge>

              <Badge>{selected.status}</Badge>

              {selected.branchName && <Badge>{selected.branchName}</Badge>}

            </div>

          </div>

          <span className="execution-workspace-path" title={issueWorkspaceText(selected.cwd)}>{issueWorkspaceText(selected.cwd)}</span>

          <div className="execution-workspace-status-line">

            <span>分支：{status.data?.git?.branch ?? selected.branchName ?? "未识别"}</span>

            <span>目标：{selected.baseRef ?? "未设置"}</span>

            <span>Git：{status.isFetching ? "检查中..." : status.data?.git?.available ? (status.data.git.dirty ? "有未提交改动" : "干净") : status.data?.git?.error ?? "不可用"}</span>

            <span>租约：{status.data?.lease.locked ? `运行中 ${status.data.lease.operationId ?? ""}` : "空闲"}</span>

          </div>

          {workspaceModeNotice(selected.mode) && <p className="issue-action-notice" role="note">{workspaceModeNotice(selected.mode)}</p>}
          <div className="issue-workspace-action-groups">

            <div className="issue-workspace-action-group">

              <span className="issue-workspace-action-label">检查改动</span>

              <div className="project-workspace-actions">

                <button
                  className="secondary small-button"
                  disabled={loadDiff.isPending || !gitAvailable}
                  onClick={() => loadDiff.mutate(selected.id)}
                  title={gitAvailable ? "查看当前工作目录的 Git diff" : "当前工作目录不是 Git 仓库，无法查看 diff"}
                  type="button"
                >
                  查看 diff
                </button>

                <button className="secondary small-button" disabled={mergePreview.isPending || selected.mode === "shared_workspace"} onClick={() => mergePreview.mutate(selected.id)} type="button">检查 merge</button>

              </div>

            </div>

            <div className="issue-workspace-action-group">

              <span className="issue-workspace-action-label">交付改动</span>

              <div className="project-workspace-actions">

                <button className="secondary small-button" disabled={commitWorkspace.isPending || !selectedDirty || Boolean(status.data?.lease.locked)} onClick={() => { const message = window.prompt("提交信息", `Update issue ${issue.identifier ?? issue.id.slice(0, 8)}`); if (message?.trim()) commitWorkspace.mutate({ workspaceId: selected.id, message }); }} type="button">确认提交</button>

                <button className="secondary small-button" disabled={preparePr.isPending || selected.mode === "shared_workspace" || !selected.branchName} onClick={() => preparePr.mutate(selected.id)} type="button">准备 PR</button>

                <button className="secondary small-button" disabled={createPr.isPending || selected.mode === "shared_workspace" || !selected.branchName} onClick={() => createPr.mutate(selected.id)} type="button">创建 PR</button>

                <button className="secondary small-button" disabled={pushWorkspace.isPending || !selected.branchName || selectedDirty} onClick={() => { const credentials = promptForPushCredentials(); pushWorkspace.mutate({ workspaceId: selected.id, credentials }); }} type="button">push 分支</button>

                <button className="secondary small-button" disabled={mergeWorkspace.isPending || selected.mode === "shared_workspace" || Boolean(status.data?.lease.locked)} onClick={() => mergeWorkspace.mutate(selected.id)} type="button">merge 到目标分支</button>

              </div>

            </div>

            <div className="issue-workspace-action-group issue-workspace-action-group-danger">

              <span className="issue-workspace-action-label">放弃或清理</span>

              <div className="project-workspace-actions">

                <button
                  className="danger small-button"
                  disabled={abandonWorkspace.isPending || selected.mode === "shared_workspace" || Boolean(status.data?.lease.locked)}
                  onClick={() => abandonWorkspace.mutate(selected.id)}
                  title={selected.mode === "shared_workspace" ? "共享工作区由多个任务共同使用，不能按单个任务放弃结果" : "将当前独立工作区标记为已放弃，但保留目录"}
                  type="button"
                >
                  放弃结果
                </button>

                <div className="workspace-cleanup-action">

                  {selectedDirty && (

                    <label className="workspace-danger-confirm" title="清理目录会丢弃该运行目录的未提交改动">

                      <input checked={cleanupDiscardConfirmed} onChange={(event) => setCleanupDiscardConfirmed(event.target.checked)} type="checkbox" />

                      <span>丢弃改动</span>

                    </label>

                  )}

                  <button
                    className="danger small-button workspace-cleanup-button"
                    disabled={cleanupWorkspace.isPending || selected.mode === "shared_workspace" || !canCleanup}
                    onClick={() => cleanupWorkspace.mutate({ workspaceId: selected.id, discardDirty: selectedDirty && cleanupDiscardConfirmed })}
                    title={selected.mode === "shared_workspace" ? "共享工作区是项目主目录，不能按单个任务清理" : "归档并清理当前独立执行目录"}
                    type="button"
                  >
                    清理目录
                  </button>

                </div>

              </div>

            </div>

          </div>

          {previewText && <pre className="workspace-diff-preview">{previewText}</pre>}

        </article>

      )}

    </section>

  );

}

function IssueRunsPanel({
  agentsById,
  currentRunId,
  embedded = false,
  expandedRunIds,
  onSelect,
  onToggle,
  renderRunDetails,
  runs,
}: {
  agentsById: Map<string, Agent>;
  currentRunId: string;
  embedded?: boolean;
  expandedRunIds: Set<string>;
  onSelect: (runId: string) => void;
  onToggle: (runId: string) => void;
  renderRunDetails?: (runId: string) => ReactNode;
  runs: HeartbeatRun[];

}) {

  const displayRuns = [...runs].sort((left, right) => runSortTime(left) - runSortTime(right));

  const [expandedSummaryRunIds, setExpandedSummaryRunIds] = useState<Set<string>>(() => new Set());

  const content = runs.length === 0 ? (

    <p className="muted">暂无运行记录。</p>

  ) : (

    <div className="issue-run-record-list">

      {displayRuns.map((run, index) => {

        const runId = heartbeatRunId(run);

        const displayRun = run;

        const source = displayRun.invocationSource?.trim();

        const wakeReason = runWakeReason(displayRun);

        const phaseLabel = runPhaseLabel(displayRun);

        const summary = runSummary(displayRun);

        const summaryExpanded = expandedSummaryRunIds.has(runId);

        const summaryExpandable = summary.length > RUN_SUMMARY_PREVIEW_CHARS;

        const visibleSummary = summaryExpanded || !summaryExpandable ? summary : previewRunSummary(summary);

        const isSelected = runId === currentRunId;

        const isExpanded = expandedRunIds.has(runId);

        const isReviewRun = displayRun.invocationSource === "review";

        const isPassiveFollowupRun =

          displayRun.invocationSource === "automation" &&

          wakeReason === "issue_passive_followup";

        const runTypeClass = isReviewRun

          ? "review"

          : isPassiveFollowupRun

            ? "followup"

            : "task";

        const runTypeLabel = isReviewRun

          ? "Reviewer 评审"

          : isPassiveFollowupRun

            ? "收尾跟进"

            : runPurposeLabel(displayRun);

        return (

          <article className={`issue-run-record-group ${runTypeClass}${isSelected ? " active" : ""}${isExpanded ? " expanded" : ""}`} key={runId}>

            <div className={`issue-run-record-main-row${isSelected ? " active" : ""}`}>

              <button

                className={`issue-run-record${isSelected ? " active" : ""}`}

                onClick={() => onSelect(runId)}

                type="button"

              >

                <span className="issue-run-record-index">第 {index + 1} 次</span>

                <div className="issue-run-record-header">

                  <div className="issue-run-record-title">

                    <strong>{runId}</strong>

                    <span className="issue-run-record-badges">

                      <span className={`badge issue-run-type-badge ${runTypeClass}`}>{runTypeLabel}</span>

                      {source && <Badge>来源 {source}</Badge>}

                      {phaseLabel && <span className="badge" title={wakeReason ? `原始触发原因：${wakeReason}` : undefined}>阶段 {phaseLabel}</span>}

                      <StatusPill status={displayRun.status}>{runStatusLabel(displayRun)}</StatusPill>

                    </span>

                  </div>

                </div>

                <dl className="issue-run-record-meta">

                  <div><dt>执行智能体</dt><dd>{agentName(displayRun.agentId, agentsById)}</dd></div>

                  <div><dt>创建时间</dt><dd>{formatIssueTime(displayRun.createdAt)}</dd></div>

                  <div><dt>开始时间</dt><dd>{formatIssueTime(displayRun.startedAt)}</dd></div>

                </dl>

              </button>

              {summary && (

                <div className={`issue-run-record-summary${summaryExpanded ? " expanded" : ""}`}>

                  <span>输出摘要</span>

                  <p>

                    {summaryExpandable && !summaryExpanded ? (

                      visibleSummary.slice(0, -3)

                    ) : summaryExpandable && summaryExpanded ? (

                      visibleSummary

                    ) : (

                      visibleSummary

                    )}

                  </p>

                  {summaryExpandable && (

                    <button

                      aria-label={summaryExpanded ? `收起运行摘要 ${runId}` : `展开运行摘要 ${runId}`}

                      className="issue-run-summary-more"

                      title={summaryExpanded ? "收起摘要" : "展开摘要"}

                      onClick={() => {

                        setExpandedSummaryRunIds((current) => {

                          const next = new Set(current);

                          if (summaryExpanded) {

                            next.delete(runId);

                          } else {

                            next.add(runId);

                          }

                          return next;

                        });

                      }}

                      type="button"

                    >

                      {summaryExpanded ? "收起" : "展开"}

                    </button>

                  )}

                </div>

              )}

              <button
                aria-label={isExpanded ? `折叠运行 ${runId}` : `展开运行 ${runId}`}
                className="secondary small-button issue-run-record-toggle"
                onClick={() => onToggle(runId)}
                type="button"
              >
                {isExpanded ? "折叠" : "展开"}
              </button>
            </div>
            {isExpanded && renderRunDetails && (
              <div className="issue-run-record-details">

                {renderRunDetails(runId)}

              </div>

            )}

          </article>

        );

      })}

    </div>

  );

  if (embedded) return content;

  return (

    <section aria-label="运行记录" className="issue-section-card">

      <div className="issue-section-heading">

        <div>

          <p className="eyebrow">RUNS</p>

          <h2>运行记录</h2>

        </div>

        <span className="muted">{runs.length} 次运行</span>

      </div>

      {content}

    </section>

  );

}

interface IssueRunPanelData {

  events: UseQueryResult<HeartbeatRunEvent[], Error>;

  operations: UseQueryResult<WorkspaceOperation[], Error>;

  run: UseQueryResult<HeartbeatRun, Error>;

}

function PaginatedLogView({

  emptyText,

  loadMore,

  loadingText,

  log,

  preClassName,

}: {

  emptyText: string;

  loadMore: (offset: number) => Promise<LogReadResult>;

  loadingText: string;

  log: UseQueryResult<LogReadResult, Error>;

  preClassName: string;

}) {

  const [content, setContent] = useState("");

  const [cursor, setCursor] = useState<number | null>(null);

  const [eof, setEof] = useState(true);

  const [loadingMore, setLoadingMore] = useState(false);

  const [loadMoreError, setLoadMoreError] = useState<Error | null>(null);

  useEffect(() => {

    const data = log.data;

    if (!data) {

      setContent("");

      setCursor(null);

      setEof(true);

      setLoadMoreError(null);

      return;

    }

    setContent(data.content ?? "");

    setCursor(data.eof === false ? nextLogOffset(data) : null);

    setEof(data.eof !== false);

    setLoadMoreError(null);

  }, [log.data?.content, log.data?.endOffset, log.data?.eof, log.data?.nextOffset]);

  async function handleLoadMore() {

    if (cursor === null || loadingMore) return;

    setLoadingMore(true);

    setLoadMoreError(null);

    try {

      const next = await loadMore(cursor);

      setContent((current) => `${current}${next.content ?? ""}`);

      setCursor(next.eof === false ? nextLogOffset(next) : null);

      setEof(next.eof !== false);

    } catch (error) {

      setLoadMoreError(error instanceof Error ? error : new Error("日志读取失败"));

    } finally {

      setLoadingMore(false);

    }

  }

  return (

    <>

      {log.isLoading && <p className="muted">{loadingText}</p>}

      {!log.isLoading && !content && <p className="muted">{emptyText}</p>}

      {content && <AutoScrollPre className={preClassName} content={formatRuntimeLog(content)} />}

      {!eof && cursor !== null && (

        <div className="issue-run-operation-actions">

          <button

            className="secondary small-button"

            disabled={loadingMore}

            onClick={handleLoadMore}

            type="button"

          >

            {loadingMore ? "读取中..." : "加载更多日志"}

          </button>

          <span className="muted">已读取到 {formatBytes(cursor)}</span>

        </div>

      )}

      {loadMoreError && <ErrorNotice error={loadMoreError} />}

    </>

  );

}

function workspaceOperationLabel(operation: WorkspaceOperation): string {
  if (operation.metadata?.preflight === true) return "准备任务工作区";
  if (operation.metadata?.adapterExecution === true) return "运行 Agent";
  switch (operation.phase) {
    case "worktree_prepare":
      return "准备代码副本";
    case "workspace_provision":
      return "准备执行工作区";
    case "workspace_teardown":
      return "释放工作区";
    case "worktree_cleanup":
      return "清理代码副本";
    default:
      return operation.phase;
  }
}

function workspaceOperationStageKey(operation: WorkspaceOperation): string | null {
  if (operation.metadata?.preflight === true) return "preflight";
  if (operation.metadata?.adapterExecution === true) return "adapterExecution";
  return null;
}

function workspaceOperationDescription(operation: WorkspaceOperation): string {
  if (operation.metadata?.preflight === true) return "读取项目工作区并生成本次运行要使用的目录、变量和上下文。";
  if (operation.metadata?.adapterExecution === true) return "在准备好的工作区里启动运行时适配器并执行 Agent。";
  switch (operation.phase) {
    case "worktree_prepare":
      return "为本次运行准备隔离的代码目录。";
    case "workspace_provision":
      return "为 agent 分配或复用执行目录，并准备运行所需的工作区。";
    case "workspace_teardown":
      return "运行结束后释放租约、锁或临时资源。";
    case "worktree_cleanup":
      return "清理本次运行产生的临时代码副本。";
    default:
      return operation.command ? "执行了一步工作区相关命令。" : "记录了一步工作区相关操作。";
  }
}

function workspaceOperationTime(operation: WorkspaceOperation): number {
  const value = operation.finishedAt ?? operation.startedAt ?? operation.updatedAt ?? operation.createdAt ?? "";
  const time = Date.parse(value);
  return Number.isNaN(time) ? 0 : time;
}

function runEventTime(event: HeartbeatRunEvent): number {
  const value = event.createdAt ?? "";
  const time = Date.parse(value);
  return Number.isNaN(time) ? 0 : time;
}

function latestExecutionSummary(events: HeartbeatRunEvent[], operations: WorkspaceOperation[]): string {
  const latestEvent = events.at(-1) ?? null;
  const latestOperation = [...operations].sort((left, right) => workspaceOperationTime(right) - workspaceOperationTime(left))[0] ?? null;
  if (latestEvent && (!latestOperation || runEventTime(latestEvent) >= workspaceOperationTime(latestOperation))) {
    const body = compactLatestSummary(runEventBody(latestEvent) || latestEvent.message || "", 120);
    return body ? `${runEventLabel(latestEvent)}：${body}` : runEventLabel(latestEvent);
  }
  if (latestOperation) {
    const body = compactLatestSummary(latestOperation.stderrExcerpt || latestOperation.stdoutExcerpt || latestOperation.command || workspaceOperationDescription(latestOperation), 120);
    return `${workspaceOperationLabel(latestOperation)}：${body || statusLabel(latestOperation.status)}`;
  }
  return "暂无任务执行记录。";
}

function IssueRunOutputPanel({

  cancelling,

  data,

  onCancel,

  onRetry,

  retrying,

  runId,

  streamActive,

  streamError,

  streamLog,

  beforeContent,

  afterKeyEvents,

}: {

  cancelling: boolean;

  data: IssueRunPanelData;

  onCancel: () => void;

  onRetry: (run: HeartbeatRun) => void;

  retrying: boolean;

  runId: string;

  streamActive: boolean;

  streamError: string | null;

  streamLog: string;

  beforeContent?: ReactNode;

  afterKeyEvents?: ReactNode;

}) {

  const [showRunLog, setShowRunLog] = useState(true);

  const [showExecution, setShowExecution] = useState(false);

  const [showAllEvents, setShowAllEvents] = useState(false);

  const run = data.run.data ?? null;

  const suppressExpectedCancellationError = isExpectedCancelledRun(run);

  const events = data.events.data ?? [];

  const operations = data.operations.data ?? [];

  const lowValueEvents = events.filter(isLowValueRunEvent);

  const visibleEvents = showAllEvents ? events : events.filter((event) => !isLowValueRunEvent(event));

  const hasRawOutput = Boolean(run?.stdoutExcerpt || run?.stderrExcerpt || operations.some((operation) => operation.command || operation.stdoutExcerpt || operation.stderrExcerpt));

  const runLog = useQuery({

    queryKey: ["heartbeat-run-log", runId],

    queryFn: () => heartbeatApi.getLog(runId),

    enabled: Boolean(runId),

    refetchInterval: () => isLiveRun(run?.status) ? LIVE_RUN_REFETCH_MS : false,

  });

  const liveRun = isLiveRun(run?.status);

  const wakeReason = runWakeReason(run);

  const isReviewRun = run?.invocationSource === "review";

  const isPassiveFollowupRun =

    run?.invocationSource === "automation" &&

    wakeReason === "issue_passive_followup";

  const canRetryRun =

    Boolean(run) &&

    (isReviewRun || isPassiveFollowupRun) &&

    ["failed", "timed_out", "cancelled"].includes(run.status);

  const retryRunLabel = isReviewRun ? "Reviewer 评审" : "收尾跟进";

  const liveLogDelta = streamLogDelta(streamLog, runLog.data?.content);

  const collapsedRunLogSummary = compactLatestSummary(formatRuntimeLog(liveLogDelta || runLog.data?.content || run?.stdoutExcerpt || run?.stderrExcerpt));

  const collapsedExecutionSummary = latestExecutionSummary(events, operations);

  const lastEvent = events.at(-1) ?? null;

  const hasVisibleRuntimeOutput = Boolean(

    liveLogDelta ||

    runLog.data?.content ||

    run?.stdoutExcerpt ||

    run?.stderrExcerpt ||

    visibleEvents.some((event) => isTextRunEvent(event) && runEventBody(event))

  );

  const processPid = typeof run?.processPid === "number" ? run.processPid : null;

  const silentRuntimeText = liveRun && !hasVisibleRuntimeOutput

    ? `${processPid ? `进程 ${processPid} 已启动` : "运行已启动"}，等待 runtime 输出。`

    : "";
  return (

    <>

      <div aria-label="运行操作" className="issue-run-output-toolbar" role="group">

        <div className="issue-run-actions">

          {liveRun && runElapsedText(run) && <Badge>已运行 {runElapsedText(run)}</Badge>}

          {processPid && <Badge>PID {processPid}</Badge>}

          {streamActive && <Badge>stream 连接中</Badge>}

          {liveRun && !streamActive && <Badge>动态刷新中</Badge>}

          {liveRun && (
            <button
              aria-label={`取消运行 ${runId}`}
              className="secondary small-button"

              disabled={cancelling}

              onClick={onCancel}

              type="button"

            >

              {cancelling ? "取消中" : "取消运行"}
            </button>
          )}
          {run && <Link className="button secondary small-button" to={`/orgs/${run.orgId}/agents/${run.agentId}/runs`}>打开运行页</Link>}
          {run && canRetryRun && (
            <button

              aria-label={`重新执行 ${retryRunLabel} ${runId}`}

              className="secondary small-button"

              disabled={retrying}

              onClick={() => onRetry(run)}

              type="button"

            >

              {retrying ? "提交中" : "重新执行"}

            </button>

          )}

        </div>

      </div>

      <IssueRunCollapsibleSection
        actionExtra={showRunLog && runLog.data?.eof === false ? <Badge>可继续读取</Badge> : null}
        className="issue-run-log-block"
        expanded={showRunLog}
        expandLabel="展开运行日志"
        expandText="展开"
        onToggle={() => setShowRunLog((value) => !value)}
        summary={collapsedRunLogSummary || "暂无运行日志。"}
        title="运行日志"
      >
        <PaginatedLogView
          emptyText="暂无运行日志。"
          loadMore={(offset) => heartbeatApi.getLog(runId, { offset })}
          loadingText="加载运行日志中..."
          log={runLog}
          preClassName="run-excerpt inline"
        />
      </IssueRunCollapsibleSection>

      <IssueRunCollapsibleSection
        className="issue-run-execution-block"
        expanded={showExecution}
        expandLabel={`展开任务执行 ${operations.length + events.length}`}
        expandText={`展开 ${operations.length + events.length}`}
        onToggle={() => setShowExecution((value) => !value)}
        summary={collapsedExecutionSummary}
        title="任务执行"
      >
        <div className="issue-run-execution-content">
          {beforeContent}

          {run?.error && !suppressExpectedCancellationError && <ErrorNotice error={run.error} />}
          {data.events.error && <ErrorNotice error={data.events.error} />}
          {data.operations.error && <ErrorNotice error={data.operations.error} />}
          {runLog.error && <ErrorNotice error={runLog.error} />}
          {streamError && <p className="error-notice">{streamError}</p>}

          {silentRuntimeText && (
            <section className="issue-run-progress-note" aria-label="进度更新提示">
              <strong>{silentRuntimeText}</strong>
              {lastEvent && (
                <span>
                  最近进度：{runEventBody(lastEvent) || lastEvent.message || runEventLabel(lastEvent)}
                  <small>{formatDateTime(lastEvent.createdAt)}</small>
                </span>
              )}
            </section>
          )}

          <div className="issue-run-stage">

            {data.operations.isLoading && <p className="muted">加载执行环境准备中...</p>}
            {!data.operations.isLoading && operations.length === 0 && <p className="muted">暂无执行环境准备记录。</p>}
            {operations.length > 0 && (
              <div className="agent-run-events compact">
                {operations.map((operation) => (
                  <IssueRunExecutionItem
                    badges={(
                      <>
                        <StatusPill status={operation.status}>{statusLabel(operation.status)}</StatusPill>
                        {workspaceOperationStageKey(operation) && <Badge>{workspaceOperationStageKey(operation)}</Badge>}
                        {operation.exitCode !== undefined && operation.exitCode !== null && <Badge>Exit {operation.exitCode}</Badge>}
                      </>
                    )}
                    details={(
                      <details className="issue-run-inline-details">
                        <summary>环境详情</summary>
                        <div className="issue-run-raw-stack">
                          <div><strong>phase</strong><span>{operation.phase}</span></div>
                          {operation.cwd && <div><strong>cwd</strong><span>{operation.cwd}</span></div>}
                          {operation.exitCode !== undefined && operation.exitCode !== null && <div><strong>exit</strong><span>{operation.exitCode}</span></div>}
                          {operation.logBytes !== undefined && operation.logBytes !== null && <div><strong>日志大小</strong><span>{formatBytes(operation.logBytes)}</span></div>}
                          {operation.command && <div><strong>command</strong><span>{operation.command}</span></div>}
                        </div>
                      </details>
                    )}
                    key={operation.id}
                    summary={workspaceOperationDescription(operation)}
                    title={workspaceOperationLabel(operation)}
                    variant="workspace"
                  />
                ))}
              </div>
            )}
          </div>

          <div className="issue-run-stage issue-run-events-flat">
            {data.events.isLoading && <p className="muted">加载事件中...</p>}
            {!data.events.isLoading && events.length === 0 && <p className="muted">暂无 Agent 关键事件。</p>}
            {!data.events.isLoading && events.length > 0 && visibleEvents.length === 0 && (
              <p className="muted">暂无 Agent 关键事件。可显示全部事件查看低价值事件。</p>
            )}
            {lowValueEvents.length > 0 && (
              <div className="issue-run-stage-actions">
                <button aria-label={showAllEvents ? "隐藏低价值事件" : `显示全部事件 ${events.length}`} className="secondary small-button" type="button" onClick={() => setShowAllEvents((value) => !value)}>
                  {showAllEvents ? "隐藏低价值事件" : `显示全部事件 ${events.length}`}
                </button>
              </div>
            )}
            {visibleEvents.length > 0 && (
              <div className="agent-run-events compact">
                {visibleEvents.map((event) => (
                  <IssueRunExecutionItem
                    badges={(
                      <>
                        <Badge>#{event.seq}</Badge>
                        {event.level && <StatusPill status={event.level}>{statusLabel(event.level)}</StatusPill>}
                        {event.stream && <Badge>{event.stream}</Badge>}
                      </>
                    )}
                    details={(
                      <details className="issue-run-inline-details">
                        <summary>事件详情</summary>
                        <pre className="agent-run-json issue-run-event-payload">{formattedJson(runEventDetails(event))}</pre>
                      </details>
                    )}
                    className={runEventTone(event)}
                    key={event.id}
                    meta={formatDateTime(event.createdAt)}
                    summary={runEventSummary(event)}
                    title={runEventLabel(event)}
                    variant={isErrorRunEvent(event) ? "error" : isTextRunEvent(event) ? "reply" : "agent"}
                  >
                    <RunEventBody event={event} />
                  </IssueRunExecutionItem>
                ))}
              </div>
            )}
          </div>
        </div>
      </IssueRunCollapsibleSection>

      {afterKeyEvents}
      {(run || hasRawOutput || liveLogDelta) && (

        <section className="issue-run-output-block issue-run-debug-output">

          <details className="issue-run-inline-details">

            <summary>高级诊断</summary>

            {liveLogDelta && (

              <section className="issue-run-debug-output">

                <h3>实时日志增量</h3>

                <AutoScrollPre className="run-excerpt inline" content={liveLogDelta} />

              </section>

            )}

            {run && (

              <section className="issue-run-debug-output">

                <h3>原始数据</h3>

                <div className="issue-run-raw-stack">

                  {hasJsonObject(run.resultJson) && (

                    <details className="issue-run-inline-details">

                      <summary>resultJson</summary>

                      <pre className="agent-run-json">{formattedJson(run.resultJson)}</pre>

                    </details>

                  )}

                  {hasJsonObject(run.contextSnapshot) && (

                    <details className="issue-run-inline-details">

                      <summary>contextSnapshot</summary>

                      <pre className="agent-run-json">{formattedJson(run.contextSnapshot)}</pre>

                    </details>

                  )}

                  {hasJsonObject(run.usageJson) && (

                    <details className="issue-run-inline-details">

                      <summary>usageJson</summary>

                      <pre className="agent-run-json">{formattedJson(run.usageJson)}</pre>

                    </details>

                  )}

                </div>

              </section>

            )}

            <section className="issue-run-debug-output">

              <h3>原始输出</h3>

              {!hasRawOutput ? (

                <p className="muted">暂无原始输出。</p>

              ) : (

                <div className="issue-run-stream-list">

                  {run?.stdoutExcerpt && (

                    <article className="agent-run-event">

                      <div className="agent-run-event-header"><strong>stdout</strong><Badge>原始输出</Badge></div>

                      <pre className="run-excerpt inline">{run.stdoutExcerpt}</pre>

                    </article>

                  )}

                  {run?.stderrExcerpt && (

                    <article className="agent-run-event error">

                      <div className="agent-run-event-header"><strong>stderr</strong><Badge>错误</Badge></div>

                      <pre className="run-excerpt error inline">{run.stderrExcerpt}</pre>

                    </article>

                  )}

                  {operations.map((operation) => (

                    <article className="agent-run-event" key={operation.id}>

                      <div className="agent-run-event-header"><strong>{operation.phase}</strong><StatusPill status={operation.status}>{statusLabel(operation.status)}</StatusPill></div>

                      {operation.command && <pre className="issue-run-event-log">{operation.command}</pre>}

                      {operation.stderrExcerpt && <pre className="run-excerpt error inline">{operation.stderrExcerpt}</pre>}

                      {operation.stdoutExcerpt && <pre className="run-excerpt inline">{operation.stdoutExcerpt}</pre>}

                    </article>

                  ))}

                </div>

              )}

            </section>

          </details>

        </section>
      )}

    </>

  );

}

function IssueRunDetailsPanel({

  issue,

  issueId,

  latestRunStatus,

  onCancelRun,

  onRetryRun,

  orgId,

  cancellingRunId,

  retryingRunId,

  runId,

}: {

  issue: IssueDetail;

  issueId: string;

  latestRunStatus?: HeartbeatRun["status"];

  onCancelRun: (run: HeartbeatRun) => void;

  onRetryRun: (run: HeartbeatRun) => void;

  orgId: string;

  cancellingRunId?: string;

  retryingRunId?: string;

  runId: string;

}) {

  const queryClient = useQueryClient();

  const streamCursorRef = useRef<RunStreamCursor>({ lastSeq: 0, nextOffset: 0 });


  const [streamActive, setStreamActive] = useState(false);

  const [streamError, setStreamError] = useState<string | null>(null);

  const [streamLog, setStreamLog] = useState("");

  const runDetail = useQuery({

    queryKey: ["heartbeat-run", runId],

    queryFn: () => heartbeatApi.get(runId),

    enabled: Boolean(runId),

    refetchInterval: (query) => isLiveRun(query.state.data?.status) ? LIVE_RUN_REFETCH_MS : false,

  });

  const runEvents = useQuery({

    queryKey: ["heartbeat-run-events", runId],

    queryFn: async () => {

      const fetched = await heartbeatApi.listEvents(runId);

      const cached = queryClient.getQueryData<HeartbeatRunEvent[]>(["heartbeat-run-events", runId]) ?? [];

      return mergeRunEvents(cached, fetched);

    },

    enabled: Boolean(runId),

    refetchInterval: () => isLiveRun(runDetail.data?.status) ? LIVE_RUN_REFETCH_MS : false,

  });

  const runWorkspaceOperations = useQuery({

    queryKey: ["heartbeat-run-workspace-operations", runId],

    queryFn: () => heartbeatApi.listWorkspaceOperations(runId),

    enabled: Boolean(runId),

    refetchInterval: () => isLiveRun(runDetail.data?.status) ? LIVE_RUN_REFETCH_MS : false,

  });

  const heartbeatContext = useQuery({

    queryKey: ["issue-heartbeat-context", issueId],

    queryFn: () => issuesApi.heartbeatContext(issueId),

    enabled: Boolean(issueId),

  });

  useEffect(() => {

    if (!runId || !isLiveRun(runDetail.data?.status)) return;

    const cursor = streamCursorRef.current;

    const controller = new AbortController();

    setStreamActive(true);

    setStreamError(null);

    void heartbeatApi.streamRun(runId, {

      afterSeq: cursor.lastSeq,

      offset: cursor.nextOffset,

      pollMs: LIVE_RUN_REFETCH_MS,

      signal: controller.signal,

      onRun: (run) => {

        queryClient.setQueryData<HeartbeatRun>(["heartbeat-run", runId], (current) => ({

          ...current,

          ...run,

        }));

      },

      onEvent: (event) => {

        cursor.lastSeq = Math.max(cursor.lastSeq, event.seq);

        queryClient.setQueryData<HeartbeatRunEvent[]>(["heartbeat-run-events", runId], (current = []) => mergeRunEvents(current, [event]));

      },

      onLog: (payload) => {

        if (typeof payload.nextOffset === "number") cursor.nextOffset = payload.nextOffset;

        if (payload.content) setStreamLog((current) => `${current}${payload.content}`);

      },

      onFinal: (run) => {

        queryClient.setQueryData<HeartbeatRun>(["heartbeat-run", runId], (current) => ({

          ...current,

          ...run,

        }));

        setStreamActive(false);

        void queryClient.invalidateQueries({ queryKey: ["issue", issueId] });

        void queryClient.invalidateQueries({ queryKey: ["issues", orgId] });

        void queryClient.invalidateQueries({ queryKey: ["issue-heartbeat-runs", issueId] });

        void queryClient.invalidateQueries({ queryKey: ["heartbeat-runs", orgId] });

        void queryClient.invalidateQueries({ queryKey: ["issue-documents", issueId] });

        void queryClient.invalidateQueries({ queryKey: ["issue-work-products", issueId] });

      },

      onError: (error) => {

        setStreamError(error);

        setStreamActive(false);

      },

    }).catch((error: unknown) => {

      if (controller.signal.aborted) return;

      setStreamError(error instanceof Error ? error.message : "Run stream failed");

      void queryClient.invalidateQueries({ queryKey: ["heartbeat-run", runId] });

      void queryClient.invalidateQueries({ queryKey: ["issue-heartbeat-runs", issueId] });

    }).finally(() => {

      if (!controller.signal.aborted) setStreamActive(false);

    });

    return () => {

      controller.abort();

      setStreamActive(false);

    };

  }, [issueId, orgId, queryClient, runDetail.data?.status, runId]);

  const taskContextPanel = (
    <IssueRunExecutionItem
      badges={<Badge>context</Badge>}
      details={heartbeatContext.data ? (
        <details className="issue-run-inline-details">
          <summary>上下文详情</summary>
          <pre className="agent-run-json">{formattedJson(heartbeatContext.data)}</pre>
        </details>
      ) : null}
      summary="Agent 执行前拿到的任务、项目和运行参数。"
      title="任务上下文"
      variant="context"
    >
      {heartbeatContext.isLoading && <p className="muted">加载上下文中...</p>}
      {heartbeatContext.error && <ErrorNotice error={heartbeatContext.error} />}
    </IssueRunExecutionItem>
  );

  return (

    <>

      <IssueRunOutputPanel

        cancelling={cancellingRunId === runId}

        data={{

          events: runEvents,

          operations: runWorkspaceOperations,

          run: runDetail,

        }}

        onCancel={() => {

          if (runDetail.data) onCancelRun(runDetail.data);

        }}

        onRetry={onRetryRun}

        retrying={retryingRunId === runId}

        runId={runId}

        streamActive={streamActive}

        streamError={streamError}

        streamLog={streamLog}

        beforeContent={taskContextPanel}

        afterKeyEvents={<IssueWorkProductsPanel embedded issue={issue} latestRunStatus={latestRunStatus} />}

      />

    </>

  );

}

export function IssuePage() {

  const { orgId = "", issueId = "" } = useParams();

  const [comment, setComment] = useState("");

  const [mentionQuery, setMentionQuery] = useState<{ start: number; query: string } | null>(null);

  const [attachmentFile, setAttachmentFile] = useState<File | null>(null);

  const [attachmentUploadNotice, setAttachmentUploadNotice] = useState("");

  const [attachmentMenuOpen, setAttachmentMenuOpen] = useState(false);

  const [executeNotice, setExecuteNotice] = useState("");

  const [subIssueTitle, setSubIssueTitle] = useState("");

  const [reviewNotice, setReviewNotice] = useState("");

  const [currentRunId, setCurrentRunId] = useState(() => {

    if (!orgId || !issueId) return "";

    return localStorage.getItem(issueRunStorageKey(orgId, issueId)) ?? "";

  });

  const [expandedRunIds, setExpandedRunIds] = useState<Set<string>>(() => new Set());

  const commentTextareaRef = useRef<HTMLTextAreaElement | null>(null);

  const autoExpandedLiveRunRef = useRef("");

  const refreshedTerminalRunRef = useRef("");

  const queryClient = useQueryClient();

  const agents = useQuery({ queryKey: ["agents", orgId], queryFn: () => agentsApi.list(orgId) });

  const hierarchy = useQuery({ queryKey: ["organization-hierarchy", orgId], queryFn: () => accessApi.hierarchy(orgId) });

  const session = useQuery({
    queryKey: ["auth-session"],
    queryFn: authApi.session,
    staleTime: AUTH_SESSION_STALE_TIME_MS,
  });

  const goals = useQuery({ queryKey: ["goals", orgId], queryFn: () => goalsApi.list(orgId) });

  const issue = useQuery({ queryKey: ["issue", issueId], queryFn: () => issuesApi.get(issueId) });

  const projects = useQuery({ queryKey: ["projects", orgId], queryFn: () => projectsApi.list(orgId) });

  const comments = useQuery({

    queryKey: ["comments", issueId],

    queryFn: () => issuesApi.listComments(issueId),

  });

  const issueActivity = useQuery({

    queryKey: ["issue-activity", issueId],

    queryFn: () => activityApi.listIssue(issueId),

    enabled: Boolean(issueId),

  });

  const attachments = useQuery({

    queryKey: ["issue-attachments", issueId],

    queryFn: () => issuesApi.listAttachments(issueId),

  });

  const issueRuns = useQuery({

    queryKey: ["issue-heartbeat-runs", issueId],

    queryFn: () => issuesApi.listRuns(issueId),

    enabled: Boolean(issueId),

    refetchInterval: (query) => query.state.data?.some((run) => isLiveRun(run.status)) ? LIVE_RUN_REFETCH_MS : false,

  });

  const orgHeartbeatRuns = useQuery({

    queryKey: ["heartbeat-runs", orgId],

    queryFn: () => heartbeatApi.list(orgId),

    enabled: Boolean(orgId && issue.data?.assigneeAgentId),

    refetchInterval: (query) => query.state.data?.some((run) => isLiveRun(run.status)) ? LIVE_RUN_REFETCH_MS : false,

  });

  const subIssues = useQuery({
    queryKey: ["issue-children", issueId, "with-work-products"],
    queryFn: () => issuesApi.children(issueId, true),
    enabled: Boolean(issueId),
    refetchInterval: (query) => {
      const children = query.state.data?.children ?? [];
      return issueRuns.data?.some((run) => isLiveRun(run.status)) || children.some((child) => isOpenIssueStatus(child.status))
        ? LIVE_RUN_REFETCH_MS
        : false;
    },
  });
  useEffect(() => {

    if (!orgId || !issueId) return;

    const storedRunId = localStorage.getItem(issueRunStorageKey(orgId, issueId)) ?? "";

    setCurrentRunId(storedRunId);

    setExpandedRunIds(new Set());

    autoExpandedLiveRunRef.current = "";

  }, [orgId, issueId]);

  useEffect(() => {

    if (currentRunId || !issueRuns.data?.length || !orgId || !issueId) return;

    const latestRun = latestIssueRun(issueRuns.data, null, issueId) ?? issueRuns.data[0];

    const latestRunId = heartbeatRunId(latestRun);

    if (!latestRunId) return;

    localStorage.setItem(issueRunStorageKey(orgId, issueId), latestRunId);

    setCurrentRunId(latestRunId);

  }, [currentRunId, issueRuns.data, issueId, orgId]);

  useEffect(() => {

    if (!orgId || !issueId || !issueRuns.data?.length) return;

    const latestRun = latestIssueRun(issueRuns.data, null, issueId);

    const latestRunId = heartbeatRunId(latestRun);

    if (!latestRunId || latestRun?.status !== "running") return;

    if (autoExpandedLiveRunRef.current === latestRunId) return;

    autoExpandedLiveRunRef.current = latestRunId;

    localStorage.setItem(issueRunStorageKey(orgId, issueId), latestRunId);

    setCurrentRunId(latestRunId);

    setExpandedRunIds((current) => {

      if (current.has(latestRunId)) return current;

      const next = new Set(current);

      next.add(latestRunId);

      return next;

    });

  }, [issueId, issueRuns.data, orgId]);

  useEffect(() => {

    if (!reviewNotice) return;

    const timer = window.setTimeout(() => setReviewNotice(""), 3000);

    return () => window.clearTimeout(timer);

  }, [reviewNotice]);

  useEffect(() => {

    if (!executeNotice) return;

    const timer = window.setTimeout(() => setExecuteNotice(""), 3000);

    return () => window.clearTimeout(timer);

  }, [executeNotice]);

  useEffect(() => {

    setReviewNotice("");

  }, [issue.data?.reviewerAgentId, issue.data?.status]);

  const addComment = useMutation({

    mutationFn: () => issuesApi.addComment(issueId, { body: comment.trim() }),

    onSuccess: () => {

      setComment("");

      setMentionQuery(null);

      void queryClient.invalidateQueries({ queryKey: ["comments", issueId] });

    },

  });

  const updateIssue = useMutation({

    mutationFn: (payload: UpdateIssuePayload) => issuesApi.update(issueId, payload),

    onSuccess: (updated) => {

      queryClient.setQueryData(["issue", issueId], updated);

      void queryClient.invalidateQueries({ queryKey: ["issues", orgId] });

    },

  });

  const createSubIssue = useMutation({

    mutationFn: () => {

      if (!issue.data) throw new Error("任务未加载");

      const reviewerAgentId =

        issue.data.reviewerAgentId && issue.data.reviewerAgentId !== issue.data.assigneeAgentId

          ? issue.data.reviewerAgentId

          : undefined;

      return issuesApi.create(orgId, {

        title: subIssueTitle.trim(),

        parentId: issue.data.id,

        projectId: issue.data.projectId,

        goalId: issue.data.goalId,

        assigneeAgentId: issue.data.assigneeAgentId,

        ...(reviewerAgentId ? { reviewerAgentId } : {}),

        priority: issue.data.priority,

        status: "todo",

      });

    },

    onSuccess: () => {

      setSubIssueTitle("");

      void queryClient.invalidateQueries({ queryKey: ["issues", orgId] });

    },

  });

  const executeIssue = useMutation({

    mutationFn: async () => {

      if (!issue.data?.assigneeAgentId) throw new Error("请先分配负责人");

      if (["done", "cancelled"].includes(issue.data.status)) throw new Error("请先重新打开任务，再启动执行");

      if (issue.data.status !== "in_progress") {

        await issuesApi.update(issue.data.id, { status: "in_progress" });

      }

      return issuesApi.execute(issue.data.id);

    },

    onSuccess: async (run) => {

      const runId = heartbeatRunId(run);

      if (runId) {

        setExecuteNotice(isLiveRun(run.status) ? `已连接到运行 ${runId}` : `已创建运行 ${runId}`);

        localStorage.setItem(issueRunStorageKey(orgId, issueId), runId);

        setCurrentRunId(runId);

        setExpandedRunIds(new Set());

        queryClient.setQueryData<HeartbeatRun>(["heartbeat-run", runId], (current) => ({

          ...current,

          ...run,

        }));

        queryClient.setQueryData<HeartbeatRun[]>(["issue-heartbeat-runs", issueId], (current = []) => [

          run,

          ...current.filter((item) => heartbeatRunId(item) !== runId),

        ]);

      } else {

        setExecuteNotice("执行请求已提交，暂未返回新的运行记录，正在刷新任务运行。");

      }

      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["issue", issueId] }),
        queryClient.invalidateQueries({ queryKey: ["issue-activity", issueId] }),
        queryClient.invalidateQueries({ queryKey: ["issues", orgId] }),
        queryClient.invalidateQueries({ queryKey: ["heartbeat-runs", orgId] }),
        queryClient.invalidateQueries({ queryKey: ["heartbeat-run", currentRunId] }),
        queryClient.invalidateQueries({ queryKey: ["heartbeat-run-events", currentRunId] }),
      ]);

    },

  });

  const passiveFollowup = useMutation({

    mutationFn: async () => {

      if (!issue.data) throw new Error("任务未加载");

      return issuesApi.passiveFollowup(issue.data.id);

    },

    onSuccess: async (run) => {

      const runId = heartbeatRunId(run);

      if (runId) {

        setExecuteNotice(`已创建收尾跟进 ${runId}`);

        localStorage.setItem(issueRunStorageKey(orgId, issueId), runId);

        setCurrentRunId(runId);

        queryClient.setQueryData<HeartbeatRun>(["heartbeat-run", runId], (current) => ({

          ...current,

          ...run,

        }));

        queryClient.setQueryData<HeartbeatRun[]>(["issue-heartbeat-runs", issueId], (current = []) => [

          run,

          ...current.filter((item) => heartbeatRunId(item) !== runId),

        ]);

      } else {

        setExecuteNotice("已提交收尾跟进，正在刷新任务运行。");

      }

      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["issue-heartbeat-runs", issueId] }),
        queryClient.invalidateQueries({ queryKey: ["issue-activity", issueId] }),
        queryClient.invalidateQueries({ queryKey: ["heartbeat-runs", orgId] }),
        queryClient.invalidateQueries({ queryKey: ["issue", issueId] }),
      ]);
    },

  });

  const retryRun = useMutation({

    mutationFn: (run: HeartbeatRun) => heartbeatApi.retry(heartbeatRunId(run)),

    onSuccess: (run) => {

      const retriedRunId = heartbeatRunId(run);

      if (retriedRunId) {

        localStorage.setItem(issueRunStorageKey(orgId, issueId), retriedRunId);

        setCurrentRunId(retriedRunId);

        setExpandedRunIds((current) => new Set(current).add(retriedRunId));

        queryClient.setQueryData<HeartbeatRun[]>(["issue-heartbeat-runs", issueId], (current = []) => [

          run,

          ...current.filter((item) => heartbeatRunId(item) !== retriedRunId),

        ]);

      }

      void queryClient.invalidateQueries({ queryKey: ["issue-heartbeat-runs", issueId] });

      void queryClient.invalidateQueries({ queryKey: ["heartbeat-runs", orgId] });

    },

  });

  const cancelIssueRun = useMutation({
    mutationFn: (run: HeartbeatRun) => heartbeatApi.cancel(heartbeatRunId(run)),
    onSuccess: (run) => {
      const cancelledRunId = heartbeatRunId(run);
      queryClient.setQueryData(["heartbeat-run", cancelledRunId], run);
      queryClient.setQueryData<HeartbeatRun[]>(["issue-heartbeat-runs", issueId], (current = []) =>
        current.map((item) => heartbeatRunId(item) === cancelledRunId ? run : item),
      );
      queryClient.setQueryData<HeartbeatRun[]>(["heartbeat-runs", orgId], (current = []) =>
        current.map((item) => heartbeatRunId(item) === cancelledRunId ? run : item),
      );
      void queryClient.invalidateQueries({ queryKey: ["issue-heartbeat-runs", issueId] });
      void queryClient.invalidateQueries({ queryKey: ["heartbeat-runs", orgId] });
      void queryClient.invalidateQueries({ queryKey: ["issue", issueId] });
      void queryClient.invalidateQueries({ queryKey: ["issues", orgId] });
    },
  });
  const checkoutIssue = useMutation({

    mutationFn: () => {

      if (!issue.data?.assigneeAgentId) throw new Error("请先分配负责人");

      return issuesApi.checkout(issue.data.id, {

        agentId: issue.data.assigneeAgentId,

        expectedStatuses: [issue.data.status],

      });

    },

    onSuccess: (updated) => {

      queryClient.setQueryData(["issue", issueId], updated);

      void queryClient.invalidateQueries({ queryKey: ["issues", orgId] });

    },

  });

  useEffect(() => {

    const latestRun = latestTerminalRunForIssue(issueRuns.data ?? [], issueId);

    const latestRunId = heartbeatRunId(latestRun);

    if (!latestRunId) return;

    const refreshKey = `${latestRunId}:${latestRun?.status}`;

    if (refreshedTerminalRunRef.current === refreshKey) return;

    refreshedTerminalRunRef.current = refreshKey;

    void queryClient.invalidateQueries({ queryKey: ["issue", issueId] });

    void queryClient.invalidateQueries({ queryKey: ["issues", orgId] });

    void queryClient.invalidateQueries({ queryKey: ["issue-activity", issueId] });

    void queryClient.invalidateQueries({ queryKey: ["issue-documents", issueId] });

    void queryClient.invalidateQueries({ queryKey: ["issue-work-products", issueId] });

  }, [issueId, issueRuns.data, orgId, queryClient]);

  const review = useMutation({

    mutationFn: (decision: IssueReviewDecision) => issuesApi.review(issueId, { decision }),

    onSuccess: () => {

      setReviewNotice("");

      void queryClient.invalidateQueries({ queryKey: ["issue", issueId] });

    },

  });

  const uploadAttachment = useMutation({

    mutationFn: (file?: File) => {

      const selectedFile = file ?? attachmentFile;

      if (!selectedFile) throw new Error("请选择附件文件");

      return issuesApi.uploadAttachment(orgId, issueId, {

        file: selectedFile,

        usage: "attachment",

      });

    },

    onSuccess: (_, file) => {

      setAttachmentUploadNotice(`已上传 ${file?.name ?? attachmentFile?.name ?? "附件"}`);

      setAttachmentFile(null);

      setAttachmentMenuOpen(false);

      void queryClient.invalidateQueries({ queryKey: ["issue-attachments", issueId] });

    },

    onMutate: () => {

      setAttachmentUploadNotice("");

    },

  });

  const deleteAttachment = useMutation({

    mutationFn: (attachmentId: string) => issuesApi.deleteAttachment(attachmentId),

    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["issue-attachments", issueId] }),

  });

  useEffect(() => {

    if (!issue.data) return;

    writeRecentIssue(orgId, {

      id: issue.data.id,

      title: issue.data.title,

      identifier: issue.data.identifier,

      status: issue.data.status,

    });

  }, [issue.data, orgId]);

  function submitComment(event: FormEvent) {

    event.preventDefault();

    if (comment.trim()) addComment.mutate();

  }

  function submitCommentFromKeyboard(event: KeyboardEvent<HTMLTextAreaElement>) {

    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;

    event.preventDefault();

    if (comment.trim() && !addComment.isPending) addComment.mutate();

  }

  function updateCommentMention(value: string, cursor: number | null | undefined) {

    const position = typeof cursor === "number" ? cursor : value.length;

    setMentionQuery(mentionQueryAtCursor(value, position));

  }

  function changeComment(value: string, cursor: number | null | undefined) {

    setComment(value);

    updateCommentMention(value, cursor);

  }

  function insertMention(agent: Agent) {

    if (!mentionQuery) return;

    const textarea = commentTextareaRef.current;

    const cursor = textarea?.selectionStart ?? comment.length;

    const token = agentMentionToken(agent);

    const nextComment = `${comment.slice(0, mentionQuery.start)}@${token} ${comment.slice(cursor)}`;

    const nextCursor = mentionQuery.start + token.length + 2;

    setComment(nextComment);

    setMentionQuery(null);

    window.setTimeout(() => {

      textarea?.focus();

      textarea?.setSelectionRange(nextCursor, nextCursor);

    }, 0);

  }

  const timelineItems = issueTimelineItems(issueActivity.data, comments.data);

  function selectAttachment(event: ChangeEvent<HTMLInputElement>) {

    const file = event.target.files?.[0] ?? null;

    setAttachmentFile(file);

    setAttachmentUploadNotice("");

    if (file) uploadAttachment.mutate(file);

    event.target.value = "";

  }

  function submitSubIssue(event: FormEvent) {

    event.preventDefault();

    if (subIssueTitle.trim()) createSubIssue.mutate();

  }

  function submitReviewDecision(decision: IssueReviewDecision) {

    if (!issue.data) return;

    const blockReason = reviewDecisionBlockReason(issue.data);

    if (blockReason) {

      setReviewNotice(blockReason);

      return;

    }

    setReviewNotice("");

    review.mutate(decision);

  }

  function markIssueInReview() {

    if (!issue.data) return;

    const blockReason = markReviewBlockReason(issue.data);

    if (blockReason) {

      setReviewNotice(blockReason);

      return;

    }

    setReviewNotice("");

    updateIssue.mutate({ status: "in_review" });

  }

  function executeCurrentIssue() {

    const latestRun = latestIssueRun(issueRuns.data ?? [], null, issueId);

    if (uploadAttachment.isPending) {

      setExecuteNotice("附件上传中，上传完成后再启动执行。");

      return;

    }

    if (isLiveRun(latestRun?.status)) {

      setExecuteNotice("当前任务已有运行在执行中，请等待结束后再重新执行。");

      return;

    }

    if (!issue.data?.assigneeAgentId) {

      setExecuteNotice("请先分配负责人，再启动执行。");

      return;

    }

    if (["done", "cancelled"].includes(issue.data.status)) {

      setExecuteNotice("请先重新打开任务，再启动执行。");

      return;

    }

    setExecuteNotice(isRerunnableRun(latestRun?.status) ? "正在提交重新执行请求..." : "正在提交执行请求...");

    executeIssue.mutate();

  }

  if (issue.error) return <ErrorNotice error={issue.error} />;

  const agentList = Array.isArray(agents.data) ? agents.data : [];

  const hierarchyMembers = Array.isArray(hierarchy.data) ? hierarchy.data : [];

  const memberList = organizationMembersWithAgentFallback(hierarchyMembers, agentList, orgId);

  const currentUserId = session.data?.user?.id ?? "";

  const isAssignedHuman = Boolean(issue.data?.assigneeUserId);

  const isCurrentHumanAssignee = Boolean(
    currentUserId && issue.data?.assigneeUserId === currentUserId,
  );

  const currentMember = memberList.find(
    (member) => member.principalType === "user" && member.principalId === currentUserId,
  );

  const humanExecutionOnly = isCurrentHumanAssignee && currentMember?.role !== "owner";

  const agentsById = new Map(agentList.map((agent) => [agent.id, agent]));

  const membersByPrincipal = new Map(
    memberList.map((member) => [`${member.principalType}:${member.principalId}`, member]),
  );

  const mentionCandidates = mentionQuery

    ? agentList

        .filter((agent) => {

          const query = mentionQuery.query;

          if (!query) return true;

          return [agent.name, agent.urlKey, agent.id].some((value) => typeof value === "string" && value.toLowerCase().includes(query));

        })

        .slice(0, 8)

    : [];

  const goalList = Array.isArray(goals.data) ? goals.data : [];

  const projectList = Array.isArray(projects.data) ? projects.data : [];

  const subIssueList = subIssues.data?.children ?? [];

  const latestRun = latestIssueRun(issueRuns.data ?? [], null, issueId);

  const latestRunError = runErrorMessage(latestRun?.error);

  const latestRunErrorNotice =

    latestRun && isExpectedCancelledRun(latestRun)

      ? null

      : latestRunError;

  const activeAssigneeRuns = activeQueueRunsForAgent(orgHeartbeatRuns.data ?? [], issue.data?.assigneeAgentId);
  const cancellingRunId =
    cancelIssueRun.isPending && cancelIssueRun.variables
      ? heartbeatRunId(cancelIssueRun.variables)
      : undefined;
  const latestRunIsLive = isLiveRun(latestRun?.status);
  const latestRunCanReexecute = isRerunnableRun(latestRun?.status);
  const latestRunSucceeded = latestRun?.status === "succeeded";
  const latestAnyRun = latestAnyRunForIssue(issueRuns.data ?? [], issueId);
  const latestCloseoutRun = latestTerminalRunForIssue(issueRuns.data ?? [], issueId);
  const closeoutReviewActivity =
    issue.data && !isLiveRun(latestAnyRun?.status)
      ? issueCloseoutReviewActivity(issue.data, issueActivity.data, latestCloseoutRun)
      : null;
  const latestRunHasCloseoutSignal = issue.data && latestRun ? runHasExplicitCloseoutSignal(latestRun, issueActivity.data, issue.data.id) : false;

  const needsCloseoutPrompt = issue.data

    ? latestRunSucceeded &&

      ["todo", "in_progress"].includes(issue.data.status) &&

      !closeoutReviewActivity &&

      !latestRunHasCloseoutSignal

    : false;

  const hideLatestRunError =

    executeIssue.isPending ||

    executeNotice.startsWith("正在提交") ||

    executeNotice.startsWith("执行请求已提交") ||

    executeNotice.startsWith("已连接到运行") ||

    executeNotice.startsWith("已创建运行");

  const executeButtonLabel = executeIssue.isPending

    ? "提交中"

    : latestRunCanReexecute

      ? "重新执行"

      : latestRunSucceeded

        ? "再次执行"

        : "启动执行";

  const executeBlockReason = uploadAttachment.isPending

    ? "附件上传中，上传完成后再启动执行"

    : latestRunIsLive

      ? "当前任务已有运行在执行中，请等待结束后再重新执行"

      : issue.data && ["done", "cancelled"].includes(issue.data.status)

        ? "请先重新打开任务，再启动执行"

        : issue.data?.assigneeAgentId

          ? ""

          : "请先分配负责人";

  return (

    <IssuesWorkspace contentClassName="org-content-full" orgId={orgId}>

      {agents.error && <ErrorNotice error={agents.error} />}

      {hierarchy.error && <ErrorNotice error={hierarchy.error} />}

      {goals.error && <ErrorNotice error={goals.error} />}

      {projects.error && <ErrorNotice error={projects.error} />}

      {orgHeartbeatRuns.error && <ErrorNotice error={orgHeartbeatRuns.error} />}

      {issue.data && (

        <div className="issue-detail-layout">

          <header className="issue-detail-top">

            <nav aria-label="任务导航" className="issue-breadcrumb">

              <Link to={`/orgs/${orgId}/issues`}>任务编号</Link>
              <span>/</span>

              <span>{issueDisplayId(issue.data)}</span>

            </nav>

            <div className="issue-detail-title-block">

              <div className="issue-detail-kicker">
                <IssueIdStrip issue={issue.data} />
                {latestRun && (
                  <StatusPill status={latestRun.status}>
                    {latestRunBadgeLabel(latestRun)}结果：{latestRunStatusText(latestRun)}
                  </StatusPill>
                )}
              </div>

              <div className="issue-title-row">

                <h1>{issue.data.title}</h1>

                <div className="issue-header-actions">

                  {!isAssignedHuman && <button

                    aria-disabled={executeBlockReason ? "true" : undefined}

                    className={executeBlockReason ? "is-disabled" : undefined}

                    disabled={executeIssue.isPending}

                    title={executeBlockReason || (latestRunCanReexecute ? "重新交给负责人启动一次运行" : "交给负责人启动一次运行")}

                    type="button"

                    onClick={executeCurrentIssue}

                  >

                    {executeButtonLabel}

                  </button>}

                  {!isAssignedHuman && <button

                    className="secondary small-button"

                    disabled={checkoutIssue.isPending || !issue.data.assigneeAgentId}

                    title={issue.data.assigneeAgentId ? "由当前负责人签出任务" : "请先分配负责人"}

                    type="button"

                    onClick={() => checkoutIssue.mutate()}

                  >

                    签出任务

                  </button>}

                  {isAssignedHuman && isCurrentHumanAssignee && issue.data.status !== "done" && issue.data.status !== "cancelled" && (
                    <button
                      disabled={updateIssue.isPending || issue.data.status === "in_review"}
                      title={issue.data.status === "in_review" ? "任务正在等待评审" : undefined}
                      type="button"
                      onClick={() => updateIssue.mutate({
                        status: issue.data.status === "in_progress" ? "done" : "in_progress",
                      })}
                    >
                      {issue.data.status === "in_progress" ? "提交完成" : "开始处理"}
                    </button>
                  )}

                  {isAssignedHuman && isCurrentHumanAssignee && ["todo", "in_progress"].includes(issue.data.status) && (
                    <button
                      className="secondary small-button"
                      disabled={updateIssue.isPending}
                      type="button"
                      onClick={() => updateIssue.mutate({ status: "blocked" })}
                    >
                      标记阻塞
                    </button>
                  )}

                  {isAssignedHuman && !isCurrentHumanAssignee && (
                    <Badge>等待 Human 负责人处理</Badge>
                  )}

                  <button className="secondary small-button" type="button" onClick={() => navigator.clipboard?.writeText(issueDisplayId(issue.data))}>

                    复制 ID

                  </button>

                  <Link className="button secondary small-button" to={`/orgs/${orgId}/chats`}>聊天</Link>

                </div>

              </div>

            </div>

            {executeIssue.error && <ErrorNotice error={executeIssue.error} />}

            {checkoutIssue.error && <ErrorNotice error={checkoutIssue.error} />}

            {executeNotice && <p className="issue-action-notice" role="status">{executeNotice}</p>}

            {latestRun && isRerunnableRun(latestRun.status) && latestRunErrorNotice && !hideLatestRunError && (

              <p className="error-notice" role="status">

                {latestRunBadgeLabel(latestRun)}结果：{latestRunStatusText(latestRun)}
                {latestRunErrorNotice ? `：${latestRunErrorNotice}` : ""}

              </p>

            )}

            {closeoutReviewActivity && (

              <p aria-label="需要人工确认收口" className="error-notice" role="status">

                该任务的自动收口已用尽，需要人工确认：标记完成、改为阻塞、重新执行或补充评论。

                {` ${issueCloseoutReviewSummary(closeoutReviewActivity)}`}

              </p>

            )}

            {needsCloseoutPrompt && (

              <p aria-label="需要收尾" className="issue-action-notice" role="status">

                最新运行已成功，但任务仍未收口。若任务已经完成，请在任务阶段下拉中改成 done；否则补充 issue block 或 issue comment。

                <button

                  className="secondary small-button"

                  disabled={passiveFollowup.isPending}

                  type="button"

                  onClick={() => passiveFollowup.mutate()}

                >

                  {passiveFollowup.isPending ? "提交中" : "立即收尾跟进"}

                </button>

              </p>

            )}

            {passiveFollowup.error && <ErrorNotice error={passiveFollowup.error} />}

          </header>

          <main className="issue-detail-main">

            <p className="issue-description">{issue.data.description || "暂无描述"}</p>

            <IssueQueueStatusPanel
              activeRuns={activeAssigneeRuns}
              agentsById={agentsById}
              currentRun={latestRun}
              issue={issue.data}
              orgId={orgId}
            />

            <section aria-label="子任务" className="issue-section-card">

              <div className="issue-section-heading">

                <div>

                  <p className="eyebrow">SUBTASKS</p>

                  <h2>子任务</h2>

                </div>

                <span className="muted">
                  {closeoutPolicyLabel(subIssues.data?.closeoutPolicy?.mode) && (
                    <Badge>{closeoutPolicyLabel(subIssues.data?.closeoutPolicy?.mode)}</Badge>
                  )}
                  {subIssueList.length}
                </span>

              </div>

              <form className="issue-subtask-form" onSubmit={submitSubIssue}>

                <input

                  aria-label="子任务名称"

                  placeholder="输入子任务名称"

                  value={subIssueTitle}

                  onChange={(event) => setSubIssueTitle(event.target.value)}

                />

                <button disabled={createSubIssue.isPending || !subIssueTitle.trim()} type="submit">添加子任务</button>

              </form>

              {createSubIssue.error && <ErrorNotice error={createSubIssue.error} />}

              {subIssues.isLoading && <p className="muted">加载子任务中...</p>}

              {subIssues.error && <ErrorNotice error={subIssues.error} />}

              {!subIssues.isLoading && !subIssues.error && subIssueList.length === 0 && <p className="muted">暂无子任务。</p>}

              {subIssueList.length > 0 && (

                <div className="issue-subtask-list">

                  {subIssueList.map((child) => (

                    <Link className="issue-subtask-row" key={child.id} to={`/orgs/${orgId}/issues/${child.id}`}>

                      <span className="issue-subtask-id">{child.identifier ?? child.id.slice(0, 8)}</span>

                      <strong>{child.title}</strong>

                      <span className="issue-subtask-assignee">

                        <span>执行者</span>

                        <strong>{issueAssigneeLabel(child, membersByPrincipal, agentsById)}</strong>

                      </span>

                      <span className="issue-subtask-product">

                        <span>产物</span>

                        <strong title={childPrimaryProductTitle(child) ?? undefined}>
                          {childPrimaryProductTitle(child) ?? "—"}
                        </strong>

                      </span>

                      <span className="issue-subtask-meta">

                        <Badge>{child.status}</Badge>

                        <Badge>{child.priority}</Badge>

                      </span>

                    </Link>
))}

                </div>

              )}

            </section>

            <section aria-label="任务验收" className="issue-section-card issue-acceptance-card">

              <div className="issue-section-heading">

                <div>

                  <p className="eyebrow">TASK ACCEPTANCE</p>

                  <h2>任务验收</h2>

                  <p className="muted">在一个位置检查任务结果、处理代码改动，并给出最终评审结论。</p>

                </div>

                <span className="muted">当前阶段：{statusLabel(issue.data.status)}</span>

              </div>

              <IssueCodeDeliveryPanel issue={issue.data} />

              <section aria-label="评审结论" className="issue-acceptance-subsection issue-review-decision">

                <div className="issue-acceptance-subheading">

                  <div>

                    <p className="eyebrow">REVIEW DECISION</p>

                    <h3>评审结论</h3>

                    <p className="muted">Reviewer 根据任务结果给出通过、修改、人工处理或阻塞结论。</p>

                  </div>

                </div>

                <div className="issue-review-status">

                <div>

                  <span>Reviewer</span>

                  <strong>{issue.data.reviewerAgentId ? agentName(issue.data.reviewerAgentId, agentsById) : "未设置"}</strong>

                </div>

                <div>

                  <span>评审状态</span>

                  <strong>{["in_review", "blocked"].includes(issue.data.status) ? "等待评审结论" : "未进入评审"}</strong>

                </div>

                <p>{reviewStatusText(issue.data, agentsById)}</p>

                </div>

                <div className="actions">

                {(["approve", "request_changes", "needs_followup", "blocked"] as IssueReviewDecision[]).map((decision, index) => (

                  <button

                    aria-disabled={Boolean(reviewDecisionBlockReason(issue.data))}

                    className={`${index === 0 ? "" : "secondary"}${reviewDecisionBlockReason(issue.data) ? " is-disabled" : ""}`}

                    disabled={review.isPending}

                    key={decision}

                    onClick={() => submitReviewDecision(decision)}

                    title={reviewDecisionBlockReason(issue.data) || reviewDecisionLabel(decision)}

                    type="button"

                  >

                    {reviewDecisionLabel(decision)}

                  </button>
))}

                <button

                  aria-disabled={Boolean(markReviewBlockReason(issue.data))}

                  className={`secondary${markReviewBlockReason(issue.data) ? " is-disabled" : ""}`}

                  disabled={updateIssue.isPending}

                  onClick={markIssueInReview}

                  title={markReviewBlockReason(issue.data) || "将任务标记为待评审"}

                  type="button"

                >

                  标记待评审

                </button>

                </div>

                {reviewNotice && <p className="issue-action-notice" role="status">{reviewNotice}</p>}

                {review.error && <ErrorNotice error={review.error} />}

                {updateIssue.error && <ErrorNotice error={updateIssue.error} />}

              </section>

            </section>

            <section aria-label="运行记录" className="issue-section-card">

              <div className="issue-section-heading">

                <div>

                  <p className="eyebrow">RUNS</p>

                  <h2>运行记录</h2>

                </div>

                <div className="issue-section-heading-actions">

                  <span className="muted">{issueRuns.data?.length ?? 0} 次运行</span>

                </div>

              </div>

              <IssueRunsPanel
                agentsById={agentsById}
                currentRunId={currentRunId}
                embedded
                expandedRunIds={expandedRunIds}
                onSelect={(runId) => {
                  localStorage.setItem(issueRunStorageKey(orgId, issueId), runId);
                  setCurrentRunId(runId);
                }}

                onToggle={(runId) => {

                  setExpandedRunIds((current) => {

                    const next = new Set(current);

                    if (next.has(runId)) {

                      next.delete(runId);

                    } else {

                      next.add(runId);

                    }

                    return next;

                  });

                }}

                renderRunDetails={(runId) => (

                  <IssueRunDetailsPanel
                    cancellingRunId={cancellingRunId}
                    issue={issue.data}

                    issueId={issueId}

                    latestRunStatus={latestRun?.status}

                    onCancelRun={(run) => cancelIssueRun.mutate(run)}

                    onRetryRun={(run) => retryRun.mutate(run)}

                    orgId={orgId}

                    retryingRunId={

                      retryRun.isPending && retryRun.variables

                        ? heartbeatRunId(retryRun.variables)

                        : undefined

                    }

                    runId={runId}

                  />

                )}

                runs={issueRuns.data ?? []}

              />

              {cancelIssueRun.error && <ErrorNotice error={cancelIssueRun.error} />}

              {retryRun.error && <ErrorNotice error={retryRun.error} />}

            </section>


            <section aria-label="动态" className="issue-section-card">

              <div className="issue-section-heading">

                <div>

                  <p className="eyebrow">ACTIVITY</p>

                  <h2>动态</h2>

                </div>

                <span className="muted">

                  {comments.data?.length ?? 0} 条评论 · {attachments.data?.length ?? 0} 个文件

                </span>

              </div>

              {comments.error && <ErrorNotice error={comments.error} />}

              {issueActivity.error && <ErrorNotice error={issueActivity.error} />}

              {attachments.error && <ErrorNotice error={attachments.error} />}

              {uploadAttachment.error && <ErrorNotice error={uploadAttachment.error} />}

              {deleteAttachment.error && <ErrorNotice error={deleteAttachment.error} />}

              <section aria-label="附件" className="issue-attachments-inline">

                {uploadAttachment.isPending && attachmentFile && (

                  <p className="issue-upload-status" role="status">正在上传 {attachmentFile.name}...</p>

                )}

                {!uploadAttachment.isPending && attachmentUploadNotice && (

                  <p className="issue-upload-status success" role="status">{attachmentUploadNotice}</p>

                )}

                {attachments.isLoading && <p className="muted">加载附件中...</p>}

                {attachments.data?.length ? (

                  <div className="issue-attachment-list">

                    {attachments.data.map((attachment) => (

                      <article className="issue-attachment-item" key={attachment.id}>

                        <div className="issue-attachment-content">

                          {attachment.contentPath ? (

                            <a

                              className="issue-attachment-title"

                              href={attachment.contentPath}

                              rel="noreferrer"

                              target="_blank"

                              title={attachment.originalFilename ?? attachment.id}

                            >

                              {attachment.originalFilename ?? attachment.id}

                            </a>

                          ) : (

                            <strong>{attachment.originalFilename ?? attachment.id}</strong>

                          )}

                          <p className="muted">{attachment.contentType} · {formatBytes(attachment.byteSize)}</p>

                          {attachment.contentPath && attachment.contentType.startsWith("image/") && (

                            <a href={attachment.contentPath} rel="noreferrer" target="_blank">

                              <img

                                alt={attachment.originalFilename ?? "附件"}

                                className="issue-attachment-preview"

                                loading="lazy"

                                src={attachment.contentPath}

                              />

                            </a>

                          )}

                        </div>

                        <button

                          aria-label={`删除 ${attachment.originalFilename ?? attachment.id}`}

                          className="danger small-button"

                          disabled={deleteAttachment.isPending}

                          onClick={() => deleteAttachment.mutate(attachment.id)}

                          title="删除附件"

                          type="button"

                        >

                          删除

                        </button>

                      </article>
))}

                  </div>

                ) : null}

              </section>

              <div className="issue-activity-list">

                {timelineItems.map((timelineItem) => {

                  if (timelineItem.kind === "activity") {

                    const item = timelineItem.item;

                    return (

                      <article className={`issue-activity-item tone-${activityTone(item)}`} key={timelineItem.id}>

                        <div className="issue-activity-avatar">{activityIcon(item)}</div>

                        <div className="issue-activity-content">

                          <div className="issue-activity-title-row">

                            <strong>{activityTitle(item)}</strong>

                            <span className="muted">{activityMeta(item, issue.data.id)}</span>
                          </div>

                          <p>
                            {activitySummary(item)}
                            {activityActorText(item) ? <span className="issue-activity-actor">{activityActorText(item)}</span> : null}
                          </p>
                        </div>

                      </article>

                    );

                  }

                  const item = timelineItem.item;

                  return (

                    <article className="issue-activity-item tone-comment" key={timelineItem.id}>

                      <div className="issue-activity-avatar">C</div>

                      <div className="issue-activity-content">

                        <div className="issue-activity-title-row">

                          <strong>评论</strong>

                          <span className="muted">{formatDateTime(item.createdAt)}</span>

                        </div>

                        <p>{item.body}</p>

                      </div>

                    </article>

                  );

                })}

                {comments.isSuccess && comments.data.length === 0 && (!Array.isArray(issueActivity.data) || issueActivity.data.length === 0) && (

                  <p className="muted">暂无动态。</p>

                )}

              </div>

              <form className="form issue-comment-form" onSubmit={submitComment}>

                <label>

                  添加评论

                  <textarea

                    ref={commentTextareaRef}

                    aria-controls={mentionCandidates.length ? "issue-comment-mention-list" : undefined}

                    aria-expanded={mentionCandidates.length ? "true" : "false"}

                    value={comment}

                    onChange={(event) => changeComment(event.target.value, event.target.selectionStart)}

                    onClick={(event) => updateCommentMention(event.currentTarget.value, event.currentTarget.selectionStart)}

                    onKeyDown={submitCommentFromKeyboard}

                    onKeyUp={(event) => updateCommentMention(event.currentTarget.value, event.currentTarget.selectionStart)}

                    required

                  />

                </label>

                {mentionCandidates.length > 0 && (

                  <div

                    aria-label="智能体提及候选"

                    className="issue-comment-mentions"

                    id="issue-comment-mention-list"

                    role="listbox"

                  >

                    {mentionCandidates.map((agent) => {

                      const token = agentMentionToken(agent);

                      return (

                        <button

                          aria-label={`${agent.name} @${token}`}

                          className="issue-comment-mention-option"

                          key={agent.id}

                          onClick={() => insertMention(agent)}

                          role="option"

                          type="button"

                        >

                          <strong>{agent.name}</strong>

                          <span>@{token}</span>

                        </button>

                      );

                    })}

                  </div>

                )}

                <div className="issue-comment-actions">

                  <div className="issue-attachment-menu-anchor">

                    <button

                      className="secondary small-button"

                      disabled={uploadAttachment.isPending}

                      onClick={() => setAttachmentMenuOpen((open) => !open)}

                      type="button"

                    >

                      {uploadAttachment.isPending ? "上传中..." : "添加附件"}

                    </button>

                    {attachmentMenuOpen && (

                      <div className="issue-attachment-popover" role="menu">

                        <label className="issue-attachment-popover-item">

                          上传本地文件

                          <input onChange={selectAttachment} type="file" />

                        </label>

                      </div>

                    )}

                  </div>

                  <button type="submit">发送评论</button>

                </div>

              </form>

            </section>

          </main>

          <aside className="issue-detail-sidebar">

            <div className="issue-sidebar-sticky">

              <IssuePropertiesPanel

                agents={agentList}

                executionOnly={humanExecutionOnly}

                goals={goalList}

                issue={issue.data}

                members={memberList}

                isUpdating={updateIssue.isPending}

                latestRunStatus={latestRun?.status}

                onUpdate={(payload) => updateIssue.mutate(payload)}

                projects={projectList}

              />

              <IssueCostPanel runs={issueRuns.data ?? []} />

              {updateIssue.error && <ErrorNotice error={updateIssue.error} />}

            </div>

          </aside>

        </div>

      )}

      {!issue.data && (

        <header className="page-header">

          <div>

            <Link className="back-link" to={`/orgs/${orgId}/issues`}>返回任务</Link>

            <h1>载入中...</h1>

          </div>

        </header>

      )}

    </IssuesWorkspace>

  );

}
