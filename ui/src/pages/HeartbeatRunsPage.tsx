import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { agentsApi } from "../api/agents";
import { heartbeatApi } from "../api/heartbeat";
import { Badge } from "../components/Badge";
import { ErrorNotice } from "../components/ErrorNotice";
import { OrgWorkspace } from "./OrganizationPage";
import { Link, useParams } from "react-router-dom";
import type { Agent, HeartbeatRun } from "../api/types";

function formatRunTime(value?: string | null): string {
  if (!value) return "无";
  return value;
}

function summarizeRun(run: HeartbeatRun | null): string {
  if (!run) return "暂无运行";
  if (run.error?.trim()) return run.error.trim();
  const summary = run.resultJson?.summary ?? run.resultJson?.result ?? run.resultJson?.message;
  return typeof summary === "string" && summary.trim() ? summary.trim() : run.id;
}

function latestRunByAgent(runs: HeartbeatRun[]): Map<string, HeartbeatRun> {
  const map = new Map<string, HeartbeatRun>();
  for (const run of runs) {
    if (!map.has(run.agentId)) map.set(run.agentId, run);
  }
  return map;
}

function runStatusLabel(status: HeartbeatRun["status"]): string {
  const labels: Record<HeartbeatRun["status"], string> = {
    queued: "Queued",
    running: "Running",
    succeeded: "Succeeded",
    failed: "Failed",
    cancelled: "Cancelled",
    timed_out: "Timed out",
  };
  return labels[status] ?? status;
}

function runUsageMetric(run: HeartbeatRun, key: string): string {
  const value = run.usageJson?.[key];
  if (typeof value === "number") return String(value);
  if (typeof value === "string" && value.trim()) return value;
  return "-";
}

function RunUsageSummary({ run }: { run: HeartbeatRun }) {
  if (!run.usageJson || Object.keys(run.usageJson).length === 0) return null;
  return (
    <div className="agent-run-metrics">
      <div><span>Input</span><strong>{runUsageMetric(run, "inputTokens")}</strong></div>
      <div><span>Output</span><strong>{runUsageMetric(run, "outputTokens")}</strong></div>
      <div><span>Cached</span><strong>{runUsageMetric(run, "cachedInputTokens")}</strong></div>
      <div><span>Cost</span><strong>{runUsageMetric(run, "costCents")}</strong></div>
    </div>
  );
}

function stringField(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function WorkspaceContextSummary({ run }: { run: HeartbeatRun }) {
  const snapshot = run.contextSnapshot;
  const workspaceContext = snapshot?.workspace;
  const workspace =
    workspaceContext && typeof workspaceContext === "object" && !Array.isArray(workspaceContext)
      ? (workspaceContext as Record<string, unknown>).rudderWorkspace
      : null;
  const workspaceRecord =
    workspace && typeof workspace === "object" && !Array.isArray(workspace)
      ? (workspace as Record<string, unknown>)
      : {};
  const executionWorkspaceId = stringField(snapshot?.executionWorkspaceId) ?? stringField(workspaceRecord.id);
  const projectWorkspaceId = stringField(snapshot?.projectWorkspaceId);
  const cwd = stringField(workspaceRecord.cwd);
  const branchName = stringField(workspaceRecord.branchName);
  const status = stringField(workspaceRecord.status);
  if (!executionWorkspaceId && !projectWorkspaceId && !cwd && !branchName && !status) return null;
  return (
    <section className="workspace-context-card" aria-label="执行工作区">
      <div className="project-workspace-card-heading">
        <h3>执行工作区</h3>
        {status && <Badge>{status}</Badge>}
      </div>
      <dl className="detail-grid compact">
        {executionWorkspaceId && <div><dt>执行工作区 ID</dt><dd>{executionWorkspaceId}</dd></div>}
        {projectWorkspaceId && <div><dt>项目工作区 ID</dt><dd>{projectWorkspaceId}</dd></div>}
        {branchName && <div><dt>分支</dt><dd>{branchName}</dd></div>}
        {cwd && <div><dt>目录</dt><dd>{cwd}</dd></div>}
      </dl>
    </section>
  );
}

function AgentHeartbeatRow({
  agent,
  latestRun,
  runCount,
  onRunNow,
  starting,
}: {
  agent: Agent;
  latestRun: HeartbeatRun | null;
  runCount: number;
  onRunNow: () => void;
  starting: boolean;
}) {
  return (
    <article className="heartbeat-agent-row">
      <div className="heartbeat-agent-main">
        <Link to={`/orgs/${agent.orgId}/agents/${agent.id}`}>{agent.name}</Link>
        <span>{agent.title ?? agent.role} · {agent.status}</span>
      </div>
      <div>
        <strong>{agent.lastHeartbeatAt ?? "从未"}</strong>
        <span>最近心跳</span>
      </div>
      <div>
        <strong>{latestRun ? runStatusLabel(latestRun.status) : "No runs"}</strong>
        <span>{runCount} runs · {summarizeRun(latestRun)}</span>
      </div>
      <div className="heartbeat-agent-actions">
        <button disabled={starting || agent.status === "terminated"} onClick={onRunNow} type="button">
          {starting ? "Starting..." : "运行心跳"}
        </button>
      </div>
    </article>
  );
}

export function HeartbeatRunsPage() {
  const { orgId = "" } = useParams();
  const queryClient = useQueryClient();
  const [agentId, setAgentId] = useState("");
  const [selectedRunId, setSelectedRunId] = useState("");
  const [afterSeq, setAfterSeq] = useState("0");
  const [eventLimit, setEventLimit] = useState("200");
  const eventAfterSeq = Number(afterSeq) || 0;
  const eventLimitValue = Number(eventLimit) || 1;
  const agents = useQuery({ queryKey: ["agents", orgId], queryFn: () => agentsApi.list(orgId) });
  const runs = useQuery({
    queryKey: ["heartbeat-runs", orgId, agentId],
    queryFn: () => heartbeatApi.list(orgId, agentId || undefined),
  });
  const detail = useQuery({
    queryKey: ["heartbeat-run", selectedRunId],
    queryFn: () => heartbeatApi.get(selectedRunId),
    enabled: Boolean(selectedRunId),
  });
  const events = useQuery({
    queryKey: ["heartbeat-run-events", selectedRunId, eventAfterSeq, eventLimitValue],
    queryFn: () => heartbeatApi.listEvents(selectedRunId, { afterSeq: eventAfterSeq, limit: eventLimitValue }),
    enabled: Boolean(selectedRunId),
  });
  const cancelRun = useMutation({
    mutationFn: (runId: string) => heartbeatApi.cancel(runId),
    onSuccess: async (run) => {
      queryClient.setQueryData(["heartbeat-run", run.id], run);
      await queryClient.invalidateQueries({ queryKey: ["heartbeat-runs", orgId] });
      await queryClient.invalidateQueries({ queryKey: ["heartbeat-run-events", run.id] });
    },
  });
  const retryRun = useMutation({
    mutationFn: (runId: string) => heartbeatApi.retry(runId),
    onSuccess: async (run) => {
      queryClient.setQueryData(["heartbeat-run", run.id], run);
      await queryClient.invalidateQueries({ queryKey: ["heartbeat-runs", orgId] });
      setSelectedRunId(run.id);
    },
  });
  const invokeRun = useMutation({
    mutationFn: (targetAgentId: string) => heartbeatApi.invoke(targetAgentId),
    onSuccess: async (run) => {
      await queryClient.invalidateQueries({ queryKey: ["heartbeat-runs", orgId] });
      setSelectedRunId(run.id);
    },
  });
  const agentList = Array.isArray(agents.data) ? agents.data : [];
  const agentNameById = new Map(agentList.map((agent) => [agent.id, agent.name]));
  const sortedRuns = useMemo(
    () => [...(runs.data ?? [])].sort((a, b) => String(b.createdAt ?? "").localeCompare(String(a.createdAt ?? ""))),
    [runs.data],
  );
  const latestByAgent = useMemo(() => latestRunByAgent(sortedRuns), [sortedRuns]);
  const runCountsByAgent = useMemo(() => {
    const counts = new Map<string, number>();
    for (const run of sortedRuns) counts.set(run.agentId, (counts.get(run.agentId) ?? 0) + 1);
    return counts;
  }, [sortedRuns]);
  const visibleAgents = agentId ? agentList.filter((agent) => agent.id === agentId) : agentList;
  const runningCount = sortedRuns.filter((run) => run.status === "running" || run.status === "queued").length;
  const failedCount = sortedRuns.filter((run) => run.status === "failed" || run.status === "timed_out").length;
  const succeededCount = sortedRuns.filter((run) => run.status === "succeeded").length;

  useEffect(() => {
    setSelectedRunId("");
  }, [agentId]);

  useEffect(() => {
    if (!runs.isSuccess || selectedRunId || sortedRuns.length === 0) return;
    setSelectedRunId(sortedRuns[0].id);
  }, [runs.isSuccess, selectedRunId, sortedRuns]);

  return (
    <OrgWorkspace orgId={orgId}>
      <header className="page-header heartbeat-page-header">
        <div>
          <p className="eyebrow">Organization</p>
          <h1>心跳</h1>
          <p className="muted">按智能体查看心跳运行状态，并打开具体运行检查事件与输出。</p>
        </div>
        <label className="heartbeat-filter">
          智能体筛选
          <select value={agentId} onChange={(event) => setAgentId(event.target.value)}>
            <option value="">全部智能体</option>
            {agentList.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}
          </select>
        </label>
      </header>
      {agents.error && <ErrorNotice error={agents.error} />}
      {runs.error && <ErrorNotice error={runs.error} />}
      {cancelRun.error && <ErrorNotice error={cancelRun.error} />}
      {retryRun.error && <ErrorNotice error={retryRun.error} />}
      {invokeRun.error && <ErrorNotice error={invokeRun.error} />}

      <div className="heartbeat-summary-grid">
        <div className="summary-metric"><span>Runs</span><strong>{sortedRuns.length}</strong></div>
        <div className="summary-metric"><span>Active</span><strong>{runningCount}</strong></div>
        <div className="summary-metric"><span>Succeeded</span><strong>{succeededCount}</strong></div>
        <div className="summary-metric"><span>Failed</span><strong>{failedCount}</strong></div>
      </div>

      <section className="panel heartbeat-agents">
        <div className="panel-heading">
          <div>
            <h2>智能体</h2>
            <p className="muted">参考上游组织心跳页，一行一个智能体，集中展示最近心跳和最近运行。</p>
          </div>
        </div>
        {visibleAgents.length === 0 && <p className="muted">暂无智能体。</p>}
        <div className="heartbeat-agent-list">
          {visibleAgents.map((agent) => (
            <AgentHeartbeatRow
              agent={agent}
              key={agent.id}
              latestRun={latestByAgent.get(agent.id) ?? null}
              onRunNow={() => invokeRun.mutate(agent.id)}
              runCount={runCountsByAgent.get(agent.id) ?? 0}
              starting={invokeRun.isPending && invokeRun.variables === agent.id}
            />
          ))}
        </div>
      </section>

      <div className="heartbeat-inspection-layout">
        <section className="panel heartbeat-detail">
          <div className="panel-heading">
            <div>
              <h2>运行详情</h2>
              <p className="muted">详情区优先展示当前运行，运行列表收在右侧。</p>
            </div>
            {detail.data && (
              <div className="actions">
                <button
                  disabled={cancelRun.isPending || !["queued", "running"].includes(detail.data.status)}
                  onClick={() => cancelRun.mutate(detail.data.id)}
                  type="button"
                >
                  取消运行
                </button>
                <button
                  disabled={retryRun.isPending || !["failed", "cancelled", "timed_out"].includes(detail.data.status)}
                  onClick={() => retryRun.mutate(detail.data.id)}
                  type="button"
                >
                  重试运行
                </button>
              </div>
            )}
          </div>
          {!selectedRunId && <p className="muted">选择一条运行记录查看事件。</p>}
          {detail.error && <ErrorNotice error={detail.error} />}
          {events.error && <ErrorNotice error={events.error} />}
          {detail.data && (
            <div className="heartbeat-detail-summary run-summary-card">
              <div className="meta-line">
                <Badge>{detail.data.status}</Badge>
                <Badge>{detail.data.invocationSource}</Badge>
                {detail.data.triggerDetail && <Badge>{detail.data.triggerDetail}</Badge>}
                {detail.data.processPid && <Badge>PID {detail.data.processPid}</Badge>}
              </div>
              <dl className="detail-grid compact">
                <div><dt>智能体</dt><dd>{agentNameById.get(detail.data.agentId) ?? detail.data.agentId}</dd></div>
                <div><dt>运行 ID</dt><dd>{detail.data.id}</dd></div>
                <div><dt>重试来源</dt><dd>{detail.data.retryOfRunId ?? "无"}</dd></div>
                <div><dt>退出码</dt><dd>{detail.data.exitCode ?? "无"}</dd></div>
                <div><dt>开始时间</dt><dd>{formatRunTime(detail.data.startedAt)}</dd></div>
                <div><dt>结束时间</dt><dd>{formatRunTime(detail.data.finishedAt)}</dd></div>
              </dl>
              <RunUsageSummary run={detail.data} />
              <WorkspaceContextSummary run={detail.data} />
              {(detail.data.sessionIdBefore || detail.data.sessionIdAfter) && (
                <dl className="agent-run-session">
                  <div><dt>Session Before</dt><dd>{detail.data.sessionIdBefore ?? "无"}</dd></div>
                  <div><dt>Session After</dt><dd>{detail.data.sessionIdAfter ?? "无"}</dd></div>
                </dl>
              )}
            </div>
          )}
          {detail.data?.error && <p className="error-notice">{detail.data.error}</p>}
          {detail.data?.stdoutExcerpt && <pre className="run-excerpt">{detail.data.stdoutExcerpt}</pre>}
          {detail.data?.stderrExcerpt && <pre className="run-excerpt error">{detail.data.stderrExcerpt}</pre>}
          {selectedRunId && (
            <div className="heartbeat-event-controls">
              <label>afterSeq
                <input min="0" type="number" value={afterSeq} onChange={(event) => setAfterSeq(event.target.value)} />
              </label>
              <label>limit
                <input min="1" type="number" value={eventLimit} onChange={(event) => setEventLimit(event.target.value)} />
              </label>
              <button type="button" onClick={() => void events.refetch()}>刷新事件</button>
            </div>
          )}
          <div className="heartbeat-events">
            {events.data?.map((event) => (
              <article className="heartbeat-event" key={event.id}>
                <div>
                  <strong>{event.eventType}</strong>
                  <span>#{event.seq} · {event.createdAt}</span>
                </div>
                <p>{event.message ?? "无消息"}</p>
              </article>
            ))}
          </div>
        </section>

        <aside className="panel heartbeat-run-rail">
          <div className="panel-heading">
            <div>
              <h2>运行记录</h2>
              <p className="muted">最近运行</p>
            </div>
          </div>
          {runs.isSuccess && sortedRuns.length === 0 && <p className="muted">暂无心跳运行记录。</p>}
          {sortedRuns.map((run) => (
            <button
              aria-label={`${run.id} ${agentNameById.get(run.agentId) ?? run.agentId} ${run.status}`}
              className={`heartbeat-run ${selectedRunId === run.id ? "selected" : ""}`}
              key={run.id}
              onClick={() => setSelectedRunId(run.id)}
              type="button"
            >
              <span>
                <strong>{run.id.slice(0, 8)}</strong>
                <small>{agentNameById.get(run.agentId) ?? run.agentId}</small>
                <small>{summarizeRun(run)}</small>
              </span>
              <Badge>{run.status}</Badge>
            </button>
          ))}
        </aside>
      </div>
    </OrgWorkspace>
  );
}
