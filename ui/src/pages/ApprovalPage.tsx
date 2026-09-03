import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { accessApi } from "../api/access";
import { approvalsApi } from "../api/approvals";
import { projectsApi } from "../api/projects";
import { Badge } from "../components/Badge";
import { ChatsWorkspace } from "../components/ContextWorkspace";
import { ErrorNotice } from "../components/ErrorNotice";
import { TertiaryPageHeader } from "../components/TertiaryPageShell";
import { formatDateTime, statusLabel } from "../utils/display";

function formatPayload(value: unknown): string {
  return JSON.stringify(value ?? {}, null, 2);
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function textValue(record: Record<string, unknown> | null, key: string): string | null {
  const value = record?.[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function compactId(value: string): string {
  return value.length > 12 ? `${value.slice(0, 8)}…` : value;
}

function parseJsonObject(value: string): Record<string, unknown> {
  const parsed: unknown = JSON.parse(value);
  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error("Payload 必须是 JSON 对象。");
  }
  return parsed as Record<string, unknown>;
}

export function ApprovalPage() {
  const { orgId = "", approvalId = "" } = useParams();
  const [decisionNote, setDecisionNote] = useState("");
  const [decisionPayload, setDecisionPayload] = useState("{}");
  const [resubmitPayload, setResubmitPayload] = useState("{}");
  const [commentBody, setCommentBody] = useState("");
  const [commentNotice, setCommentNotice] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const approval = useQuery({
    queryKey: ["approval", approvalId],
    queryFn: () => approvalsApi.get(approvalId),
  });
  const linkedIssues = useQuery({
    queryKey: ["approval-issues", approvalId],
    queryFn: () => approvalsApi.listIssues(approvalId),
    enabled: Boolean(approvalId),
  });
  const comments = useQuery({
    queryKey: ["approval-comments", approvalId],
    queryFn: () => approvalsApi.listComments(approvalId),
    enabled: Boolean(approvalId),
  });
  const members = useQuery({
    queryKey: ["organization-members", orgId],
    queryFn: () => accessApi.members(orgId),
    enabled: Boolean(orgId),
  });
  const projects = useQuery({
    queryKey: ["projects", orgId],
    queryFn: () => projectsApi.list(orgId),
    enabled: Boolean(orgId),
  });
  const act = useMutation({
    mutationFn: (action: "approve" | "reject" | "requestRevision" | "resubmit") => {
      if (action === "resubmit") {
        return approvalsApi.resubmit(approvalId, {
          payload: parseJsonObject(resubmitPayload),
        });
      }
      const payload = parseJsonObject(decisionPayload);
      return approvalsApi[action](approvalId, {
        ...(decisionNote.trim() ? { decisionNote: decisionNote.trim() } : {}),
        ...(Object.keys(payload).length > 0 ? { payload } : {}),
      });
    },
    onMutate: () => setFormError(null),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["approval", approvalId] });
      void queryClient.invalidateQueries({ queryKey: ["approval-issues", approvalId] });
      void queryClient.invalidateQueries({ queryKey: ["messenger-approvals", orgId] });
      void queryClient.invalidateQueries({ queryKey: ["approvals", orgId] });
      void queryClient.invalidateQueries({ queryKey: ["issues", orgId] });
      void queryClient.invalidateQueries({ queryKey: ["issue"] });
    },
    onError: (error) => setFormError(error instanceof Error ? error.message : "审批操作失败"),
  });
  const addComment = useMutation({
    mutationFn: () => approvalsApi.addComment(approvalId, { body: commentBody.trim() }),
    onSuccess: () => {
      setCommentBody("");
      setCommentNotice("评论已添加。评论只记录沟通内容，不会改变审批状态。");
      void queryClient.invalidateQueries({ queryKey: ["approval-comments", approvalId] });
    },
    onMutate: () => setCommentNotice(null),
  });
  function runAction(action: "approve" | "reject" | "requestRevision" | "resubmit") {
    setFormError(null);
    act.mutate(action);
  }
  if (approval.error) return <ErrorNotice error={approval.error} />;
  const isActionable = approval.data?.status === "pending";
  const currentPayload = approval.data ? formatPayload(approval.data.payload) : "{}";
  const proposedIssue = recordValue(approval.data?.payload.proposedIssue);
  const proposedIssueTitle = textValue(proposedIssue, "title");
  const proposedIssueDescription = textValue(proposedIssue, "description");
  const proposedIssueProjectId = textValue(proposedIssue, "projectId");
  const proposedIssueProjectName = proposedIssueProjectId
    ? projects.data?.find((project) => project.id === proposedIssueProjectId)?.name ?? compactId(proposedIssueProjectId)
    : "—";
  const requesterId = approval.data?.requestedByAgentId ?? approval.data?.requestedByUserId;
  const requesterMember = requesterId
    ? members.data?.find((member) => member.principalId === requesterId)
    : undefined;
  const requesterType = requesterMember?.principalType === "agent" || approval.data?.requestedByAgentId
    ? "Agent"
    : requesterMember?.principalType === "user" || approval.data?.requestedByUserId
      ? "Human"
      : null;
  const requesterName = requesterId
    ? `${requesterType ?? "Member"} · ${requesterMember?.displayName ?? compactId(requesterId)}`
    : "系统";
  const deciderId = approval.data?.decidedByUserId;
  const deciderMember = deciderId
    ? members.data?.find((member) => member.principalId === deciderId)
    : undefined;
  const deciderName = deciderId
    ? `Human · ${deciderMember?.displayName ?? compactId(deciderId)}`
    : "—";
  const showsDecisionPanel = isActionable || approval.data?.status === "revision_requested";
  const isRevisionRequested = approval.data?.status === "revision_requested";
  return (
    <ChatsWorkspace contentClassName="org-content-full approval-detail-content" orgId={orgId}>
      <TertiaryPageHeader
        eyebrow={<Link to={`/orgs/${orgId}/approvals`}>← 审批列表</Link>}
        supporting={approval.data ? <Badge>{statusLabel(approval.data.status)}</Badge> : "正在加载审批信息..."}
        title={proposedIssueTitle ?? approval.data?.type ?? "载入中..."}
      />
      {approval.data && (
        <section className={`approval-detail-layout${showsDecisionPanel ? "" : " approval-detail-layout-resolved"}${isRevisionRequested ? " approval-detail-layout-revision" : ""}`}>
          <article className="panel approval-detail">
            <dl className="approval-detail-meta">
              <div>
                <dt>审批类型</dt>
                <dd>{approval.data.type}</dd>
              </div>
              <div>
                <dt>创建时间</dt>
                <dd>{formatDateTime(approval.data.createdAt)}</dd>
              </div>
              <div>
                <dt>发起方</dt>
                <dd title={requesterId ?? undefined}>{requesterName}</dd>
              </div>
              <div>
                <dt>决策人</dt>
                <dd title={deciderId ?? undefined}>{deciderName}</dd>
              </div>
              <div className="approval-detail-id">
                <dt>审批 ID</dt>
                <dd>{approval.data.id}</dd>
              </div>
            </dl>
            {proposedIssue && (
              <section className="approval-request-summary">
                <h2>任务提案</h2>
                {proposedIssueDescription && <p>{proposedIssueDescription}</p>}
                <dl className="detail-grid compact">
                  <div>
                    <dt>优先级</dt>
                    <dd>{textValue(proposedIssue, "priority") ?? "—"}</dd>
                  </div>
                  <div>
                    <dt>执行智能体</dt>
                    <dd>{textValue(proposedIssue, "assigneeAgentId") ?? "—"}</dd>
                  </div>
                  <div>
                    <dt>所属项目</dt>
                    <dd title={proposedIssueProjectId ?? undefined}>{proposedIssueProjectName}</dd>
                  </div>
                </dl>
              </section>
            )}
            {approval.data.decisionNote && !isRevisionRequested && (
              <div className="approval-note">
                <span>审核意见</span>
                <p>{approval.data.decisionNote}</p>
              </div>
            )}
            <details className="approval-payload-details">
              <summary>完整请求 JSON</summary>
              <pre>{JSON.stringify(approval.data.payload, null, 2)}</pre>
            </details>
            <section className="approval-detail-section">
              <div className="approval-section-heading">
                <h2>关联任务</h2>
                <span>{linkedIssues.data?.length ?? 0}</span>
              </div>
              {linkedIssues.error && <ErrorNotice error={linkedIssues.error} />}
              {linkedIssues.isLoading && <p className="muted">加载关联任务中...</p>}
              {!linkedIssues.isLoading && (linkedIssues.data?.length ?? 0) === 0 && <p className="muted">暂无关联任务。</p>}
              {linkedIssues.data?.map((issue) => (
                <Link className="approval-linked-issue" key={issue.id} to={`/orgs/${orgId}/issues/${issue.id}`}>
                  <span>{issue.identifier ?? issue.id.slice(0, 8)}</span>
                  <strong>{issue.title}</strong>
                  <Badge>{statusLabel(issue.status)}</Badge>
                </Link>
              ))}
            </section>
            <section className="approval-detail-section">
              <div className="approval-section-heading">
                <h2>评论</h2>
                <span>{comments.data?.length ?? 0}</span>
              </div>
              <p className="muted approval-comment-hint">
                评论只记录沟通内容，不改变审批状态。
              </p>
              {comments.error && <ErrorNotice error={comments.error} />}
              {comments.isLoading && <p className="muted">加载评论中...</p>}
              {!comments.isLoading && (comments.data?.length ?? 0) === 0 && <p className="muted">暂无评论。</p>}
              {comments.data?.map((comment) => (
                <article className="approval-comment" key={comment.id}>
                  <p>{comment.body}</p>
                  <small className="muted">{comment.authorAgentId ?? comment.authorUserId ?? "未知"} · {formatDateTime(comment.createdAt)}</small>
                </article>
              ))}
              <form
                className="approval-comment-form"
                onSubmit={(event) => {
                  event.preventDefault();
                  if (commentBody.trim()) addComment.mutate();
                }}
              >
                <textarea
                  aria-label="审批评论"
                  placeholder="添加审批评论"
                  value={commentBody}
                  onChange={(event) => setCommentBody(event.target.value)}
                />
                <button disabled={addComment.isPending || !commentBody.trim()} type="submit">添加评论</button>
              </form>
              {commentNotice && <p className="success-notice">{commentNotice}</p>}
              {addComment.error && <ErrorNotice error={addComment.error} />}
            </section>
          </article>
          {showsDecisionPanel && (
            <aside className="panel approval-decision-panel">
              <div className="approval-decision-heading">
                <h2>{isRevisionRequested ? "审批结果" : "审批决策"}</h2>
                {isRevisionRequested && <span className="approval-status-badge revision_requested">已退回</span>}
              </div>
              {isActionable ? (
              <>
                <label>
                  决策备注
                  <textarea
                    placeholder="可选：说明同意、拒绝或退回的原因。"
                    value={decisionNote}
                    onChange={(event) => setDecisionNote(event.target.value)}
                  />
                </label>
                <label>
                  决策 Payload JSON
                  <textarea
                    className="config-editor"
                    value={decisionPayload}
                    onChange={(event) => setDecisionPayload(event.target.value)}
                  />
                </label>
                <div className="approval-actions">
                  <button disabled={act.isPending} onClick={() => runAction("approve")} type="button">同意</button>
                  <button className="danger" disabled={act.isPending} onClick={() => runAction("reject")} type="button">拒绝</button>
                  <button className="secondary" disabled={act.isPending} onClick={() => runAction("requestRevision")} type="button">
                    退回
                  </button>
                </div>
              </>
              ) : (
                <div className="approval-result-summary">
                  <span>审核意见</span>
                  <p>{approval.data.decisionNote?.trim() || "审批人未填写审核意见。"}</p>
                </div>
              )}
              {approval.data.status === "revision_requested" && (
                <details className="approval-resubmit-form">
                  <summary>
                    <span>修改并重新提交</span>
                    <small>展开编辑请求 JSON</small>
                  </summary>
                  <div>
                    <p className="muted">根据审核意见修改请求内容后，再重新提交审批。</p>
                    <label>
                      请求 Payload JSON
                      <textarea
                        className="config-editor"
                        value={resubmitPayload === "{}" ? currentPayload : resubmitPayload}
                        onChange={(event) => setResubmitPayload(event.target.value)}
                      />
                    </label>
                    <button className="secondary" disabled={act.isPending} onClick={() => runAction("resubmit")} type="button">
                      重新提交审批
                    </button>
                  </div>
                </details>
              )}
              {formError && <p className="error-notice">{formError}</p>}
            </aside>
          )}
          {act.error && <ErrorNotice error={act.error} />}
        </section>
      )}
    </ChatsWorkspace>
  );
}
