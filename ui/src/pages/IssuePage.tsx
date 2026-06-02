import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { useEffect, useState, type ChangeEvent, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { agentsApi } from "../api/agents";
import { goalsApi } from "../api/goals";
import { heartbeatApi } from "../api/heartbeat";
import { issuesApi } from "../api/issues";
import { projectsApi } from "../api/projects";
import type {
  Agent,
  Goal,
  HeartbeatRun,
  HeartbeatRunEvent,
  IssueDetail,
  IssuePriority,
  IssueReviewDecision,
  IssueStatus,
  ProjectDetail,
  UpdateIssuePayload,
  WorkspaceOperation,
} from "../api/types";
import { Badge } from "../components/Badge";
import { IssuesWorkspace } from "../components/ContextWorkspace";
import { ErrorNotice } from "../components/ErrorNotice";
import { writeRecentIssue } from "../utils/recentIssues";

const ISSUE_STATUSES: IssueStatus[] = ["backlog", "todo", "in_progress", "in_review", "done", "blocked", "cancelled"];
const ISSUE_PRIORITIES: IssuePriority[] = ["critical", "high", "medium", "low"];

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

function issueRunStorageKey(orgId: string, issueId: string): string {
  return `octopus:issue-run:${orgId}:${issueId}`;
}

function reviewDecisionBlockReason(issue: IssueDetail): string {
  if (!issue.reviewerAgentId) return "请先设置 Reviewer，当前任务不能评审。";
  if (!["in_review", "blocked"].includes(issue.status)) return "任务进入 in_review 或 blocked 后才能评审。";
  return "";
}

function markReviewBlockReason(issue: IssueDetail): string {
  if (!issue.reviewerAgentId) return "请先设置 Reviewer，当前任务不能标记为待评审。";
  if (issue.status === "in_review") return "当前任务已经是待评审状态。";
  return "";
}

function isLiveRun(status?: string | null): boolean {
  return status === "queued" || status === "running";
}

function hasJsonObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function formattedJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function runSummary(run: HeartbeatRun | null): string {
  if (!run) return "暂无执行记录";
  if (run.error?.trim()) return run.error.trim();
  const result = hasJsonObject(run.resultJson) ? run.resultJson : null;
  for (const key of ["summary", "result", "message"]) {
    const value = result?.[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return run.status;
}

function formatIssueTime(value: string | null | undefined): string {
  if (!value) return "-";
  return new Date(value).toLocaleString();
}

function IssuePropertiesPanel({
  agents,
  goals,
  issue,
  isUpdating,
  onUpdate,
  projects,
}: {
  agents: Agent[];
  goals: Goal[];
  issue: IssueDetail;
  isUpdating: boolean;
  onUpdate: (payload: UpdateIssuePayload) => void;
  projects: ProjectDetail[];
}) {
  const agentsById = new Map(agents.map((agent) => [agent.id, agent]));
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
          <span>状态</span>
          <span className="issue-property-control-row">
            <select
              disabled={isUpdating}
              value={issue.status}
              onChange={(event) => onUpdate({ status: event.target.value as IssueStatus })}
            >
              {ISSUE_STATUSES.map((status) => <option key={status} value={status}>{status}</option>)}
            </select>
            <button
              className="secondary small-button"
              disabled={isUpdating || issue.status === "in_progress"}
              onClick={() => onUpdate({ status: "in_progress" })}
              type="button"
            >
              标记进行中
            </button>
          </span>
        </label>
        <label className="issue-property-row">
          <span>优先级</span>
          <select disabled={isUpdating} value={issue.priority} onChange={(event) => onUpdate({ priority: event.target.value as IssuePriority })}>
            {ISSUE_PRIORITIES.map((priority) => <option key={priority} value={priority}>{priority}</option>)}
          </select>
        </label>
        <label className="issue-property-row">
          <span>负责人</span>
          <select
            disabled={isUpdating}
            value={nullableSelectValue(issue.assigneeAgentId)}
            onChange={(event) => onUpdate({ assigneeAgentId: event.target.value || null, assigneeUserId: null })}
          >
            <option value="">未分配</option>
            {agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}
          </select>
        </label>
        {issue.assigneeAgentId && (
          <div className="issue-property-row issue-property-link-row">
            <span>负责人链接</span>
            <Link to={`/orgs/${issue.orgId}/agents/${issue.assigneeAgentId}`}>{agentName(issue.assigneeAgentId, agentsById)}</Link>
          </div>
        )}
        <label className="issue-property-row">
          <span>Reviewer</span>
          <select
            disabled={isUpdating}
            value={nullableSelectValue(issue.reviewerAgentId)}
            onChange={(event) => onUpdate({ reviewerAgentId: event.target.value || null, reviewerUserId: null })}
          >
            <option value="">不设置</option>
            {agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}
          </select>
        </label>
        {issue.reviewerAgentId && (
          <div className="issue-property-row issue-property-link-row">
            <span>Reviewer 链接</span>
            <Link to={`/orgs/${issue.orgId}/agents/${issue.reviewerAgentId}`}>{agentName(issue.reviewerAgentId, agentsById)}</Link>
          </div>
        )}
        <label className="issue-property-row">
          <span>项目</span>
          <select
            disabled={isUpdating}
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
            disabled={isUpdating}
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
        <div className="issue-property-row"><span>已创建</span><strong>{issue.createdAt || "-"}</strong></div>
        <div className="issue-property-row"><span>已更新</span><strong>{issue.updatedAt || "-"}</strong></div>
      </div>
    </section>
  );
}

function IssueWorkProductsPanel({ issue }: { issue: IssueDetail }) {
  const workProducts = issue.workProducts ?? [];
  return (
    <section aria-label="工作产物" className="issue-section-card">
      <div className="issue-section-heading">
        <h2>工作产物</h2>
        <span className="muted">{workProducts.length}</span>
      </div>
      {workProducts.length > 0 && (
        <div className="issue-work-product-list">
          {workProducts.map((product) => (
            <article className="issue-work-product-card" key={product.id}>
              <div>
                <strong>{product.title}</strong>
                <p>{product.summary ?? product.externalId ?? product.id}</p>
              </div>
              <div className="issue-work-product-meta">
                <Badge>{product.type}</Badge>
                <Badge>{product.status}</Badge>
                <Badge>{product.reviewState}</Badge>
                {product.isPrimary && <Badge>primary</Badge>}
              </div>
              <dl className="issue-work-product-details">
                <div><dt>工作区</dt><dd>{product.executionWorkspaceId ?? "-"}</dd></div>
                <div><dt>健康状态</dt><dd>{product.healthStatus}</dd></div>
                <div><dt>运行</dt><dd>{product.createdByRunId ?? "-"}</dd></div>
                {product.assetId && <div><dt>资产</dt><dd>{product.assetId}</dd></div>}
                {product.contentType && <div><dt>类型</dt><dd>{product.contentType}</dd></div>}
                {product.byteSize !== undefined && product.byteSize !== null && <div><dt>大小</dt><dd>{product.byteSize} bytes</dd></div>}
              </dl>
              <div className="issue-work-product-actions">
                {product.contentPath && <a className="button secondary small-button" href={product.contentPath}>下载产物</a>}
                {product.url && <a className="button secondary small-button" href={product.url}>打开产物</a>}
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

interface IssueRunPanelData {
  events: UseQueryResult<HeartbeatRunEvent[], Error>;
  operations: UseQueryResult<WorkspaceOperation[], Error>;
  run: UseQueryResult<HeartbeatRun, Error>;
}

function IssueRunOutputPanel({
  data,
  onCancel,
  onRetry,
  runId,
}: {
  data: IssueRunPanelData;
  onCancel: () => void;
  onRetry: () => void;
  runId: string;
}) {
  const run = data.run.data ?? null;
  const events = data.events.data ?? [];
  const operations = data.operations.data ?? [];
  const canCancel = isLiveRun(run?.status);
  const canRetry = run?.status === "failed" || run?.status === "timed_out" || run?.status === "cancelled";
  return (
    <section aria-label="执行输出" className="issue-section-card issue-run-output">
      <div className="issue-section-heading">
        <div>
          <h2>执行输出</h2>
          <p className="muted">本面板展示当前任务最近一次由本页面触发的运行。</p>
        </div>
        <div className="issue-run-actions">
          {run && <Badge>{run.status}</Badge>}
          {run && <Link className="button secondary small-button" to={`/orgs/${run.orgId}/agents/${run.agentId}/runs`}>打开运行页</Link>}
          <button className="secondary small-button" disabled={!canCancel} onClick={onCancel} type="button">取消运行</button>
          <button className="secondary small-button" disabled={!canRetry} onClick={onRetry} type="button">重试运行</button>
        </div>
      </div>
      {data.run.error && <ErrorNotice error={data.run.error} />}
      {data.events.error && <ErrorNotice error={data.events.error} />}
      {data.operations.error && <ErrorNotice error={data.operations.error} />}
      <dl className="issue-run-summary">
        <div><dt>Run ID</dt><dd>{run?.id ?? runId}</dd></div>
        <div><dt>状态</dt><dd>{run?.status ?? "加载中"}</dd></div>
        <div><dt>开始</dt><dd>{run?.startedAt ?? "-"}</dd></div>
        <div><dt>结束</dt><dd>{run?.finishedAt ?? "-"}</dd></div>
      </dl>
      <p className="issue-run-summary-text">{runSummary(run)}</p>
      {(run?.stdoutExcerpt || run?.stderrExcerpt) && (
        <div className="issue-run-stream-list">
          {run.stdoutExcerpt && (
            <article className="agent-run-event">
              <div className="agent-run-event-header">
                <strong>stdout</strong>
                <Badge>输出</Badge>
              </div>
              <pre className="run-excerpt inline">{run.stdoutExcerpt}</pre>
            </article>
          )}
          {run.stderrExcerpt && (
            <article className="agent-run-event">
              <div className="agent-run-event-header">
                <strong>stderr</strong>
                <Badge>错误</Badge>
              </div>
              <pre className="run-excerpt error inline">{run.stderrExcerpt}</pre>
            </article>
          )}
        </div>
      )}
      <section className="issue-run-output-block issue-run-events-flat">
        <h3>事件</h3>
        {data.events.isLoading && <p className="muted">加载事件中...</p>}
        {!data.events.isLoading && events.length === 0 && <p className="muted">暂无事件。</p>}
        {events.length > 0 && (
          <div className="agent-run-events">
            {events.map((event) => (
              <article className="agent-run-event" key={event.id}>
                <div className="agent-run-event-header">
                  <span>#{event.seq}</span>
                  <strong>{event.eventType}</strong>
                  {event.level && <Badge>{event.level}</Badge>}
                  {event.stream && <Badge>{event.stream}</Badge>}
                </div>
                {event.message && <pre className="issue-run-event-log">{event.message}</pre>}
                {hasJsonObject(event.payload) && <pre className="agent-run-json issue-run-event-payload">{formattedJson(event.payload)}</pre>}
                <small className="muted">{event.createdAt}</small>
              </article>
            ))}
          </div>
        )}
      </section>
      <section className="issue-run-output-block">
        <h3>工作区操作</h3>
        {data.operations.isLoading && <p className="muted">加载工作区操作中...</p>}
        {!data.operations.isLoading && operations.length === 0 && <p className="muted">暂无工作区操作。</p>}
        {operations.length > 0 && (
          <div className="agent-run-events">
            {operations.map((operation) => (
              <article className="agent-run-event" key={operation.id}>
                <div className="agent-run-event-header">
                  <strong>{operation.phase}</strong>
                  <Badge>{operation.status}</Badge>
                  {operation.exitCode !== undefined && operation.exitCode !== null && <Badge>Exit {operation.exitCode}</Badge>}
                </div>
                {operation.command && <pre className="issue-run-event-log">{operation.command}</pre>}
                {operation.stderrExcerpt && <pre className="run-excerpt error inline">{operation.stderrExcerpt}</pre>}
                {operation.stdoutExcerpt && <pre className="run-excerpt inline">{operation.stdoutExcerpt}</pre>}
                <small className="muted">{operation.cwd ?? operation.id}</small>
              </article>
            ))}
          </div>
        )}
      </section>
    </section>
  );
}

export function IssuePage() {
  const { orgId = "", issueId = "" } = useParams();
  const navigate = useNavigate();
  const [comment, setComment] = useState("");
  const [attachmentFile, setAttachmentFile] = useState<File | null>(null);
  const [attachmentUploadNotice, setAttachmentUploadNotice] = useState("");
  const [attachmentUsage, setAttachmentUsage] = useState("attachment");
  const [executeNotice, setExecuteNotice] = useState("");
  const [subIssueTitle, setSubIssueTitle] = useState("");
  const [reviewNotice, setReviewNotice] = useState("");
  const [currentRunId, setCurrentRunId] = useState(() => {
    if (!orgId || !issueId) return "";
    return localStorage.getItem(issueRunStorageKey(orgId, issueId)) ?? "";
  });
  const queryClient = useQueryClient();
  const agents = useQuery({ queryKey: ["agents", orgId], queryFn: () => agentsApi.list(orgId) });
  const goals = useQuery({ queryKey: ["goals", orgId], queryFn: () => goalsApi.list(orgId) });
  const issue = useQuery({ queryKey: ["issue", issueId], queryFn: () => issuesApi.get(issueId) });
  const projects = useQuery({ queryKey: ["projects", orgId], queryFn: () => projectsApi.list(orgId) });
  const comments = useQuery({
    queryKey: ["comments", issueId],
    queryFn: () => issuesApi.listComments(issueId),
  });
  const attachments = useQuery({
    queryKey: ["issue-attachments", issueId],
    queryFn: () => issuesApi.listAttachments(issueId),
  });
  const issueRuns = useQuery({
    queryKey: ["issue-heartbeat-runs", issueId],
    queryFn: () => issuesApi.listRuns(issueId),
    enabled: Boolean(issueId),
    refetchInterval: (query) => query.state.data?.some((run) => isLiveRun(run.status)) ? 3000 : false,
  });
  useEffect(() => {
    if (!orgId || !issueId) return;
    setCurrentRunId(localStorage.getItem(issueRunStorageKey(orgId, issueId)) ?? "");
  }, [orgId, issueId]);
  useEffect(() => {
    if (currentRunId || !issueRuns.data?.length || !orgId || !issueId) return;
    const latestRun = issueRuns.data[0];
    localStorage.setItem(issueRunStorageKey(orgId, issueId), latestRun.id);
    setCurrentRunId(latestRun.id);
  }, [currentRunId, issueRuns.data, issueId, orgId]);
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
      return issuesApi.create(orgId, {
        title: subIssueTitle.trim(),
        parentId: issue.data.id,
        projectId: issue.data.projectId,
        goalId: issue.data.goalId,
        assigneeAgentId: issue.data.assigneeAgentId,
        reviewerAgentId: issue.data.reviewerAgentId,
        priority: issue.data.priority,
        status: "todo",
      });
    },
    onSuccess: (created) => {
      setSubIssueTitle("");
      void queryClient.invalidateQueries({ queryKey: ["issues", orgId] });
      navigate(`/orgs/${orgId}/issues/${created.id}`);
    },
  });
  const executeIssue = useMutation({
    mutationFn: async () => {
      if (!issue.data?.assigneeAgentId) throw new Error("请先分配负责人");
      if (issue.data.status !== "in_progress") {
        await issuesApi.update(issue.data.id, { status: "in_progress" });
      }
      return issuesApi.execute(issue.data.id);
    },
    onSuccess: async (run) => {
      setExecuteNotice("");
      localStorage.setItem(issueRunStorageKey(orgId, issueId), run.id);
      setCurrentRunId(run.id);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["issue", issueId] }),
        queryClient.invalidateQueries({ queryKey: ["issues", orgId] }),
        queryClient.invalidateQueries({ queryKey: ["issue-heartbeat-runs", issueId] }),
        queryClient.invalidateQueries({ queryKey: ["heartbeat-runs", orgId] }),
      ]);
    },
  });
  const runDetail = useQuery({
    queryKey: ["heartbeat-run", currentRunId],
    queryFn: () => heartbeatApi.get(currentRunId),
    enabled: Boolean(currentRunId),
    refetchInterval: (query) => isLiveRun(query.state.data?.status) ? 3000 : false,
  });
  const runEvents = useQuery({
    queryKey: ["heartbeat-run-events", currentRunId],
    queryFn: () => heartbeatApi.listEvents(currentRunId),
    enabled: Boolean(currentRunId),
    refetchInterval: () => isLiveRun(runDetail.data?.status) ? 3000 : false,
  });
  const runWorkspaceOperations = useQuery({
    queryKey: ["heartbeat-run-workspace-operations", currentRunId],
    queryFn: () => heartbeatApi.listWorkspaceOperations(currentRunId),
    enabled: Boolean(currentRunId),
    refetchInterval: () => isLiveRun(runDetail.data?.status) ? 3000 : false,
  });
  const cancelRun = useMutation({
    mutationFn: () => heartbeatApi.cancel(currentRunId),
    onSuccess: (run) => {
      queryClient.setQueryData(["heartbeat-run", currentRunId], run);
      void queryClient.invalidateQueries({ queryKey: ["issue-heartbeat-runs", issueId] });
      void queryClient.invalidateQueries({ queryKey: ["heartbeat-runs", orgId] });
    },
  });
  const retryRun = useMutation({
    mutationFn: () => heartbeatApi.retry(currentRunId),
    onSuccess: (run) => {
      localStorage.setItem(issueRunStorageKey(orgId, issueId), run.id);
      setCurrentRunId(run.id);
      queryClient.setQueryData(["heartbeat-run", run.id], run);
      void queryClient.invalidateQueries({ queryKey: ["issue-heartbeat-runs", issueId] });
      void queryClient.invalidateQueries({ queryKey: ["heartbeat-runs", orgId] });
    },
  });
  const review = useMutation({
    mutationFn: (decision: IssueReviewDecision) => issuesApi.review(issueId, { decision }),
    onSuccess: () => {
      setReviewNotice("");
      void queryClient.invalidateQueries({ queryKey: ["issue", issueId] });
    },
  });
  const uploadAttachment = useMutation({
    mutationFn: () => {
      if (!attachmentFile) throw new Error("请选择附件文件");
      return issuesApi.uploadAttachment(orgId, issueId, {
        file: attachmentFile,
        usage: attachmentUsage.trim() || "attachment",
      });
    },
    onSuccess: () => {
      setAttachmentUploadNotice(`已上传 ${attachmentFile?.name ?? "附件"}`);
      setAttachmentFile(null);
      setAttachmentUsage("attachment");
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
  function selectAttachment(event: ChangeEvent<HTMLInputElement>) {
    setAttachmentFile(event.target.files?.[0] ?? null);
    setAttachmentUploadNotice("");
  }
  function submitAttachment(event: FormEvent) {
    event.preventDefault();
    if (attachmentFile) uploadAttachment.mutate();
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
    if (uploadAttachment.isPending) {
      setExecuteNotice("附件上传中，上传完成后再执行任务。");
      return;
    }
    if (!issue.data?.assigneeAgentId) {
      setExecuteNotice("请先分配负责人，再执行任务。");
      return;
    }
    setExecuteNotice("");
    executeIssue.mutate();
  }
  if (issue.error) return <ErrorNotice error={issue.error} />;
  const agentList = Array.isArray(agents.data) ? agents.data : [];
  const agentsById = new Map(agentList.map((agent) => [agent.id, agent]));
  const goalList = Array.isArray(goals.data) ? goals.data : [];
  const projectList = Array.isArray(projects.data) ? projects.data : [];
  return (
    <IssuesWorkspace contentClassName="org-content-full" orgId={orgId}>
      {agents.error && <ErrorNotice error={agents.error} />}
      {goals.error && <ErrorNotice error={goals.error} />}
      {projects.error && <ErrorNotice error={projects.error} />}
      {issue.data && (
        <div className="issue-detail-layout">
          <main className="issue-detail-main">
            <nav aria-label="任务导航" className="issue-breadcrumb">
              <Link to={`/orgs/${orgId}/issues`}>任务</Link>
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
                  <button
                    aria-disabled={(uploadAttachment.isPending || !issue.data.assigneeAgentId) ? "true" : undefined}
                    className={(uploadAttachment.isPending || !issue.data.assigneeAgentId) ? "is-disabled" : undefined}
                    disabled={executeIssue.isPending}
                    title={
                      uploadAttachment.isPending
                        ? "附件上传中，上传完成后再执行任务"
                        : issue.data.assigneeAgentId
                          ? "触发负责人执行当前任务"
                          : "请先分配负责人"
                    }
                    type="button"
                    onClick={executeCurrentIssue}
                  >
                    执行任务
                  </button>
                  <button className="secondary small-button" type="button" onClick={() => navigator.clipboard?.writeText(issueDisplayId(issue.data))}>
                    复制 ID
                  </button>
                  <Link className="button secondary small-button" to={`/orgs/${orgId}/chats`}>聊天</Link>
                </div>
              </div>
              <p className="issue-description">{issue.data.description || "暂无描述"}</p>
            </div>
            {executeIssue.error && <ErrorNotice error={executeIssue.error} />}
            {executeNotice && <p className="issue-action-notice" role="status">{executeNotice}</p>}

            <section aria-label="子任务" className="issue-section-card">
              <div className="issue-section-heading">
                <h2>子任务</h2>
                <span className="muted">0</span>
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
            </section>

            <section aria-label="评审" className="issue-section-card">
              <div className="issue-section-heading">
                <h2>评审</h2>
                <span className="muted">当前状态：{issue.data.status}</span>
              </div>
              <div className="actions">
                <button
                  aria-disabled={Boolean(reviewDecisionBlockReason(issue.data))}
                  className={reviewDecisionBlockReason(issue.data) ? "is-disabled" : undefined}
                  disabled={review.isPending}
                  onClick={() => submitReviewDecision("approve")}
                  title={reviewDecisionBlockReason(issue.data) || "通过当前任务评审"}
                  type="button"
                >
                  通过评审
                </button>
                <button
                  aria-disabled={Boolean(reviewDecisionBlockReason(issue.data))}
                  className={`secondary${reviewDecisionBlockReason(issue.data) ? " is-disabled" : ""}`}
                  disabled={review.isPending}
                  onClick={() => submitReviewDecision("request_changes")}
                  title={reviewDecisionBlockReason(issue.data) || "请求修改当前任务"}
                  type="button"
                >
                  请求修改
                </button>
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

            {currentRunId && (
              <IssueRunOutputPanel
                data={{
                  events: runEvents,
                  operations: runWorkspaceOperations,
                  run: runDetail,
                }}
                onCancel={() => cancelRun.mutate()}
                onRetry={() => retryRun.mutate()}
                runId={currentRunId}
              />
            )}
            {cancelRun.error && <ErrorNotice error={cancelRun.error} />}
            {retryRun.error && <ErrorNotice error={retryRun.error} />}

            <IssueWorkProductsPanel issue={issue.data} />

            <section aria-label="附件" className="issue-section-card">
              <div className="issue-section-heading">
                <h2>附件</h2>
                <span className="muted">{attachments.data?.length ?? 0}</span>
              </div>
              {attachments.error && <ErrorNotice error={attachments.error} />}
              {uploadAttachment.error && <ErrorNotice error={uploadAttachment.error} />}
              {deleteAttachment.error && <ErrorNotice error={deleteAttachment.error} />}
              {uploadAttachment.isPending && attachmentFile && (
                <p className="issue-upload-status" role="status">正在上传 {attachmentFile.name}...</p>
              )}
              {!uploadAttachment.isPending && attachmentUploadNotice && (
                <p className="issue-upload-status success" role="status">{attachmentUploadNotice}</p>
              )}
              {attachments.isSuccess && attachments.data.length === 0 && <p className="muted">暂无附件。</p>}
              {attachments.data && attachments.data.length > 0 && (
                <div className="issue-attachment-list">
                  {attachments.data.map((attachment) => (
                    <article className="issue-attachment-item" key={attachment.id}>
                      <div>
                        <strong>{attachment.originalFilename ?? attachment.id}</strong>
                        <p className="muted">{attachment.usage} · {attachment.contentType} · {attachment.byteSize} bytes</p>
                      </div>
                      <div className="issue-attachment-actions">
                        <a className="button secondary small-button" href={attachment.contentPath}>下载</a>
                        <button
                          className="danger small-button"
                          disabled={deleteAttachment.isPending}
                          onClick={() => deleteAttachment.mutate(attachment.id)}
                          type="button"
                        >
                          删除
                        </button>
                      </div>
                    </article>
                  ))}
                </div>
              )}
              <form className="form issue-attachment-form" onSubmit={submitAttachment}>
                <label>
                  附件文件
                  <input onChange={selectAttachment} type="file" />
                </label>
                <label>
                  用途
                  <input value={attachmentUsage} onChange={(event) => setAttachmentUsage(event.target.value)} />
                </label>
                <button disabled={!attachmentFile || uploadAttachment.isPending} type="submit">上传附件</button>
              </form>
            </section>

            <section aria-label="动态" className="issue-section-card">
              <div className="issue-section-heading">
                <h2>动态</h2>
                <span className="muted">
                  {(comments.data?.length ?? 0) + (issueRuns.data?.length ?? 0)} 条记录
                </span>
              </div>
              {comments.error && <ErrorNotice error={comments.error} />}
              {issueRuns.error && <ErrorNotice error={issueRuns.error} />}
              <div className="issue-activity-list">
                {comments.data?.map((item) => (
                  <article className="issue-activity-item" key={item.id}>
                    <div className="issue-activity-avatar">C</div>
                    <p>{item.body}</p>
                  </article>
                ))}
                {issueRuns.data?.map((run) => (
                  <button
                    className={`issue-activity-item issue-run-activity${run.id === currentRunId ? " active" : ""}`}
                    key={run.id}
                    onClick={() => {
                      localStorage.setItem(issueRunStorageKey(orgId, issueId), run.id);
                      setCurrentRunId(run.id);
                    }}
                    type="button"
                  >
                    <div className="issue-activity-avatar">R</div>
                    <span>
                      <strong>执行任务</strong>
                      <span className="muted">
                        {run.status} · {agentName(run.agentId, agentsById)} · {formatIssueTime(run.createdAt)}
                      </span>
                    </span>
                  </button>
                ))}
                {comments.isSuccess && issueRuns.isSuccess && comments.data.length === 0 && issueRuns.data.length === 0 && (
                  <p className="muted">暂无动态。</p>
                )}
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
                  复制 ID
                </button>
                <Link className="button secondary small-button" to={`/orgs/${orgId}/chats`}>聊天</Link>
              </div>
              <IssuePropertiesPanel
                agents={agentList}
                goals={goalList}
                issue={issue.data}
                isUpdating={updateIssue.isPending}
                onUpdate={(payload) => updateIssue.mutate(payload)}
                projects={projectList}
              />
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
