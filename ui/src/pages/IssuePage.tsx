import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { useEffect, useRef, useState, type ChangeEvent, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
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
  IssueListItem,
  IssuePriority,
  IssueReviewDecision,
  IssueStatus,
  LogReadResult,
  ProjectDetail,
  UpdateIssuePayload,
  WorkspaceOperation,
} from "../api/types";
import { Badge } from "../components/Badge";
import { IssuesWorkspace } from "../components/ContextWorkspace";
import { ErrorNotice } from "../components/ErrorNotice";
import { formatBytes, formatDateTime, priorityLabel, statusLabel } from "../utils/display";
import { writeRecentIssue } from "../utils/recentIssues";

const ISSUE_STATUSES: IssueStatus[] = ["backlog", "todo", "in_progress", "in_review", "done", "blocked", "cancelled"];
const ISSUE_PRIORITIES: IssuePriority[] = ["critical", "high", "medium", "low"];
const LIVE_RUN_REFETCH_MS = 1000;
const AGENT_REPLY_COLLAPSE_CHARS = 600;
const AGENT_REPLY_COLLAPSE_LINES = 8;

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
      return "需要跟进";
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

function isRerunnableRun(status?: string | null): boolean {
  return status === "failed" || status === "timed_out" || status === "cancelled";
}

function isTerminalRun(status?: string | null): boolean {
  return status === "succeeded" || isRerunnableRun(status);
}

function heartbeatRunId(run: HeartbeatRun | null | undefined): string {
  return run?.id || run?.runId || "";
}

function runSortTime(run: HeartbeatRun): number {
  const value = run.createdAt ?? run.startedAt ?? run.updatedAt ?? "";
  const time = Date.parse(value);
  return Number.isNaN(time) ? 0 : time;
}

function latestIssueRun(runs: HeartbeatRun[], currentRun: HeartbeatRun | null): HeartbeatRun | null {
  const merged = new Map<string, HeartbeatRun>();
  for (const run of runs) {
    const id = heartbeatRunId(run);
    if (id) merged.set(id, run);
  }
  if (currentRun) {
    const id = heartbeatRunId(currentRun);
    if (id) merged.set(id, { ...merged.get(id), ...currentRun });
  }
  const sorted = Array.from(merged.values()).sort((left, right) => runSortTime(right) - runSortTime(left));
  return sorted[0] ?? null;
}

function metadataText(metadata: Record<string, unknown> | null | undefined, key: string): string {
  const value = metadata?.[key];
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

function nextLogOffset(log: LogReadResult): number | null {
  if (typeof log.nextOffset === "number") return log.nextOffset;
  if (typeof log.endOffset === "number") return log.endOffset;
  return null;
}

function isWorkspaceProvisionOperation(operation: WorkspaceOperation): boolean {
  return operation.phase === "workspace_provision";
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

function runSummary(run: HeartbeatRun | null): string {
  if (!run) return "暂无运行记录";
  if (run.error?.trim()) return run.error.trim();
  const result = hasJsonObject(run.resultJson) ? run.resultJson : null;
  for (const key of ["summary", "result", "message"]) {
    const value = result?.[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return statusLabel(run.status);
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
  if (isTextRunEvent(event)) return "Agent 回复";
  if (eventType.includes("queued")) return "入队";
  if (eventType.includes("started") || eventType.includes("running")) return "开始";
  if (eventType.includes("adapter") || eventType.includes("runtime")) return "调用 adapter";
  if (eventType.includes("succeeded") || eventType.includes("completed")) return "成功";
  if (eventType.includes("cancel")) return "取消";
  return event.eventType;
}

function runEventBody(event: HeartbeatRunEvent): string {
  return eventPayloadText(event.payload) || event.message || "";
}

function shouldCollapseAgentReply(body: string): boolean {
  return body.length > AGENT_REPLY_COLLAPSE_CHARS || body.split(/\r?\n/).length > AGENT_REPLY_COLLAPSE_LINES;
}

function agentReplyPreview(body: string): string {
  const lines = body.split(/\r?\n/);
  const linePreview = lines.slice(0, AGENT_REPLY_COLLAPSE_LINES).join("\n");
  const preview = linePreview.length > AGENT_REPLY_COLLAPSE_CHARS
    ? `${linePreview.slice(0, AGENT_REPLY_COLLAPSE_CHARS).trimEnd()}...`
    : linePreview;
  return lines.length > AGENT_REPLY_COLLAPSE_LINES && !preview.endsWith("...") ? `${preview}\n...` : preview;
}

function AgentReplyBody({ body }: { body: string }) {
  const shouldCollapse = shouldCollapseAgentReply(body);
  const [expanded, setExpanded] = useState(!shouldCollapse);
  return (
    <div className="issue-run-agent-reply-block">
      <p className={`issue-run-agent-reply${shouldCollapse && !expanded ? " collapsed" : ""}`}>
        {expanded ? body : agentReplyPreview(body)}
      </p>
      {shouldCollapse && (
        <button
          className="secondary small-button issue-run-agent-reply-toggle"
          onClick={() => setExpanded((value) => !value)}
          type="button"
        >
          {expanded ? "收起回复" : "展开完整回复"}
        </button>
      )}
    </div>
  );
}

function formatIssueTime(value: string | null | undefined): string {
  return formatDateTime(value);
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
          <span>任务阶段</span>
          <select
            disabled={isUpdating}
            value={issue.status}
            onChange={(event) => onUpdate({ status: event.target.value as IssueStatus })}
          >
            {ISSUE_STATUSES.map((status) => <option key={status} value={status}>{statusLabel(status)}</option>)}
          </select>
        </label>
        <label className="issue-property-row">
          <span>优先级</span>
          <select disabled={isUpdating} value={issue.priority} onChange={(event) => onUpdate({ priority: event.target.value as IssuePriority })}>
            {ISSUE_PRIORITIES.map((priority) => <option key={priority} value={priority}>{priorityLabel(priority)}</option>)}
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
        <div className="issue-property-row"><span>已创建</span><strong>{formatDateTime(issue.createdAt)}</strong></div>
        <div className="issue-property-row"><span>已更新</span><strong>{formatDateTime(issue.updatedAt)}</strong></div>
      </div>
    </section>
  );
}

function IssueWorkProductsPanel({ issue, latestRunStatus }: { issue: IssueDetail; latestRunStatus?: HeartbeatRun["status"] }) {
  const queryClient = useQueryClient();
  const workProductsQuery = useQuery({
    queryKey: ["issue-work-products", issue.id],
    queryFn: () => issuesApi.listWorkProducts(issue.id),
    initialData: issue.workProducts ?? [],
  });
  const workProducts = workProductsQuery.data ?? [];
  const deleteWorkProduct = useMutation({
    mutationFn: (workProductId: string) => issuesApi.deleteWorkProduct(workProductId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["issue-work-products", issue.id] });
      void queryClient.invalidateQueries({ queryKey: ["issue", issue.id] });
    },
  });
  return (
    <section aria-label="运行产物" className="issue-section-card">
      <div className="issue-section-heading">
        <h2>运行产物</h2>
        <span className="muted">{workProducts.length}</span>
      </div>
      <p className="muted issue-work-product-hint">
        运行产物是智能体执行后生成并由 server 记录的交付文件。下载只读取 contentPath，不会写入本地工作区。
      </p>
      {workProductsQuery.error && <ErrorNotice error={workProductsQuery.error} />}
      {workProductsQuery.isLoading && <p className="muted">加载工作产物中...</p>}
      {!workProductsQuery.isLoading && workProducts.length === 0 && (
        <p className="muted">
          {latestRunStatus === "succeeded"
            ? "最新运行已成功，但 server 没有登记受管产物。可能没有生成文件，或文件写到了工作区 / artifacts 之外的路径。"
            : "暂无运行产物。任务执行成功后，server 会把受管工作区或 artifacts 中的产物登记到这里。"}
        </p>
      )}
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
                <Badge>{statusLabel(product.status)}</Badge>
                <Badge>{statusLabel(product.reviewState)}</Badge>
                {product.isPrimary && <Badge>primary</Badge>}
              </div>
              <dl className="issue-work-product-details">
                <div><dt>工作区</dt><dd>{product.executionWorkspaceId ?? "-"}</dd></div>
                <div><dt>工作区路径</dt><dd>{metadataText(product.metadata, "workspacePath")}</dd></div>
                <div><dt>来源</dt><dd>{metadataText(product.metadata, "source")}</dd></div>
                <div><dt>健康状态</dt><dd>{product.healthStatus}</dd></div>
                <div><dt>运行</dt><dd>{product.createdByRunId ?? "-"}</dd></div>
                {product.assetId && <div><dt>资产</dt><dd>{product.assetId}</dd></div>}
              </dl>
              <details className="storage-object-details">
                <summary>存储对象</summary>
                <dl className="issue-work-product-details">
                  <div><dt>provider</dt><dd>{product.provider}</dd></div>
                  <div><dt>大小</dt><dd>{product.byteSize !== undefined && product.byteSize !== null ? formatBytes(product.byteSize) : "-"}</dd></div>
                  <div><dt>contentType</dt><dd>{product.contentType ?? "-"}</dd></div>
                  <div><dt>sha256</dt><dd>{product.sha256 ?? "-"}</dd></div>
                </dl>
              </details>
              <div className="issue-work-product-actions">
                {product.contentPath ? (
                  <>
                    <a className="button secondary small-button" href={product.contentPath}>下载运行产物</a>
                    <a className="button secondary small-button" href={product.contentPath} target="_blank" rel="noreferrer">预览内容</a>
                  </>
                ) : (
                  <span className="download-unavailable">不可下载</span>
                )}
                {product.url && <a className="button secondary small-button" href={product.url}>打开运行产物</a>}
                <button
                  className="danger small-button"
                  disabled={deleteWorkProduct.isPending}
                  onClick={() => deleteWorkProduct.mutate(product.id)}
                  type="button"
                >
                  删除产物
                </button>
              </div>
            </article>
          ))}
        </div>
      )}
      {deleteWorkProduct.error && <ErrorNotice error={deleteWorkProduct.error} />}
    </section>
  );
}

function IssueDocumentsPanel({ issueId }: { issueId: string }) {
  const queryClient = useQueryClient();
  const [documentsHidden, setDocumentsHidden] = useState(false);
  const [selectedKey, setSelectedKey] = useState<string>("");
  const [draftKey, setDraftKey] = useState("");
  const [draftTitle, setDraftTitle] = useState("");
  const [draftBody, setDraftBody] = useState("");
  const [changeSummary, setChangeSummary] = useState("");
  const documents = useQuery({
    queryKey: ["issue-documents", issueId],
    queryFn: () => issuesApi.listDocuments(issueId),
  });
  useEffect(() => {
    if (selectedKey || !documents.data?.[0]) return;
    setSelectedKey(documents.data[0].key);
  }, [documents.data, selectedKey]);
  const document = useQuery({
    queryKey: ["issue-document", issueId, selectedKey],
    queryFn: () => issuesApi.getDocument(issueId, selectedKey),
    enabled: Boolean(selectedKey),
  });
  const revisions = useQuery({
    queryKey: ["issue-document-revisions", issueId, selectedKey],
    queryFn: () => issuesApi.listDocumentRevisions(issueId, selectedKey),
    enabled: Boolean(selectedKey),
  });
  useEffect(() => {
    if (!document.data) return;
    setDraftKey(document.data.key);
    setDraftTitle(document.data.title ?? "");
    setDraftBody(document.data.body);
    setChangeSummary("");
  }, [document.data]);
  const saveDocument = useMutation({
    mutationFn: () => issuesApi.upsertDocument(issueId, draftKey.trim(), {
      title: draftTitle.trim() || null,
      format: "markdown",
      body: draftBody,
      changeSummary: changeSummary.trim() || null,
      baseRevisionId: document.data?.latestRevisionId ?? null,
    }),
    onSuccess: (saved) => {
      setSelectedKey(saved.key);
      void queryClient.invalidateQueries({ queryKey: ["issue", issueId] });
      void queryClient.invalidateQueries({ queryKey: ["issue-documents", issueId] });
      void queryClient.invalidateQueries({ queryKey: ["issue-document", issueId, saved.key] });
      void queryClient.invalidateQueries({ queryKey: ["issue-document-revisions", issueId, saved.key] });
    },
  });
  const deleteDocument = useMutation({
    mutationFn: () => issuesApi.deleteDocument(issueId, selectedKey),
    onSuccess: () => {
      setSelectedKey("");
      setDraftKey("");
      setDraftTitle("");
      setDraftBody("");
      setChangeSummary("");
      void queryClient.invalidateQueries({ queryKey: ["issue", issueId] });
      void queryClient.invalidateQueries({ queryKey: ["issue-documents", issueId] });
    },
  });
  function startNewDocument() {
    setSelectedKey("");
    setDraftKey("");
    setDraftTitle("");
    setDraftBody("");
    setChangeSummary("");
  }
  const canSave = Boolean(draftKey.trim() && draftBody.trim());
  return (
    <section aria-label="任务文档" className="issue-section-card">
      <div className="issue-section-heading">
        <h2>任务文档</h2>
        <div className="issue-section-heading-actions">
          <span className="muted">{documents.data?.length ?? 0}</span>
          <button
            className="secondary small-button"
            onClick={() => setDocumentsHidden((value) => !value)}
            type="button"
          >
            {documentsHidden ? "显示" : "隐藏"}
          </button>
        </div>
      </div>
      {!documentsHidden && (
        <>
          <p className="muted issue-work-product-hint">
            文档由 server 按任务保存，支持查看正文、编辑保存、查看历史版本和删除。
          </p>
          {documents.error && <ErrorNotice error={documents.error} />}
          <div className="issue-documents-layout">
            <aside className="issue-document-list" aria-label="文档列表">
              <button className="secondary small-button" onClick={startNewDocument} type="button">新建文档</button>
              {documents.isLoading && <p className="muted">加载文档中...</p>}
              {documents.isSuccess && documents.data.length === 0 && <p className="muted">暂无文档。</p>}
              {documents.data?.map((item) => (
                <button
                  className={selectedKey === item.key ? "active" : ""}
                  key={item.id}
                  onClick={() => setSelectedKey(item.key)}
                  type="button"
                >
                  <strong>{item.title || item.key}</strong>
                  <span>{item.key} · v{item.latestRevisionNumber}</span>
                </button>
              ))}
            </aside>
            <div className="issue-document-editor">
              {document.error && <ErrorNotice error={document.error} />}
              <div className="issue-document-fields">
                <label>
                  文档 key
                  <input
                    disabled={Boolean(document.data)}
                    placeholder="plan"
                    value={draftKey}
                    onChange={(event) => setDraftKey(event.target.value)}
                  />
                </label>
                <label>
                  标题
                  <input value={draftTitle} onChange={(event) => setDraftTitle(event.target.value)} />
                </label>
              </div>
              <label>
                正文
                <textarea
                  className="issue-document-body"
                  placeholder="输入 Markdown 文档内容"
                  value={draftBody}
                  onChange={(event) => setDraftBody(event.target.value)}
                />
              </label>
              <label>
                变更说明
                <input value={changeSummary} onChange={(event) => setChangeSummary(event.target.value)} />
              </label>
              <div className="issue-work-product-actions">
                <button disabled={!canSave || saveDocument.isPending} onClick={() => saveDocument.mutate()} type="button">
                  保存文档
                </button>
                <button
                  className="danger small-button"
                  disabled={!selectedKey || deleteDocument.isPending}
                  onClick={() => deleteDocument.mutate()}
                  type="button"
                >
                  删除文档
                </button>
              </div>
              {saveDocument.error && <ErrorNotice error={saveDocument.error} />}
              {deleteDocument.error && <ErrorNotice error={deleteDocument.error} />}
              <details className="storage-object-details">
                <summary>历史版本</summary>
                {revisions.error && <ErrorNotice error={revisions.error} />}
                {revisions.isLoading && selectedKey && <p className="muted">加载历史版本中...</p>}
                {revisions.data?.map((revision) => (
                  <article className="issue-document-revision" key={revision.id}>
                    <strong>v{revision.revisionNumber}</strong>
                    <span>{revision.changeSummary || "无变更说明"} · {formatDateTime(revision.createdAt)}</span>
                  </article>
                ))}
                {revisions.isSuccess && revisions.data.length === 0 && <p className="muted">暂无历史版本。</p>}
              </details>
            </div>
          </div>
        </>
      )}
    </section>
  );
}

function IssueRunsPanel({
  agentsById,
  currentRun,
  currentRunId,
  onSelect,
  runs,
}: {
  agentsById: Map<string, Agent>;
  currentRun: HeartbeatRun | null;
  currentRunId: string;
  onSelect: (runId: string) => void;
  runs: HeartbeatRun[];
}) {
  return (
    <section aria-label="运行记录" className="issue-section-card">
      <div className="issue-section-heading">
        <h2>运行记录</h2>
        <span className="muted">{runs.length} 次运行</span>
      </div>
      {runs.length === 0 ? (
        <p className="muted">暂无运行记录。</p>
      ) : (
        <div className="issue-run-record-list">
          {runs.map((run) => {
            const runId = heartbeatRunId(run);
            const displayRun = heartbeatRunId(currentRun) === runId ? { ...run, ...currentRun } : run;
            const summary = runSummary(displayRun);
            return (
              <button
                className={`issue-run-record${runId === currentRunId ? " active" : ""}`}
                key={runId}
                onClick={() => onSelect(runId)}
                type="button"
              >
                <div className="issue-run-record-header">
                  <strong>{runId}</strong>
                  <Badge>{statusLabel(displayRun.status)}</Badge>
                </div>
                <dl className="issue-run-record-meta">
                  <div><dt>执行智能体</dt><dd>{agentName(displayRun.agentId, agentsById)}</dd></div>
                  <div><dt>创建时间</dt><dd>{formatIssueTime(displayRun.createdAt)}</dd></div>
                  <div><dt>开始时间</dt><dd>{formatIssueTime(displayRun.startedAt)}</dd></div>
                </dl>
                {summary && (
                  <p className="issue-run-record-summary">
                    <span>运行输出摘要</span>
                    {summary}
                  </p>
                )}
              </button>
            );
          })}
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
      {content && <AutoScrollPre className={preClassName} content={content} />}
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

function IssueRunOutputPanel({
  data,
  onCancel,
  onRetry,
  runId,
  streamActive,
  streamError,
  streamLog,
}: {
  data: IssueRunPanelData;
  onCancel: () => void;
  onRetry: () => void;
  runId: string;
  streamActive: boolean;
  streamError: string | null;
  streamLog: string;
}) {
  const [selectedOperationLogId, setSelectedOperationLogId] = useState("");
  const [showEvents, setShowEvents] = useState(true);
  const [showRunLog, setShowRunLog] = useState(true);
  const [showDebugOutput, setShowDebugOutput] = useState(false);
  const [showLowValueEvents, setShowLowValueEvents] = useState(false);
  const run = data.run.data ?? null;
  const events = data.events.data ?? [];
  const operations = data.operations.data ?? [];
  const visibleEvents = events.filter((event) => !isLowValueRunEvent(event));
  const lowValueEvents = events.filter(isLowValueRunEvent);
  const hasRawOutput = Boolean(run?.stdoutExcerpt || run?.stderrExcerpt || operations.some((operation) => operation.command || operation.stdoutExcerpt || operation.stderrExcerpt));
  const operationLog = useQuery({
    queryKey: ["workspace-operation-log", selectedOperationLogId],
    queryFn: () => heartbeatApi.getWorkspaceOperationLog(selectedOperationLogId),
    enabled: Boolean(selectedOperationLogId),
    refetchInterval: () => isLiveRun(run?.status) ? LIVE_RUN_REFETCH_MS : false,
  });
  const runLog = useQuery({
    queryKey: ["heartbeat-run-log", runId],
    queryFn: () => heartbeatApi.getLog(runId),
    enabled: Boolean(runId),
    refetchInterval: () => isLiveRun(run?.status) ? LIVE_RUN_REFETCH_MS : false,
  });
  const canCancel = isLiveRun(run?.status);
  const canRetry = run?.status === "failed" || run?.status === "timed_out" || run?.status === "cancelled";
  const liveRun = isLiveRun(run?.status);
  return (
    <section aria-label="执行输出" className="issue-section-card issue-run-output">
      <div className="issue-section-heading">
        <div>
          <h2>执行输出</h2>
          <p className="muted">
            本面板展示当前任务最近一次由本页面触发的运行。{liveRun ? "运行中会通过 stream 动态刷新事件和输出。" : ""}
          </p>
        </div>
        <div className="issue-run-actions">
          {streamActive && <Badge>stream 连接中</Badge>}
          {liveRun && !streamActive && <Badge>动态刷新中</Badge>}
          {run && <Badge>{statusLabel(run.status)}</Badge>}
          {run && <Link className="button secondary small-button" to={`/orgs/${run.orgId}/agents/${run.agentId}/runs`}>打开运行页</Link>}
          <button className="secondary small-button" disabled={!canCancel} onClick={onCancel} type="button">取消运行</button>
          <button className="secondary small-button" disabled={!canRetry} onClick={onRetry} type="button">重试运行</button>
        </div>
      </div>
      {data.run.error && <ErrorNotice error={data.run.error} />}
      {data.events.error && <ErrorNotice error={data.events.error} />}
      {data.operations.error && <ErrorNotice error={data.operations.error} />}
      {runLog.error && <ErrorNotice error={runLog.error} />}
      {streamError && <p className="error-notice">{streamError}</p>}
      <section className="issue-run-output-block">
        <h3>运行详情</h3>
        <dl className="issue-run-summary">
          <div><dt>Run ID</dt><dd>{heartbeatRunId(run) || runId}</dd></div>
          <div><dt>状态</dt><dd>{run ? statusLabel(run.status) : "加载中"}</dd></div>
          <div><dt>开始</dt><dd>{run?.startedAt ?? "-"}</dd></div>
          <div><dt>结束</dt><dd>{run?.finishedAt ?? "-"}</dd></div>
        </dl>
        <div className="issue-run-summary-text">
          <span>最新执行摘要</span>
          <p>{runSummary(run)}</p>
        </div>
        {run && (
          <details className="issue-run-inline-details">
            <summary>查看 result/context/usage</summary>
            <div className="issue-run-output-grid">
              {hasJsonObject(run.resultJson) && (
                <div>
                  <span className="agent-run-section-label">resultJson</span>
                  <pre className="agent-run-json">{formattedJson(run.resultJson)}</pre>
                </div>
              )}
              {hasJsonObject(run.contextSnapshot) && (
                <div>
                  <span className="agent-run-section-label">contextSnapshot</span>
                  <pre className="agent-run-json">{formattedJson(run.contextSnapshot)}</pre>
                </div>
              )}
              {hasJsonObject(run.usageJson) && (
                <div>
                  <span className="agent-run-section-label">usageJson</span>
                  <pre className="agent-run-json">{formattedJson(run.usageJson)}</pre>
                </div>
              )}
            </div>
          </details>
        )}
      </section>
      {streamLog && (
        <section className="issue-run-output-block">
          <div className="issue-run-output-heading">
            <h3>实时日志</h3>
            <Badge>stream log</Badge>
          </div>
          <AutoScrollPre className="run-excerpt inline" content={streamLog} />
        </section>
      )}
      <section className="issue-run-output-block">
        <div className="issue-run-output-heading">
          <h3>运行日志</h3>
          <div className="issue-run-operation-actions">
            {showRunLog && runLog.data?.eof === false && <Badge>可继续读取</Badge>}
            <button className="secondary small-button" type="button" onClick={() => setShowRunLog((value) => !value)}>
              {showRunLog ? "隐藏运行日志" : "显示运行日志"}
            </button>
          </div>
        </div>
        {!showRunLog ? (
          <p className="muted">运行日志已隐藏。</p>
        ) : (
          <PaginatedLogView
            emptyText="暂无运行日志。"
            loadMore={(offset) => heartbeatApi.getLog(runId, { offset })}
            loadingText="加载运行日志中..."
            log={runLog}
            preClassName="run-excerpt inline"
          />
        )}
      </section>
      <section className="issue-run-output-block issue-run-events-flat">
        <div className="issue-run-output-heading">
          <h3>事件</h3>
          <div className="issue-run-operation-actions">
            <button className="secondary small-button" type="button" onClick={() => setShowEvents((value) => !value)}>
              {showEvents ? "隐藏事件" : `显示事件 ${events.length}`}
            </button>
            {showEvents && lowValueEvents.length > 0 && (
              <button className="secondary small-button" type="button" onClick={() => setShowLowValueEvents((value) => !value)}>
                {showLowValueEvents ? "隐藏低价值事件" : `显示低价值事件 ${lowValueEvents.length}`}
              </button>
            )}
          </div>
        </div>
        {!showEvents ? (
          <p className="muted">事件已隐藏。</p>
        ) : (
          <>
            {data.events.isLoading && <p className="muted">加载事件中...</p>}
            {!data.events.isLoading && events.length === 0 && <p className="muted">暂无事件。</p>}
            {visibleEvents.length > 0 && (
              <div className="agent-run-events">
                {visibleEvents.map((event) => (
                  <article className={`agent-run-event issue-run-timeline-event${isErrorRunEvent(event) ? " error" : ""}${isTextRunEvent(event) ? " agent-reply" : ""}`} key={event.id}>
                    <div className="agent-run-event-header">
                      <span>#{event.seq}</span>
                      <strong>{runEventLabel(event)}</strong>
                      <Badge>{event.eventType}</Badge>
                      {event.level && <Badge>{statusLabel(event.level)}</Badge>}
                      {event.stream && <Badge>{event.stream}</Badge>}
                    </div>
                    {runEventBody(event) && (
                      isTextRunEvent(event) && !isErrorRunEvent(event)
                        ? <AgentReplyBody body={runEventBody(event)} />
                        : <pre className={`issue-run-event-log${isErrorRunEvent(event) ? " error" : ""}`}>{runEventBody(event)}</pre>
                    )}
                    {hasJsonObject(event.payload) && (
                      <details className="issue-run-inline-details">
                        <summary>事件详情</summary>
                        <pre className="agent-run-json issue-run-event-payload">{formattedJson(event.payload)}</pre>
                      </details>
                    )}
                    <small className="muted">{formatDateTime(event.createdAt)}</small>
                  </article>
                ))}
              </div>
            )}
            {showLowValueEvents && lowValueEvents.length > 0 && (
              <div className="issue-run-low-value-events">
                {lowValueEvents.map((event) => (
                  <article className="agent-run-event compact" key={event.id}>
                    <div className="agent-run-event-header">
                      <span>#{event.seq}</span>
                      <strong>{event.eventType}</strong>
                    </div>
                    {event.message && <p className="muted">{event.message}</p>}
                  </article>
                ))}
              </div>
            )}
          </>
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
                  <Badge>{statusLabel(operation.status)}</Badge>
                  {operation.exitCode !== undefined && operation.exitCode !== null && <Badge>Exit {operation.exitCode}</Badge>}
                </div>
                {operation.command && <p className="muted">{operation.command}</p>}
                {operation.stderrExcerpt && <pre className="run-excerpt error inline">{operation.stderrExcerpt}</pre>}
                <small className="muted">{operation.cwd ?? operation.id}</small>
                <div className="issue-run-operation-actions">
                  <button
                    className="secondary small-button"
                    type="button"
                    onClick={() => setSelectedOperationLogId((current) => current === operation.id ? "" : operation.id)}
                  >
                    {selectedOperationLogId === operation.id ? "收起步骤日志" : "查看该步骤日志"}
                  </button>
                  {operation.logBytes !== undefined && operation.logBytes !== null && (
                    <span className="muted">{formatBytes(operation.logBytes)}</span>
                  )}
                </div>
                {selectedOperationLogId === operation.id && (
                  <div className="issue-run-operation-log">
                    {isWorkspaceProvisionOperation(operation) && (
                      <p className="muted">该日志为运行日志中的 workspace_provision 片段。</p>
                    )}
                    {operationLog.error && <ErrorNotice error={operationLog.error} />}
                    <PaginatedLogView
                      emptyText="暂无操作日志。"
                      loadMore={(offset) => heartbeatApi.getWorkspaceOperationLog(operation.id, { offset })}
                      loadingText="加载操作日志中..."
                      log={operationLog}
                      preClassName="issue-run-event-log"
                    />
                  </div>
                )}
              </article>
            ))}
          </div>
        )}
      </section>
      <section className="issue-run-output-block issue-run-debug-output">
        <div className="issue-run-output-heading">
          <h3>调试 / Raw output</h3>
          <button className="secondary small-button" disabled={!hasRawOutput} type="button" onClick={() => setShowDebugOutput((value) => !value)}>
            {showDebugOutput ? "收起" : "展开"}
          </button>
        </div>
        {!hasRawOutput && <p className="muted">暂无原始输出。</p>}
        {showDebugOutput && hasRawOutput && (
          <div className="issue-run-stream-list">
            {run?.stdoutExcerpt && (
              <article className="agent-run-event">
                <div className="agent-run-event-header">
                  <strong>stdout</strong>
                  <Badge>原始输出</Badge>
                </div>
                <pre className="run-excerpt inline">{run.stdoutExcerpt}</pre>
              </article>
            )}
            {run?.stderrExcerpt && (
              <article className="agent-run-event error">
                <div className="agent-run-event-header">
                  <strong>stderr</strong>
                  <Badge>错误</Badge>
                </div>
                <pre className="run-excerpt error inline">{run.stderrExcerpt}</pre>
              </article>
            )}
            {operations.map((operation) => (
              <article className="agent-run-event" key={operation.id}>
                <div className="agent-run-event-header">
                  <strong>{operation.phase}</strong>
                  <Badge>{statusLabel(operation.status)}</Badge>
                </div>
                {operation.command && <pre className="issue-run-event-log">{operation.command}</pre>}
                {operation.stderrExcerpt && <pre className="run-excerpt error inline">{operation.stderrExcerpt}</pre>}
                {operation.stdoutExcerpt && <pre className="run-excerpt inline">{operation.stdoutExcerpt}</pre>}
                <button
                  className="secondary small-button"
                  type="button"
                  onClick={() => setSelectedOperationLogId(operation.id)}
                >
                  查看完整日志
                </button>
                {selectedOperationLogId === operation.id && (
                  <div className="issue-run-operation-log">
                    {operationLog.isLoading && <p className="muted">加载完整日志中...</p>}
                    {operationLog.error && <ErrorNotice error={operationLog.error} />}
                    {operationLog.data?.content && <pre className="issue-run-event-log">{operationLog.data.content}</pre>}
                  </div>
                )}
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
  const [comment, setComment] = useState("");
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
  const streamCursorRef = useRef<Record<string, RunStreamCursor>>({});
  const refreshedTerminalRunRef = useRef("");
  const [streamActiveRunId, setStreamActiveRunId] = useState("");
  const [streamErrorsByRun, setStreamErrorsByRun] = useState<Record<string, string | null>>({});
  const [streamLogsByRun, setStreamLogsByRun] = useState<Record<string, string>>({});
  const queryClient = useQueryClient();
  const agents = useQuery({ queryKey: ["agents", orgId], queryFn: () => agentsApi.list(orgId) });
  const goals = useQuery({ queryKey: ["goals", orgId], queryFn: () => goalsApi.list(orgId) });
  const issue = useQuery({ queryKey: ["issue", issueId], queryFn: () => issuesApi.get(issueId) });
  const heartbeatContext = useQuery({
    queryKey: ["issue-heartbeat-context", issueId],
    queryFn: () => issuesApi.heartbeatContext(issueId),
    enabled: Boolean(issueId),
  });
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
    refetchInterval: (query) => query.state.data?.some((run) => isLiveRun(run.status)) ? LIVE_RUN_REFETCH_MS : false,
  });
  const subIssues = useQuery({
    queryKey: ["issues", orgId, "children", issueId],
    queryFn: () => issuesApi.list(orgId, { parentId: issueId }),
    enabled: Boolean(orgId && issueId),
  });
  useEffect(() => {
    if (!orgId || !issueId) return;
    setCurrentRunId(localStorage.getItem(issueRunStorageKey(orgId, issueId)) ?? "");
  }, [orgId, issueId]);
  useEffect(() => {
    if (currentRunId || !issueRuns.data?.length || !orgId || !issueId) return;
    const latestRun = issueRuns.data[0];
    const latestRunId = heartbeatRunId(latestRun);
    if (!latestRunId) return;
    localStorage.setItem(issueRunStorageKey(orgId, issueId), latestRunId);
    setCurrentRunId(latestRunId);
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
      queryClient.setQueryData<IssueListItem[]>(["issues", orgId, "children", issueId], (current = []) => [
        ...current.filter((item) => item.id !== created.id),
        created,
      ]);
      void queryClient.invalidateQueries({ queryKey: ["issues", orgId, "children", issueId] });
      void queryClient.invalidateQueries({ queryKey: ["issues", orgId] });
    },
  });
  function resetRunStreamState(runId: string) {
    streamCursorRef.current[runId] = { lastSeq: 0, nextOffset: 0 };
    setStreamErrorsByRun((current) => ({ ...current, [runId]: null }));
    setStreamLogsByRun((current) => ({ ...current, [runId]: "" }));
  }
  const executeIssue = useMutation({
    mutationFn: async () => {
      if (!issue.data?.assigneeAgentId) throw new Error("请先分配负责人");
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
        resetRunStreamState(runId);
        setCurrentRunId(runId);
        queryClient.setQueryData<HeartbeatRun>(["heartbeat-run", runId], (current) => ({
          ...current,
          ...run,
        }));
      } else {
        setExecuteNotice("执行请求已提交，暂未返回新的运行记录，正在刷新任务运行。");
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["issue", issueId] }),
        queryClient.invalidateQueries({ queryKey: ["issues", orgId] }),
        queryClient.invalidateQueries({ queryKey: ["issue-heartbeat-runs", issueId] }),
        queryClient.invalidateQueries({ queryKey: ["heartbeat-runs", orgId] }),
        queryClient.invalidateQueries({ queryKey: ["heartbeat-run", currentRunId] }),
        queryClient.invalidateQueries({ queryKey: ["heartbeat-run-events", currentRunId] }),
      ]);
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
  const runDetail = useQuery({
    queryKey: ["heartbeat-run", currentRunId],
    queryFn: () => heartbeatApi.get(currentRunId),
    enabled: Boolean(currentRunId),
    refetchInterval: (query) => isLiveRun(query.state.data?.status) ? LIVE_RUN_REFETCH_MS : false,
  });
  const runEvents = useQuery({
    queryKey: ["heartbeat-run-events", currentRunId],
    queryFn: async () => {
      const fetched = await heartbeatApi.listEvents(currentRunId);
      const cached = queryClient.getQueryData<HeartbeatRunEvent[]>(["heartbeat-run-events", currentRunId]) ?? [];
      return mergeRunEvents(cached, fetched);
    },
    enabled: Boolean(currentRunId),
    refetchInterval: () => isLiveRun(runDetail.data?.status) ? LIVE_RUN_REFETCH_MS : false,
  });
  const runWorkspaceOperations = useQuery({
    queryKey: ["heartbeat-run-workspace-operations", currentRunId],
    queryFn: () => heartbeatApi.listWorkspaceOperations(currentRunId),
    enabled: Boolean(currentRunId),
    refetchInterval: () => isLiveRun(runDetail.data?.status) ? LIVE_RUN_REFETCH_MS : false,
  });
  useEffect(() => {
    if (!currentRunId || !isLiveRun(runDetail.data?.status)) return;
    const cursor = streamCursorRef.current[currentRunId] ?? { lastSeq: 0, nextOffset: 0 };
    streamCursorRef.current[currentRunId] = cursor;
    const controller = new AbortController();
    setStreamActiveRunId(currentRunId);
    setStreamErrorsByRun((current) => ({ ...current, [currentRunId]: null }));
    void heartbeatApi.streamRun(currentRunId, {
      afterSeq: cursor.lastSeq,
      offset: cursor.nextOffset,
      pollMs: LIVE_RUN_REFETCH_MS,
      signal: controller.signal,
      onRun: (run) => {
        queryClient.setQueryData<HeartbeatRun>(["heartbeat-run", currentRunId], (current) => ({
          ...current,
          ...run,
        }));
      },
      onEvent: (event) => {
        cursor.lastSeq = Math.max(cursor.lastSeq, event.seq);
        queryClient.setQueryData<HeartbeatRunEvent[]>(["heartbeat-run-events", currentRunId], (current = []) => {
          return mergeRunEvents(current, [event]);
        });
      },
      onLog: (payload) => {
        if (typeof payload.nextOffset === "number") cursor.nextOffset = payload.nextOffset;
        if (!payload.content) return;
        setStreamLogsByRun((current) => ({
          ...current,
          [currentRunId]: `${current[currentRunId] ?? ""}${payload.content}`,
        }));
      },
      onFinal: (run) => {
        queryClient.setQueryData<HeartbeatRun>(["heartbeat-run", currentRunId], (current) => ({
          ...current,
          ...run,
        }));
        setStreamActiveRunId((activeRunId) => activeRunId === currentRunId ? "" : activeRunId);
        void queryClient.invalidateQueries({ queryKey: ["issue", issueId] });
        void queryClient.invalidateQueries({ queryKey: ["issues", orgId] });
        void queryClient.invalidateQueries({ queryKey: ["issue-heartbeat-runs", issueId] });
        void queryClient.invalidateQueries({ queryKey: ["heartbeat-runs", orgId] });
        void queryClient.invalidateQueries({ queryKey: ["issue-documents", issueId] });
        void queryClient.invalidateQueries({ queryKey: ["issue-work-products", issueId] });
      },
      onError: (error) => {
        setStreamErrorsByRun((current) => ({ ...current, [currentRunId]: error }));
        setStreamActiveRunId((activeRunId) => activeRunId === currentRunId ? "" : activeRunId);
      },
    }).catch((error: unknown) => {
      if (controller.signal.aborted) return;
      setStreamErrorsByRun((current) => ({
        ...current,
        [currentRunId]: error instanceof Error ? error.message : "Run stream failed",
      }));
    }).finally(() => {
      if (controller.signal.aborted) return;
      setStreamActiveRunId((activeRunId) => activeRunId === currentRunId ? "" : activeRunId);
    });
    return () => {
      controller.abort();
      setStreamActiveRunId((activeRunId) => activeRunId === currentRunId ? "" : activeRunId);
    };
  }, [currentRunId, issueId, orgId, queryClient, runDetail.data?.status]);
  useEffect(() => {
    const latestRun = latestIssueRun(issueRuns.data ?? [], runDetail.data ?? null);
    const latestRunId = heartbeatRunId(latestRun);
    if (!latestRunId || !isTerminalRun(latestRun?.status)) return;
    const refreshKey = `${latestRunId}:${latestRun?.status}`;
    if (refreshedTerminalRunRef.current === refreshKey) return;
    refreshedTerminalRunRef.current = refreshKey;
    void queryClient.invalidateQueries({ queryKey: ["issue", issueId] });
    void queryClient.invalidateQueries({ queryKey: ["issue-documents", issueId] });
    void queryClient.invalidateQueries({ queryKey: ["issue-work-products", issueId] });
  }, [issueId, issueRuns.data, queryClient, runDetail.data]);
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
      const runId = heartbeatRunId(run);
      localStorage.setItem(issueRunStorageKey(orgId, issueId), runId);
      resetRunStreamState(runId);
      setCurrentRunId(runId);
      queryClient.setQueryData<HeartbeatRun>(["heartbeat-run", runId], (current) => ({
        ...current,
        ...run,
      }));
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
    const latestRun = latestIssueRun(issueRuns.data ?? [], runDetail.data ?? null);
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
    setExecuteNotice(isRerunnableRun(latestRun?.status) ? "正在提交重新执行请求..." : "正在提交执行请求...");
    executeIssue.mutate();
  }
  if (issue.error) return <ErrorNotice error={issue.error} />;
  const agentList = Array.isArray(agents.data) ? agents.data : [];
  const agentsById = new Map(agentList.map((agent) => [agent.id, agent]));
  const goalList = Array.isArray(goals.data) ? goals.data : [];
  const projectList = Array.isArray(projects.data) ? projects.data : [];
  const subIssueList = Array.isArray(subIssues.data) ? subIssues.data : [];
  const latestRun = latestIssueRun(issueRuns.data ?? [], runDetail.data ?? null);
  const latestRunIsLive = isLiveRun(latestRun?.status);
  const latestRunCanReexecute = isRerunnableRun(latestRun?.status);
  const latestRunSucceeded = latestRun?.status === "succeeded";
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
      : issue.data?.assigneeAgentId
        ? ""
        : "请先分配负责人";
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
                <Badge>{statusLabel(issue.data.status)}</Badge>
                <Badge>{priorityLabel(issue.data.priority)}</Badge>
                {latestRun && <Badge>运行：{statusLabel(latestRun.status)}</Badge>}
              </div>
              <div className="issue-title-row">
                <h1>{issue.data.title}</h1>
                <div className="issue-header-actions">
                  <button
                    aria-disabled={executeBlockReason ? "true" : undefined}
                    className={executeBlockReason ? "is-disabled" : undefined}
                    disabled={executeIssue.isPending}
                    title={executeBlockReason || (latestRunCanReexecute ? "重新交给负责人启动一次运行" : "交给负责人启动一次运行")}
                    type="button"
                    onClick={executeCurrentIssue}
                  >
                    {executeButtonLabel}
                  </button>
                  <button
                    className="secondary small-button"
                    disabled={checkoutIssue.isPending || !issue.data.assigneeAgentId}
                    title={issue.data.assigneeAgentId ? "由当前负责人签出任务" : "请先分配负责人"}
                    type="button"
                    onClick={() => checkoutIssue.mutate()}
                  >
                    签出任务
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
            {checkoutIssue.error && <ErrorNotice error={checkoutIssue.error} />}
            {executeNotice && <p className="issue-action-notice" role="status">{executeNotice}</p>}
            {latestRun && isRerunnableRun(latestRun.status) && latestRun.error?.trim() && (
              <p className="error-notice" role="status">
                最新运行{statusLabel(latestRun.status)}：{latestRun.error.trim()}
              </p>
            )}

            <section aria-label="心跳上下文" className="issue-section-card">
              <div className="issue-section-heading">
                <h2>心跳上下文</h2>
                <span className="muted">任务执行时传给运行时的上下文</span>
              </div>
              {heartbeatContext.isLoading && <p className="muted">加载上下文中...</p>}
              {heartbeatContext.error && <ErrorNotice error={heartbeatContext.error} />}
              {heartbeatContext.data && <pre className="agent-run-json">{formattedJson(heartbeatContext.data)}</pre>}
            </section>

            <section aria-label="子任务" className="issue-section-card">
              <div className="issue-section-heading">
                <h2>子任务</h2>
                <span className="muted">{subIssueList.length}</span>
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
                      <span className="issue-subtask-meta">
                        <Badge>{child.status}</Badge>
                        <Badge>{child.priority}</Badge>
                      </span>
                    </Link>
                  ))}
                </div>
              )}
            </section>

            <section aria-label="评审" className="issue-section-card">
              <div className="issue-section-heading">
                <h2>评审</h2>
                <span className="muted">当前阶段：{statusLabel(issue.data.status)}</span>
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

            <IssueRunsPanel
              agentsById={agentsById}
              currentRun={runDetail.data ?? null}
              currentRunId={currentRunId}
              runs={issueRuns.data ?? []}
              onSelect={(runId) => {
                localStorage.setItem(issueRunStorageKey(orgId, issueId), runId);
                setCurrentRunId(runId);
              }}
            />

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
                streamActive={streamActiveRunId === currentRunId}
                streamError={streamErrorsByRun[currentRunId] ?? null}
                streamLog={streamLogsByRun[currentRunId] ?? ""}
              />
            )}
            {cancelRun.error && <ErrorNotice error={cancelRun.error} />}
            {retryRun.error && <ErrorNotice error={retryRun.error} />}

            <IssueDocumentsPanel issueId={issueId} />

            <IssueWorkProductsPanel issue={issue.data} latestRunStatus={latestRun?.status} />

            <section aria-label="动态" className="issue-section-card">
              <div className="issue-section-heading">
                <h2>动态</h2>
                <span className="muted">
                  {comments.data?.length ?? 0} 条评论 · {attachments.data?.length ?? 0} 个文件
                </span>
              </div>
              {comments.error && <ErrorNotice error={comments.error} />}
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
                {comments.data?.map((item) => (
                  <article className="issue-activity-item" key={item.id}>
                    <div className="issue-activity-avatar">C</div>
                    <p>{item.body}</p>
                  </article>
                ))}
                {comments.isSuccess && comments.data.length === 0 && (
                  <p className="muted">暂无动态。</p>
                )}
              </div>
              <form className="form issue-comment-form" onSubmit={submitComment}>
                <label>
                  添加评论
                  <textarea value={comment} onChange={(event) => setComment(event.target.value)} required />
                </label>
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
