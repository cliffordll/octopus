import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { approvalsApi } from "../api/approvals";
import { Badge } from "../components/Badge";
import { ChatsWorkspace } from "../components/ContextWorkspace";
import { ErrorNotice } from "../components/ErrorNotice";
import { formatDateTime, statusLabel } from "../utils/display";

function formatPayload(value: unknown): string {
  return JSON.stringify(value ?? {}, null, 2);
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
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["approval", approvalId] }),
    onError: (error) => setFormError(error instanceof Error ? error.message : "审批操作失败"),
  });
  const addComment = useMutation({
    mutationFn: () => approvalsApi.addComment(approvalId, { body: commentBody.trim() }),
    onSuccess: () => {
      setCommentBody("");
      void queryClient.invalidateQueries({ queryKey: ["approval-comments", approvalId] });
    },
  });
  function runAction(action: "approve" | "reject" | "requestRevision" | "resubmit") {
    setFormError(null);
    act.mutate(action);
  }
  if (approval.error) return <ErrorNotice error={approval.error} />;
  const isActionable = approval.data?.status === "pending";
  const currentPayload = approval.data ? formatPayload(approval.data.payload) : "{}";
  return (
    <ChatsWorkspace contentClassName="org-content-full" orgId={orgId}>
      <header className="page-header">
        <div>
          <Link className="back-link" to={`/orgs/${orgId}/approvals`}>返回审批管理</Link>
          <p className="eyebrow">Approval</p>
          <h1>{approval.data?.type ?? "载入中..."}</h1>
          <p className="muted">在消息上下文中查看完整请求并做出决策。</p>
        </div>
      </header>
      {approval.data && (
        <section className="approval-detail-layout">
          <article className="panel approval-detail">
            <div className="approval-card-header">
              <div>
                <p className="eyebrow">审批对象</p>
                <h2>{approval.data.type}</h2>
              </div>
              <Badge>{statusLabel(approval.data.status)}</Badge>
            </div>
            <dl className="detail-grid">
              <div>
                <dt>审批 ID</dt>
                <dd>{approval.data.id}</dd>
              </div>
              <div>
                <dt>发起时间</dt>
                <dd>{formatDateTime(approval.data.createdAt)}</dd>
              </div>
              <div>
                <dt>发起智能体</dt>
                <dd>{approval.data.requestedByAgentId ?? "无"}</dd>
              </div>
              <div>
                <dt>决策人</dt>
                <dd>{approval.data.decidedByUserId ?? "未决策"}</dd>
              </div>
            </dl>
            {approval.data.decisionNote && (
              <div className="approval-note">
                <span>Decision note</span>
                <p>{approval.data.decisionNote}</p>
              </div>
            )}
            <h3>完整请求</h3>
            <pre>{JSON.stringify(approval.data.payload, null, 2)}</pre>
            <h3>关联任务</h3>
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
            <h3>评论</h3>
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
            {addComment.error && <ErrorNotice error={addComment.error} />}
          </article>
          <aside className="panel approval-decision-panel">
            <h2>审批决策</h2>
            {isActionable ? (
              <>
                <label>
                  决策备注
                  <textarea
                    placeholder="可选：说明同意、拒绝或请求修改的原因。"
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
                <div className="actions">
                  <button disabled={act.isPending} onClick={() => runAction("approve")} type="button">同意</button>
                  <button className="danger" disabled={act.isPending} onClick={() => runAction("reject")} type="button">拒绝</button>
                  <button className="secondary" disabled={act.isPending} onClick={() => runAction("requestRevision")} type="button">
                    请求修改
                  </button>
                </div>
              </>
            ) : (
              <p className="muted">该审批已处理，当前状态为 {statusLabel(approval.data.status)}。</p>
            )}
            {approval.data.status === "revision_requested" && (
              <div className="approval-resubmit-form">
                <label>
                  重新提交 Payload JSON
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
            )}
            {formError && <p className="error-notice">{formError}</p>}
          </aside>
          {act.error && <ErrorNotice error={act.error} />}
        </section>
      )}
    </ChatsWorkspace>
  );
}
