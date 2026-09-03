import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { agentsApi } from "../api/agents";
import { heartbeatApi } from "../api/heartbeat";
import type { Agent, HeartbeatRun } from "../api/types";
import { ErrorNotice } from "../components/ErrorNotice";
import { SegmentedControl } from "../components/SegmentedControl";
import { StatusPill } from "../components/StatusPill";
import { TertiaryPageHeader } from "../components/TertiaryPageShell";
import { roleLabel, statusLabel } from "../utils/display";
import { runDescriptor, runIssueLabel, runPurposeLabel, runStatusLabel, runTerminalReasonLabel } from "../utils/runDisplay";
import { OrgWorkspace } from "./OrganizationPage";

const DEFAULT_HEARTBEAT_INTERVAL_SEC = 300;

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
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
  const terminalReason = runTerminalReasonLabel(run);
  if (terminalReason) return terminalReason;
  if (run.error?.trim()) return run.error.trim();
  const result = asRecord(run.resultJson);
  for (const key of ["summary", "result", "message"]) {
    const value = result?.[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return null;
}

function heartbeatConfig(agent: Agent): Record<string, unknown> {
  const runtimeConfig = asRecord(agent.runtimeConfig) ?? {};
  return asRecord(runtimeConfig.heartbeat) ?? {};
}

function heartbeatEnabled(agent: Agent): boolean {
  const heartbeat = heartbeatConfig(agent);
  return heartbeat.enabled !== false && heartbeat.timerEnabled !== false;
}

function heartbeatIntervalSec(agent: Agent): number {
  const heartbeat = heartbeatConfig(agent);
  const raw = heartbeat.intervalSec ?? heartbeat.intervalSeconds ?? heartbeat.interval;
  if (typeof raw === "number" && Number.isFinite(raw) && raw > 0) return raw;
  if (typeof raw === "string" && raw.trim()) {
    const parsed = Number(raw);
    if (Number.isFinite(parsed) && parsed > 0) return parsed;
  }
  return DEFAULT_HEARTBEAT_INTERVAL_SEC;
}

function buildHeartbeatPatch(agent: Agent, enabled: boolean): { runtimeConfig: Record<string, unknown> } {
  const runtimeConfig = { ...(asRecord(agent.runtimeConfig) ?? {}) };
  const heartbeat = { ...(asRecord(runtimeConfig.heartbeat) ?? {}) };
  const currentInterval = heartbeat.intervalSec;
  const intervalSec =
    enabled && (typeof currentInterval !== "number" || currentInterval <= 0)
      ? DEFAULT_HEARTBEAT_INTERVAL_SEC
      : currentInterval;
  return {
    runtimeConfig: {
      ...runtimeConfig,
      heartbeat: {
        ...heartbeat,
        enabled,
        ...(intervalSec === undefined ? {} : { intervalSec }),
      },
    },
  };
}

function buildHeartbeatIntervalPatch(agent: Agent, intervalSec: number): { runtimeConfig: Record<string, unknown> } {
  const runtimeConfig = { ...(asRecord(agent.runtimeConfig) ?? {}) };
  const heartbeat = { ...(asRecord(runtimeConfig.heartbeat) ?? {}) };
  return {
    runtimeConfig: {
      ...runtimeConfig,
      heartbeat: {
        ...heartbeat,
        intervalSec,
      },
    },
  };
}

function latestRunState(run: HeartbeatRun | null): string {
  return run ? statusLabel(run.status) : "暂无运行";
}

function latestRunByAgent(runs: HeartbeatRun[]): Map<string, HeartbeatRun> {
  const map = new Map<string, HeartbeatRun>();
  for (const run of runs) {
    if (!map.has(run.agentId)) map.set(run.agentId, run);
  }
  return map;
}

export function HeartbeatRunsPage() {
  const { orgId = "" } = useParams();
  const queryClient = useQueryClient();
  const [intervalDrafts, setIntervalDrafts] = useState<Record<string, string>>({});
  const agents = useQuery({ queryKey: ["agents", orgId], queryFn: () => agentsApi.list(orgId), refetchInterval: 5000 });
  const runs = useQuery({
    queryKey: ["heartbeat-runs", orgId],
    queryFn: () => heartbeatApi.list(orgId),
    refetchInterval: 3000,
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
  const setHeartbeatInterval = useMutation({
    mutationFn: ({ agent, intervalSec }: { agent: Agent; intervalSec: number }) =>
      agentsApi.update(agent.id, buildHeartbeatIntervalPatch(agent, intervalSec)),
    onSuccess: async (_, variables) => {
      setIntervalDrafts((current) => {
        const next = { ...current };
        delete next[variables.agent.id];
        return next;
      });
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
      <TertiaryPageHeader
        actions={<Link className="button org-primary-action" to={`/orgs/${orgId}/run-intelligence`}>运行分析</Link>}
        eyebrow="Heartbeat Monitor"
        supporting="这里汇总智能体状态检测、运行记录和手动诊断。状态检测默认每 300s 执行一次，不等于执行任务。"
        title="心跳"
      />
      {agents.error && <ErrorNotice error={agents.error} />}
      {runs.error && <ErrorNotice error={runs.error} />}
      {setHeartbeatEnabled.error && <ErrorNotice error={setHeartbeatEnabled.error} />}
      {setHeartbeatInterval.error && <ErrorNotice error={setHeartbeatInterval.error} />}
      {invokeRun.error && <ErrorNotice error={invokeRun.error} />}

      <div className="heartbeat-upstream-page">
        <section aria-labelledby="heartbeat-agents-title" className="panel heartbeat-upstream-card">
          <div className="org-section-header">
            <div>
              <p className="eyebrow">Agents</p>
              <h2 id="heartbeat-agents-title">智能体</h2>
            </div>
          </div>
          {rows.length === 0 ? (
            <div className="heartbeat-empty-state">暂无活跃智能体。创建智能体后再管理心跳。</div>
          ) : (
            <div className="heartbeat-upstream-list">
              {rows.map((agent) => {
                const latestRun = latestByAgent.get(agent.id) ?? null;
                const runState = latestRunState(latestRun);
                const summary = latestRunSummary(latestRun);
                const toggleOn = heartbeatEnabled(agent);
                const saving = setHeartbeatEnabled.isPending && setHeartbeatEnabled.variables?.agent.id === agent.id;
                const savingInterval = setHeartbeatInterval.isPending && setHeartbeatInterval.variables?.agent.id === agent.id;
                const starting = invokeRun.isPending && invokeRun.variables?.id === agent.id;
                const intervalValue = intervalDrafts[agent.id] ?? String(heartbeatIntervalSec(agent));
                const nextInterval = Number(intervalValue);
                return (
                  <article className="heartbeat-upstream-row" data-testid="org-heartbeat-row" key={agent.id}>
                    <div className="heartbeat-agent-cell">
                      <div className="heartbeat-agent-title-line">
                        <Link to={`/orgs/${agent.orgId}/agents/${agent.id}`}>{agent.name}</Link>
                      </div>
                      <p title={`${agent.title ?? roleLabel(agent.role)} · ${statusLabel(agent.status)}`}>{agent.title ?? roleLabel(agent.role)} · {statusLabel(agent.status)}</p>
                      <div className="heartbeat-latest-state">
                        {latestRun ? <StatusPill status={latestRun.status}>{runState}</StatusPill> : <strong className="heartbeat-state-muted">{runState}</strong>}
                        {latestRun?.createdAt && <span className="muted" title={formatDateTime(latestRun.createdAt)}>运行 {relativeTime(latestRun.createdAt)}</span>}
                      </div>
                    </div>
                    <div className="heartbeat-run-cell">
                      <span className="heartbeat-summary-label">运行摘要</span>
                      <p title={summary || undefined}>{summary || "暂无运行摘要"}</p>
                    </div>
                    <div className="heartbeat-row-actions">
                      <SegmentedControl
                        ariaLabel={`${agent.name} 心跳开关`}
                        disabled={saving}
                        onChange={(value) => setHeartbeatEnabled.mutate({ agent, enabled: value === "enabled" })}
                        options={[{ label: "启用", value: "enabled" }, { label: "关闭", value: "disabled" }]}
                        value={toggleOn ? "enabled" : "disabled"}
                      />
                      <div className="heartbeat-interval-actions">
                        <label className="heartbeat-interval-control">
                          <span>间隔（秒）</span>
                          <input
                            aria-label={`${agent.name} 状态检测间隔秒数`}
                            min="1"
                            type="number"
                            value={intervalValue}
                            onChange={(event) => setIntervalDrafts((current) => ({ ...current, [agent.id]: event.target.value }))}
                          />
                        </label>
                        <button
                          className="secondary small-button heartbeat-save-interval"
                          disabled={savingInterval || !Number.isFinite(nextInterval) || nextInterval <= 0}
                          onClick={() => setHeartbeatInterval.mutate({ agent, intervalSec: nextInterval })}
                          type="button"
                        >
                          保存间隔
                        </button>
                      </div>
                      <button className="secondary heartbeat-run-diagnostic" disabled={starting} onClick={() => invokeRun.mutate(agent)} type="button">
                        {starting ? "诊断启动中..." : "运行诊断"}
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>
          )}
        </section>

        <section aria-labelledby="heartbeat-runs-title" className="panel heartbeat-upstream-card">
          <div className="org-section-header">
            <div>
              <p className="eyebrow">Recent Activity</p>
              <h2 id="heartbeat-runs-title">运行记录</h2>
            </div>
          </div>
          {sortedRuns.length === 0 ? (
            <div className="heartbeat-empty-activity">暂无运行记录。</div>
          ) : (
            <ul className="heartbeat-activity-list" aria-label="最近运行记录">
              {sortedRuns.slice(0, 6).map((run) => {
                const summary = latestRunSummary(run);
                const issueLabel = runIssueLabel(run);
                return (
                  <li key={run.id}>
                    <Link
                      className="heartbeat-activity-row"
                      to={`/orgs/${run.orgId}/agents/${run.agentId}/runs/${run.id}`}
                    >
                      <StatusPill status={run.status}>{runStatusLabel(run)}</StatusPill>
                      <strong className="heartbeat-activity-agent" title={agentNameById.get(run.agentId) ?? "未知智能体"}>{agentNameById.get(run.agentId) ?? "未知智能体"}</strong>
                      <div className="heartbeat-activity-context">
                        <p className="heartbeat-activity-meta" title={runDescriptor(run)}>{runPurposeLabel(run)} · {runDescriptor(run)}</p>
                        {issueLabel && <p className="heartbeat-activity-meta" title={issueLabel}>{issueLabel}</p>}
                      </div>
                      <p className="heartbeat-activity-summary" title={summary || undefined}>{summary || "—"}</p>
                      <time title={formatDateTime(run.createdAt)}>{relativeTime(run.createdAt)}</time>
                    </Link>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      </div>
    </OrgWorkspace>
  );
}
