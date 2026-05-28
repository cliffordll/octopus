import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { issuesApi } from "../api/issues";
import type { IssueDetail, IssueReviewDecision } from "../api/types";
import { Badge } from "../components/Badge";
import { IssuesWorkspace } from "../components/ContextWorkspace";
import { ErrorNotice } from "../components/ErrorNotice";
import { writeRecentIssue } from "../utils/recentIssues";

function issueDisplayId(issue: IssueDetail): string {
  return issue.identifier ?? issue.id.slice(0, 8);
}

function IssuePropertiesPanel({ issue }: { issue: IssueDetail }) {
  return (
    <section aria-label="Issue properties" className="panel issue-properties-card">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Properties</p>
          <h2>属性</h2>
        </div>
      </div>
      <dl className="issue-property-list">
        <div><dt>Status</dt><dd><Badge>{issue.status}</Badge></dd></div>
        <div><dt>Priority</dt><dd><Badge>{issue.priority}</Badge></dd></div>
        <div><dt>Project</dt><dd>{issue.projectId ?? "None"}</dd></div>
        <div><dt>Goal</dt><dd>{issue.goalId ?? "None"}</dd></div>
        <div><dt>Assignee</dt><dd>{issue.assigneeAgentId ?? issue.assigneeUserId ?? "None"}</dd></div>
        <div><dt>Reviewer</dt><dd>{issue.reviewerAgentId ?? issue.reviewerUserId ?? "None"}</dd></div>
        <div><dt>Parent</dt><dd>{issue.parentId ?? "None"}</dd></div>
        <div><dt>Number</dt><dd>{issue.issueNumber ?? "None"}</dd></div>
        <div><dt>Depth</dt><dd>{issue.requestDepth}</dd></div>
        <div><dt>Origin</dt><dd>{issue.originKind}</dd></div>
        <div><dt>Origin ID</dt><dd>{issue.originId ?? "None"}</dd></div>
        <div><dt>Started</dt><dd>{issue.startedAt ?? "None"}</dd></div>
        <div><dt>Completed</dt><dd>{issue.completedAt ?? "None"}</dd></div>
        <div><dt>Created</dt><dd>{issue.createdAt || "-"}</dd></div>
        <div><dt>Updated</dt><dd>{issue.updatedAt || "-"}</dd></div>
      </dl>
    </section>
  );
}

export function IssuePage() {
  const { orgId = "", issueId = "" } = useParams();
  const [comment, setComment] = useState("");
  const queryClient = useQueryClient();
  const issue = useQuery({ queryKey: ["issue", issueId], queryFn: () => issuesApi.get(issueId) });
  const comments = useQuery({
    queryKey: ["comments", issueId],
    queryFn: () => issuesApi.listComments(issueId),
  });
  const addComment = useMutation({
    mutationFn: () => issuesApi.addComment(issueId, { body: comment.trim() }),
    onSuccess: () => {
      setComment("");
      void queryClient.invalidateQueries({ queryKey: ["comments", issueId] });
    },
  });
  const updateIssue = useMutation({
    mutationFn: (payload: { status?: IssueDetail["status"] }) => issuesApi.update(issueId, payload),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["issue", issueId] }),
  });
  const review = useMutation({
    mutationFn: (decision: IssueReviewDecision) => issuesApi.review(issueId, { decision }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["issue", issueId] }),
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
  if (issue.error) return <ErrorNotice error={issue.error} />;
  return (
    <IssuesWorkspace orgId={orgId}>
      {issue.data && (
        <div className="issue-detail-layout">
          <main className="issue-detail-main">
            <nav aria-label="Issue navigation" className="issue-breadcrumb">
              <Link to={`/orgs/${orgId}/issues`}>Issues</Link>
              <span>/</span>
              <span>{issueDisplayId(issue.data)}</span>
            </nav>

            <div className="issue-detail-title-block">
              <div className="issue-detail-kicker">
                <Badge>{issueDisplayId(issue.data)}</Badge>
                <Badge>{issue.data.status}</Badge>
                <Badge>{issue.data.priority}</Badge>
              </div>
              <div className="issue-title-row">
                <h1>{issue.data.title}</h1>
                <div className="issue-header-actions">
                  <button className="secondary small-button" type="button" onClick={() => navigator.clipboard?.writeText(issueDisplayId(issue.data))}>
                    Copy ID
                  </button>
                  <Link className="button secondary small-button" to={`/orgs/${orgId}/chats`}>Chat</Link>
                </div>
              </div>
              <p className="issue-description">{issue.data.description || "Add a description..."}</p>
            </div>

            <section aria-label="Sub-issues" className="issue-section-card">
              <div className="issue-section-heading">
                <h2>Sub-issues</h2>
                <span className="muted">0</span>
              </div>
              <p className="muted">No sub-issues.</p>
            </section>

            <section aria-label="Review" className="issue-section-card">
              <div className="issue-section-heading">
                <h2>Review</h2>
                <span className="muted">当前状态：{issue.data.status}</span>
              </div>
              <div className="actions">
                <button onClick={() => review.mutate("approve")} type="button">批准 Review</button>
                <button className="secondary" onClick={() => review.mutate("request_changes")} type="button">
                  请求修改
                </button>
                <button className="secondary" onClick={() => updateIssue.mutate({ status: "in_progress" })} type="button">
                  标记进行中
                </button>
              </div>
              {review.error && <ErrorNotice error={review.error} />}
              {updateIssue.error && <ErrorNotice error={updateIssue.error} />}
            </section>

            <section aria-label="Activity" className="issue-section-card">
              <div className="issue-section-heading">
                <h2>Activity</h2>
                <span className="muted">{comments.data?.length ?? 0} comments</span>
              </div>
              {comments.error && <ErrorNotice error={comments.error} />}
              <div className="issue-activity-list">
                {comments.data?.map((item) => (
                  <article className="issue-activity-item" key={item.id}>
                    <div className="issue-activity-avatar">C</div>
                    <p>{item.body}</p>
                  </article>
                ))}
                {comments.isSuccess && comments.data.length === 0 && <p className="muted">No activity yet.</p>}
              </div>
              <form className="form issue-comment-form" onSubmit={submitComment}>
                <label>
                  添加评论
                  <textarea value={comment} onChange={(event) => setComment(event.target.value)} required />
                </label>
                <div className="issue-comment-actions">
                  <button type="submit">发送评论</button>
                </div>
              </form>
            </section>
          </main>

          <aside className="issue-detail-sidebar">
            <div className="issue-sidebar-sticky">
              <div className="issue-sidebar-actions">
                <button className="secondary small-button" type="button" onClick={() => navigator.clipboard?.writeText(issue.data.id)}>
                  Copy ID
                </button>
                <Link className="button secondary small-button" to={`/orgs/${orgId}/chats`}>Chat</Link>
              </div>
              <IssuePropertiesPanel issue={issue.data} />
            </div>
          </aside>
        </div>
      )}
      {!issue.data && (
        <header className="page-header">
          <div>
            <Link className="back-link" to={`/orgs/${orgId}/issues`}>返回 Issues</Link>
            <h1>载入中...</h1>
          </div>
        </header>
      )}
    </IssuesWorkspace>
  );
}
