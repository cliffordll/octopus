import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { issuesApi } from "../api/issues";
import type { IssueReviewDecision } from "../api/types";
import { Badge } from "../components/Badge";
import { IssuesWorkspace } from "../components/ContextWorkspace";
import { ErrorNotice } from "../components/ErrorNotice";

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
  const review = useMutation({
    mutationFn: (decision: IssueReviewDecision) => issuesApi.review(issueId, { decision }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["issue", issueId] }),
  });
  function submitComment(event: FormEvent) {
    event.preventDefault();
    if (comment.trim()) addComment.mutate();
  }
  if (issue.error) return <ErrorNotice error={issue.error} />;
  return (
    <IssuesWorkspace orgId={orgId}>
      <header className="page-header">
        <div>
          <Link className="back-link" to={`/orgs/${orgId}/issues`}>返回 Issues</Link>
          <h1>{issue.data?.title ?? "载入中..."}</h1>
        </div>
      </header>
      {issue.data && (
        <div className="grid-two detail-grid">
          <section className="panel">
            <div className="meta-line">
              <Badge>{issue.data.identifier ?? "Issue"}</Badge>
              <Badge>{issue.data.status}</Badge>
              <Badge>{issue.data.priority}</Badge>
            </div>
            <p className="description">{issue.data.description || "没有描述。"}</p>
            <h2>Review</h2>
            <div className="actions">
              <button onClick={() => review.mutate("approve")} type="button">批准 Review</button>
              <button className="secondary" onClick={() => review.mutate("request_changes")} type="button">
                请求修改
              </button>
            </div>
            {review.error && <ErrorNotice error={review.error} />}
          </section>
          <section className="panel">
            <h2>评论</h2>
            {comments.error && <ErrorNotice error={comments.error} />}
            <div className="comments">
              {comments.data?.map((item) => <p key={item.id}>{item.body}</p>)}
            </div>
            <form className="form" onSubmit={submitComment}>
              <label>
                添加评论
                <textarea value={comment} onChange={(event) => setComment(event.target.value)} required />
              </label>
              <button type="submit">发送评论</button>
            </form>
          </section>
        </div>
      )}
    </IssuesWorkspace>
  );
}
