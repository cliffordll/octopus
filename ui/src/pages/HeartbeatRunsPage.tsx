import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";
import { Link, useParams } from "react-router-dom";
import { agentsApi } from "../api/agents";
import { heartbeatApi } from "../api/heartbeat";
import type { Agent, HeartbeatRun } from "../api/types";
import { ErrorNotice } from "../components/ErrorNotice";
import { OrgWorkspace } from "./OrganizationPage";

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function humanize(value?: string | null): string {
  if (!value) return "none";
  return value;
}

function relativeTime(value?: string | null): string {
  if (!value) return "从未";
  const timestamp = new Date(value).getTime();
  if (Number.isNaN(timestamp)) return value;
  const diffMs = Date.now() - timestamp;
  const abs = Math.abs(diffMs);
  const minute = 60 * 1000;
  const hour = 60 * minute;
  const day = 24 * hour;
  if (abs < minute) return diffMs >= 0 ? "刚刚" : "即将";
  if (abs < hour) return `${Math.round(abs / minute)} 分钟${diffMs >= 0 ? "前" : "后"}`;
  if (abs < day) return `${Math.round(abs / hour)} 小时${diffMs >= 0 ? "前" : "后"}`;
  return `${Math.round(abs / day)} 天${diffMs >= 0 ? "前" : "后"}`;
}

function formatDateTime(value?: string | null): string | undefined {
  if (!value) return undefined;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function latestRunSummary(run: HeartbeatRun | null): string | null {
  if (!run) return null;
  if (run.error?.trim()) return run.error.trim();
  const result = asRecord(run.resultJson);
  for (const key of ["summary", "result", "message"]) {
    const value = result?.[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return null;
}

function heartbeatConfig(agent: Agent): Record<string, unknown> {
  const runtimeConfig = asRecord(agent.runtimeConfig) ?? asRecord(agent.agentRuntimeConfig) ?? {};
  return asRecord(runtimeConfig.heartbeat) ?? {};
}

function heartbeatEnabled(agent: Agent): boolean {
  const heartbeat = heartbeatConfig(agent);
  return heartbeat.enabled === true || heartbeat.timerEnabled === true || heartbeat.enabled === "true";
}

function heartbeatIntervalSec(agent: Agent): number {
  const heartbeat = heartbeatConfig(agent);
  const raw = heartbeat.intervalSec ?? heartbeat.intervalSeconds ?? heartbeat.interval;
  if (typeof raw === "number" && Number.isFinite(raw)) return raw;
  if (typeof raw === "string" && raw.trim()) return Number(raw) || 0;
  return 0;
}

function buildHeartbeatPatch(agent: Agent, enabled: boolean): { agentRuntimeConfig: Record<string, unknown> } {
  const runtimeConfig = { ...(asRecord(agent.agentRuntimeConfig) ?? {}) };
  const heartbeat = { ...(asRecord(runtimeConfig.heartbeat) ?? {}) };
  return {
    agentRuntimeConfig: {
      ...runtimeConfig,
      heartbeat: {
        ...heartbeat,
        enabled,
      },
    },
  };
}

function schedulerState(agent: Agent): { className: string; label: string } {
  if (heartbeatEnabled(agent) && heartbeatIntervalSec(agent) > 0) {
    return { className: "heartbeat-state-success", label: "scheduled" };
  }
  if (heartbeatEnabled(agent)) {
    return { className: "heartbeat-state-warning", label: "configured_inactive" };
  }
  return { className: "heartbeat-state-muted", label: "disabled" };
}

function latestRunState(run: HeartbeatRun | null): { className: string; label: string } {
  if (!run) return { className: "heartbeat-state-muted", label: "no_run" };
  if (run.status === "failed" || run.status === "timed_out") {
    return { className: "heartbeat-state-danger", label: run.status };
  }
  if (run.status === "succeeded") return { className: "heartbeat-state-success", label: run.status };
  if (run.status === "running") return { className: "heartbeat-state-live", label: run.status };
  if (run.status === "queued") return { className: "heartbeat-state-warning", label: run.status };
  return { className: "heartbeat-state-muted", label: humanize(run.status) };
}

function latestRunByAgent(runs: HeartbeatRun[]): Map<string, HeartbeatRun> {
  const map = new Map<string, HeartbeatRun>();
  for (const run of runs) {
    if (!map.has(run.agentId)) map.set(run.agentId, run);
  }
  return map;
}

function statusClass(status: HeartbeatRun["status"]): string {
  if (status === "failed" || status === "timed_out") return "heartbeat-activity-failed";
  if (status === "succeeded") return "heartbeat-activity-succeeded";
  return "heartbeat-activity-active";
}

export function HeartbeatRunsPage() {
  const { orgId = "" } = useParams();
  const queryClient = useQueryClient();
  const agents = useQuery({ queryKey: ["agents", orgId], queryFn: () => agentsApi.list(orgId) });
  const runs = useQuery({
    queryKey: ["heartbeat-runs", orgId],
    queryFn: () => heartbeatApi.list(orgId),
    refetchInterval: 15000,
  });
  const setHeartbeatEnabled = useMutation({
    mutationFn: ({ agent, enabled }: { agent: Agent; enabled: boolean }) =>
      agentsApi.update(agent.id, buildHeartbeatPatch(agent, enabled)),
    onSuccess: async (_, variables) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["agents", variables.agent.orgId] }),
        queryClient.invalidateQueries({ queryKey: ["heartbeat-runs", variables.agent.orgId] }),
      ]);
    },
  });
  const invokeRun = useMutation({
    mutationFn: (agent: Agent) => heartbeatApi.invoke(agent.id),
    onSuccess: async (_, agent) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["heartbeat-runs", agent.orgId] }),
        queryClient.invalidateQueries({ queryKey: ["agents", agent.orgId] }),
      ]);
    },
  });

  const agentList = Array.isArray(agents.data) ? agents.data.filter((agent) => agent.status !== "terminated") : [];
  const sortedRuns = useMemo(
    () => [...(runs.data ?? [])].sort((a, b) => String(b.createdAt ?? "").localeCompare(String(a.createdAt ?? ""))),
    [runs.data],
  );
  const latestByAgent = useMemo(() => latestRunByAgent(sortedRuns), [sortedRuns]);
  const rows = useMemo(
    () =>
      [...agentList].sort((left, right) => {
        const leftLive = ["queued", "running"].includes(latestByAgent.get(left.id)?.status ?? "") ? 1 : 0;
        const rightLive = ["queued", "running"].includes(latestByAgent.get(right.id)?.status ?? "") ? 1 : 0;
        if (leftLive !== rightLive) return rightLive - leftLive;
        if (heartbeatEnabled(left) !== heartbeatEnabled(right)) return heartbeatEnabled(left) ? -1 : 1;
        return left.name.localeCompare(right.name);
      }),
    [agentList, latestByAgent],
  );
  const agentNameById = new Map(agentList.map((agent) => [agent.id, agent.name]));

  return (
    <OrgWorkspace contentClassName="org-content-full" orgId={orgId}>
      {agents.error && <ErrorNotice error={agents.error} />}
      {runs.error && <ErrorNotice error={runs.error} />}
      {setHeartbeatEnabled.error && <ErrorNotice error={setHeartbeatEnabled.error} />}
      {invokeRun.error && <ErrorNotice error={invokeRun.error} />}

      <div className="heartbeat-upstream-page">
        <section className="panel heartbeat-upstream-card">
          <div className="heartbeat-card-header">
            <div>
              <h1>智能体</h1>
              <p>每个智能体一行。这里用于控制定时心跳策略，并在需要深入检查时跳转到最近运行。</p>
            </div>
            <Link className="button secondary small-button" to={`/orgs/${orgId}/run-intelligence`}>运行分析</Link>
          </div>
          {rows.length === 0 ? (
            <div className="heartbeat-empty-state">暂无活跃智能体。创建智能体后再管理组织心跳。</div>
          ) : (
            <div className="heartbeat-upstream-list">
              {rows.map((agent) => {
                const latestRun = latestByAgent.get(agent.id) ?? null;
                const scheduler = schedulerState(agent);
                const runState = latestRunState(latestRun);
                const summary = latestRunSummary(latestRun);
                const toggleOn = heartbeatEnabled(agent);
                const saving = setHeartbeatEnabled.isPending && setHeartbeatEnabled.variables?.agent.id === agent.id;
                const starting = invokeRun.isPending && invokeRun.variables?.id === agent.id;
                return (
                  <article className="heartbeat-upstream-row" data-testid="org-heartbeat-row" key={agent.id}>
                    <div className="heartbeat-agent-cell">
                      <div className="heartbeat-agent-title-line">
                        <Link to={`/orgs/${agent.orgId}/agents/${agent.id}`}>{agent.name}</Link>
                        {latestRun && ["queued", "running"].includes(latestRun.status) && <span>Live</span>}
                      </div>
                      <p>{humanize(agent.title ?? agent.role)} · {humanize(agent.status)}</p>
                    </div>
                    <div className="heartbeat-scheduler-cell">
                      <strong className={scheduler.className}>{scheduler.label}</strong>
                      <p>每 {heartbeatIntervalSec(agent)}s</p>
                      <p title={formatDateTime(agent.lastHeartbeatAt)}>最近心跳 {relativeTime(agent.lastHeartbeatAt)}</p>
                    </div>
                    <div className="heartbeat-run-cell">
                      <strong className={runState.className}>{runState.label}</strong>
                      {summary && <p title={summary}>{summary}</p>}
                      <div>
                        {latestRun?.createdAt && <span title={formatDateTime(latestRun.createdAt)}>运行 {relativeTime(latestRun.createdAt)}</span>}
                        <Link to={`/orgs/${agent.orgId}/agents/${agent.id}`}>智能体 ↗</Link>
                      </div>
                    </div>
                    <div className="heartbeat-row-actions">
                      <div className="heartbeat-toggle-actions" aria-label={`定时心跳状态 ${agent.name}`}>
                        <button
                          className={toggleOn ? "active" : ""}
                          disabled={saving}
                          onClick={() => !toggleOn && setHeartbeatEnabled.mutate({ agent, enabled: true })}
                          type="button"
                        >
                          启用
                        </button>
                        <button
                          className={!toggleOn ? "active" : ""}
                          disabled={saving}
                          onClick={() => toggleOn && setHeartbeatEnabled.mutate({ agent, enabled: false })}
                          type="button"
                        >
                          关闭
                        </button>
                      </div>
                      <button className="secondary" disabled={starting} onClick={() => invokeRun.mutate(agent)} type="button">
                        {starting ? "启动中..." : "立即运行"}
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>
          )}
        </section>

        <section className="panel heartbeat-upstream-card">
          <div className="heartbeat-card-header">
            <div>
              <h2>最近活动</h2>
              <p>这里保持摘要优先。需要 transcript、日志和工作区操作时，打开关联运行。</p>
            </div>
          </div>
          {sortedRuns.length === 0 ? (
            <div className="heartbeat-empty-activity">暂无心跳运行记录。</div>
          ) : (
            <div className="heartbeat-activity-grid">
              {sortedRuns.slice(0, 6).map((run) => {
                const summary = latestRunSummary(run);
                return (
                  <Link
                    className="heartbeat-activity-card"
                    key={run.id}
                    to={`/orgs/${run.orgId}/agents/${run.agentId}/runs/${run.id}`}
                  >
                    <div className="heartbeat-activity-heading">
                      <span className={statusClass(run.status)}>{humanize(run.status)}</span>
                      <small>{agentNameById.get(run.agentId) ?? "未知智能体"}</small>
                    </div>
                    {summary && <p>{summary}</p>}
                    <time title={formatDateTime(run.createdAt)}>{relativeTime(run.createdAt)}</time>
                  </Link>
                );
              })}
            </div>
          )}
        </section>
      </div>
    </OrgWorkspace>
  );
}
