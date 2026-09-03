import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { accessApi } from "../api/access";
import { agentsApi } from "../api/agents";
import { approvalsApi } from "../api/approvals";
import { messengerApi } from "../api/messenger";
import { projectsApi } from "../api/projects";
import type { ApprovalDetail, ApprovalListItem, ApprovalStatus } from "../api/types";
import { ChatsWorkspace } from "../components/ContextWorkspace";
import { ErrorNotice } from "../components/ErrorNotice";
import { TertiaryPageHeader } from "../components/TertiaryPageShell";
import { statusLabel } from "../utils/display";

const STATUS_OPTIONS: Array<{ value: ApprovalStatus; label: string }> = [
  { value: "pending", label: "待审批" },
  { value: "revision_requested", label: "需修改" },
  { value: "approved", label: "已同意" },
  { value: "rejected", label: "已拒绝" },
];

type ApprovalDecisionAction = "approve" | "reject" | "requestRevision";

const DECISION_LABELS: Record<ApprovalDecisionAction, string> = {
  approve: "同意",
  reject: "拒绝",
  requestRevision: "退回",
};

function approvalTitle(approval: ApprovalListItem) {
  return approval.type;
}

function proposedIssueTitle(approval?: ApprovalDetail | null): string | null {
  const proposedIssue = approval?.payload?.proposedIssue;
  if (!proposedIssue || typeof proposedIssue !== "object" || Array.isArray(proposedIssue)) return null;
  const title = (proposedIssue as Record<string, unknown>).title;
  return typeof title === "string" && title.trim() ? title.trim() : null;
}

function proposedIssueDescription(approval?: ApprovalDetail | null): string | null {
  const proposedIssue = approval?.payload?.proposedIssue;
  if (!proposedIssue || typeof proposedIssue !== "object" || Array.isArray(proposedIssue)) return null;
  const description = (proposedIssue as Record<string, unknown>).description;
  return typeof description === "string" && description.trim() ? description.trim() : null;
}

function approvalFromMessengerItem(item: Record<string, unknown>): ApprovalDetail | null {
  const approval = item.approval;
  return approval && typeof approval === "object" && !Array.isArray(approval)
    ? approval as ApprovalDetail
    : null;
}

function formatDate(value: string) {
  if (!value) return "未知时间";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function parseJsonObject(value: string): Record<string, unknown> {
  const parsed: unknown = JSON.parse(value);
  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error("审批 payload 必须是 JSON 对象");
  }
  return parsed as Record<string, unknown>;
}

function createApprovalErrorMessage(error: unknown): string {
  const message = error instanceof Error ? error.message : "";
  if (/one or more issues not found/i.test(message)) {
    return "一个或多个任务不存在。请检查任务 ID 后重试。";
  }
  return message || "创建审批失败";
}

export function ApprovalsPage() {
  const { orgId = "" } = useParams();
  const [status, setStatus] = useState<ApprovalStatus | "">("");
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [approvalType, setApprovalType] = useState<ApprovalListItem["type"]>("chat_operation");
  const [approvalPayload, setApprovalPayload] = useState("{}");
  const [requestedByAgentId, setRequestedByAgentId] = useState("");
  const [issueIds, setIssueIds] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);
  const [decisionDialog, setDecisionDialog] = useState<{
    action: ApprovalDecisionAction;
    approvalId: string;
    title: string;
  } | null>(null);
  const [decisionNote, setDecisionNote] = useState("");
  const queryClient = useQueryClient();
  const approvals = useQuery({
    queryKey: ["messenger-approvals", orgId],
    queryFn: () => messengerApi.approvals(orgId),
  });
  const agents = useQuery({
    queryKey: ["agents", orgId],
    queryFn: () => agentsApi.list(orgId),
  });
  const members = useQuery({
    queryKey: ["organization-members", orgId],
    queryFn: () => accessApi.members(orgId),
  });
  const projects = useQuery({
    queryKey: ["projects", orgId],
    queryFn: () => projectsApi.list(orgId),
  });
  const decision = useMutation({
    mutationFn: ({ approvalId, action, note }: { approvalId: string; action: ApprovalDecisionAction; note: string }) =>
      approvalsApi[action](approvalId, note.trim() ? { decisionNote: note.trim() } : {}),
    onSuccess: (approval) => {
      setDecisionDialog(null);
      setDecisionNote("");
      void queryClient.invalidateQueries({ queryKey: ["messenger-approvals", orgId] });
      void queryClient.invalidateQueries({ queryKey: ["approvals", orgId] });
      void queryClient.invalidateQueries({ queryKey: ["approval", approval.id] });
      void queryClient.invalidateQueries({ queryKey: ["approval-issues", approval.id] });
      void queryClient.invalidateQueries({ queryKey: ["issues", orgId] });
      void queryClient.invalidateQueries({ queryKey: ["issue"] });
    },
  });
  const createApproval = useMutation({
    mutationFn: () =>
      approvalsApi.create(orgId, {
        type: approvalType,
        payload: parseJsonObject(approvalPayload),
        ...(requestedByAgentId.trim() ? { requestedByAgentId: requestedByAgentId.trim() } : {}),
        ...(issueIds.trim()
          ? { issueIds: issueIds.split(",").map((item) => item.trim()).filter(Boolean) }
          : {}),
      }),
    onSuccess: () => {
      setCreateDialogOpen(false);
      setApprovalPayload("{}");
      setRequestedByAgentId("");
      setIssueIds("");
      setCreateError(null);
      void queryClient.invalidateQueries({ queryKey: ["messenger-approvals", orgId] });
      void queryClient.invalidateQueries({ queryKey: ["approvals", orgId] });
    },
    onError: (error) => setCreateError(createApprovalErrorMessage(error)),
  });
  const approvalList = (approvals.data?.detail.items ?? [])
    .map(approvalFromMessengerItem)
    .filter((approval): approval is ApprovalDetail => Boolean(approval))
    .filter((approval) => !status || approval.status === status);
  const agentList = agents.data ?? [];
  const memberLabels = new Map((members.data ?? []).map((member) => [
    member.principalId,
    `${member.principalType === "agent" ? "Agent" : "Human"} · ${member.displayName}`,
  ]));
  const projectNames = new Map((projects.data ?? []).map((project) => [project.id, project.name]));
  function submitApproval(event: FormEvent) {
    event.preventDefault();
    setCreateError(null);
    createApproval.mutate();
  }

  function openDecisionDialog(approval: ApprovalDetail, action: ApprovalDecisionAction) {
    decision.reset();
    setDecisionNote("");
    setDecisionDialog({
      action,
      approvalId: approval.id,
      title: proposedIssueTitle(approval) ?? approvalTitle(approval),
    });
  }

  function submitDecision(event: FormEvent) {
    event.preventDefault();
    if (!decisionDialog) return;
    decision.mutate({
      action: decisionDialog.action,
      approvalId: decisionDialog.approvalId,
      note: decisionNote,
    });
  }

  return (
    <ChatsWorkspace contentClassName="org-content-full" orgId={orgId}>
      <TertiaryPageHeader
        eyebrow="Approvals"
        supporting="审批对象保留在消息上下文中处理，避免决策脱离对话。"
        title="审批管理"
      />
      <section className="approval-management">
        <div className="approval-toolbar">
          <div aria-label="审批状态筛选" className="approval-status-filter" role="group">
            <button className={status === "" ? "active" : ""} onClick={() => setStatus("")} type="button">全部</button>
            {STATUS_OPTIONS.map((option) => (
              <button
                className={status === option.value ? "active" : ""}
                key={option.value}
                onClick={() => setStatus(status === option.value ? "" : option.value)}
                type="button"
              >
                {option.label}
              </button>
            ))}
          </div>
          <button className="secondary approval-create-action" onClick={() => setCreateDialogOpen(true)} type="button">创建审批</button>
        </div>
        {approvals.error && <ErrorNotice error={approvals.error} />}
        {decision.error && !decisionDialog && <ErrorNotice error={decision.error} />}
        <div className="approval-thread">
          {approvalList.length > 0 && (
            <div aria-hidden="true" className="approval-list-columns">
              <span />
              <span>审批事项</span>
              <span>状态与操作</span>
            </div>
          )}
          {approvalList.map((approval) => (
            <ApprovalCard
              approval={approval}
              decisionPending={decision.isPending}
              key={approval.id}
              memberLabels={memberLabels}
              onDecision={(action) => openDecisionDialog(approval, action)}
              orgId={orgId}
              projectNames={projectNames}
            />
          ))}
          {approvals.isSuccess && approvalList.length === 0 && (
            <section className="panel approval-empty-state">
              <p className="eyebrow">Approvals</p>
              <h2>暂无待展示审批</h2>
              <p className="muted">需要人工处理或最近更新的审批会出现在这里。</p>
            </section>
          )}
        </div>
      </section>
      {createDialogOpen && (
        <div aria-modal="true" className="modal-backdrop" role="dialog">
          <section className="panel task-modal">
            <div className="task-modal-header">
              <h2>创建审批</h2>
              <button className="secondary" onClick={() => setCreateDialogOpen(false)} type="button">关闭</button>
            </div>
            <form className="form" onSubmit={submitApproval}>
              <label>
                审批类型
                <select value={approvalType} onChange={(event) => setApprovalType(event.target.value as ApprovalListItem["type"])}>
                  <option value="hire_agent">hire_agent</option>
                  <option value="approve_ceo_strategy">approve_ceo_strategy</option>
                  <option value="budget_override_required">budget_override_required</option>
                  <option value="chat_issue_creation">chat_issue_creation</option>
                  <option value="chat_operation">chat_operation</option>
                </select>
              </label>
              <label>
                Payload JSON
                <textarea value={approvalPayload} onChange={(event) => setApprovalPayload(event.target.value)} />
              </label>
              <label>
                发起智能体
                <select value={requestedByAgentId} onChange={(event) => setRequestedByAgentId(event.target.value)}>
                  <option value="">无</option>
                  {agentList.map((agent) => (
                    <option key={agent.id} value={agent.id}>
                      {agent.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                任务 ID
                <input value={issueIds} onChange={(event) => setIssueIds(event.target.value)} />
              </label>
              {createError && <p className="error-notice">{createError}</p>}
              <div className="task-modal-actions">
                <button className="secondary" onClick={() => setCreateDialogOpen(false)} type="button">取消</button>
                <button disabled={createApproval.isPending} type="submit">创建</button>
              </div>
            </form>
          </section>
        </div>
      )}
      {decisionDialog && (
        <div aria-modal="true" className="modal-backdrop" role="dialog">
          <section className="panel task-modal approval-decision-dialog">
            <div className="task-modal-header">
              <div>
                <p className="eyebrow">Approval Decision</p>
                <h2>{DECISION_LABELS[decisionDialog.action]}审批</h2>
              </div>
              <button
                className="secondary"
                disabled={decision.isPending}
                onClick={() => {
                  setDecisionDialog(null);
                  setDecisionNote("");
                  decision.reset();
                }}
                type="button"
              >
                关闭
              </button>
            </div>
            <p className="approval-decision-target" title={decisionDialog.title}>审批事项：{decisionDialog.title}</p>
            <form className="form" onSubmit={submitDecision}>
              <label>
                审核意见{decisionDialog.action === "approve" ? "（可选）" : ""}
                <textarea
                  aria-label="审核意见"
                  autoFocus
                  onChange={(event) => setDecisionNote(event.target.value)}
                  placeholder={decisionDialog.action === "requestRevision" ? "说明退回原因及需要修改的内容" : "填写本次审核意见"}
                  required={decisionDialog.action !== "approve"}
                  value={decisionNote}
                />
              </label>
              {decision.error && <ErrorNotice error={decision.error} />}
              <div className="task-modal-actions">
                <button
                  className="secondary"
                  disabled={decision.isPending}
                  onClick={() => {
                    setDecisionDialog(null);
                    setDecisionNote("");
                    decision.reset();
                  }}
                  type="button"
                >
                  取消
                </button>
                <button
                  className={decisionDialog.action === "reject" ? "danger" : undefined}
                  disabled={decision.isPending}
                  type="submit"
                >
                  确认{DECISION_LABELS[decisionDialog.action]}
                </button>
              </div>
            </form>
          </section>
        </div>
      )}
    </ChatsWorkspace>
  );
}

function ApprovalCard({
  approval,
  decisionPending,
  memberLabels,
  onDecision,
  orgId,
  projectNames,
}: {
  approval: ApprovalDetail;
  decisionPending: boolean;
  memberLabels: Map<string, string>;
  onDecision: (action: ApprovalDecisionAction) => void;
  orgId: string;
  projectNames: Map<string, string>;
}) {
  const issueTitle = proposedIssueTitle(approval);
  const issueDescription = proposedIssueDescription(approval);
  const projectId = proposedIssueProjectId(approval);
  const projectName = projectId ? projectNames.get(projectId) ?? compactId(projectId) : "—";
  const requesterId = approval.requestedByAgentId ?? approval.requestedByUserId;
  const requesterType = approval.requestedByAgentId ? "Agent" : approval.requestedByUserId ? "Human" : null;
  const requesterName = requesterId
    ? memberLabels.get(requesterId) ?? `${requesterType ?? "Member"} · ${compactId(requesterId)}`
    : "系统";
  const pending = approval.status === "pending";
  return (
    <article className="approval-list-item">
      <span aria-hidden="true" className={`approval-list-status-dot ${approval.status}`} />
      <div className="approval-list-summary">
        <h2>
          <Link className="approval-list-link" to={`/orgs/${orgId}/approvals/${approval.id}`}>
            {issueTitle ?? approvalTitle(approval)}
          </Link>
        </h2>
        {issueDescription && <p title={issueDescription}>{issueDescription}</p>}
        <div className="approval-list-meta">
          <span aria-label={`审批类型：${approval.type}`}>{approval.type}</span>
          <span aria-label={`所属项目：${projectName}`} title={projectId ?? undefined}>{projectName}</span>
          <span aria-label={`发起方：${requesterName}`} title={requesterId ?? undefined}>{requesterName}</span>
          <time aria-label={`创建时间：${formatDate(approval.createdAt)}`}>{formatDate(approval.createdAt)}</time>
        </div>
      </div>
      <div className="approval-list-controls">
        <span className={`approval-status-badge ${approval.status}`}>{statusLabel(approval.status)}</span>
        {pending && (
          <div className="approval-list-actions">
            <button className="approve" disabled={decisionPending} onClick={() => onDecision("approve")} type="button">同意</button>
            <button className="reject" disabled={decisionPending} onClick={() => onDecision("reject")} type="button">拒绝</button>
            <button className="revision" disabled={decisionPending} onClick={() => onDecision("requestRevision")} type="button">退回</button>
          </div>
        )}
      </div>
    </article>
  );
}

function proposedIssueProjectId(approval?: ApprovalDetail | null): string | null {
  const proposedIssue = approval?.payload?.proposedIssue;
  if (!proposedIssue || typeof proposedIssue !== "object" || Array.isArray(proposedIssue)) return null;
  const projectId = (proposedIssue as Record<string, unknown>).projectId;
  return typeof projectId === "string" && projectId.trim() ? projectId.trim() : null;
}

function compactId(value: string): string {
  return value.length > 12 ? `${value.slice(0, 8)}…` : value;
}
