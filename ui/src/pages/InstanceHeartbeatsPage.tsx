import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { agentsApi } from "../api/agents";
import { heartbeatApi } from "../api/heartbeat";
import type { Agent, InstanceSchedulerHeartbeatAgent } from "../api/types";
import { ErrorNotice } from "../components/ErrorNotice";
import { roleLabel, statusLabel } from "../utils/display";

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

function schedulerState(agent: InstanceSchedulerHeartbeatAgent): { className: string; label: string } {
  if (agent.schedulerActive) return { className: "heartbeat-state-success", label: "已调度" };
  if (agent.heartbeatEnabled) return { className: "heartbeat-state-warning", label: "已配置未启用" };
  return { className: "heartbeat-state-muted", label: "未启用" };
}

function formatInterval(intervalSec: number): string {
  return `每 ${effectiveIntervalSec(intervalSec)}s`;
}

function effectiveIntervalSec(intervalSec: number): number {
  return intervalSec > 0 ? intervalSec : DEFAULT_HEARTBEAT_INTERVAL_SEC;
}

async function setHeartbeatEnabled(agentRow: InstanceSchedulerHeartbeatAgent, enabled: boolean): Promise<Agent> {
  const agent = await agentsApi.get(agentRow.id);
  const runtimeConfig = { ...(asRecord(agent.runtimeConfig) ?? {}) };
  const heartbeat = { ...(asRecord(runtimeConfig.heartbeat) ?? {}) };
  const currentInterval = heartbeat.intervalSec;
  const intervalSec =
    enabled && (typeof currentInterval !== "number" || currentInterval <= 0)
      ? DEFAULT_HEARTBEAT_INTERVAL_SEC
      : currentInterval;
  return agentsApi.update(agentRow.id, {
    runtimeConfig: {
      ...runtimeConfig,
      heartbeat: {
        ...heartbeat,
        enabled,
        ...(intervalSec === undefined ? {} : { intervalSec }),
      },
    },
  });
}

async function setHeartbeatInterval(agentRow: InstanceSchedulerHeartbeatAgent, intervalSec: number): Promise<Agent> {
  const agent = await agentsApi.get(agentRow.id);
  const runtimeConfig = { ...(asRecord(agent.runtimeConfig) ?? {}) };
  const heartbeat = { ...(asRecord(runtimeConfig.heartbeat) ?? {}) };
  return agentsApi.update(agentRow.id, {
    runtimeConfig: {
      ...runtimeConfig,
      heartbeat: {
        ...heartbeat,
        intervalSec,
      },
    },
  });
}

export function InstanceHeartbeatsPanel() {
  const queryClient = useQueryClient();
  const [intervalDrafts, setIntervalDrafts] = useState<Record<string, string>>({});
  const heartbeats = useQuery({
    queryKey: ["instance", "scheduler-heartbeats"],
    queryFn: heartbeatApi.listInstanceSchedulerAgents,
    refetchInterval: 15000,
  });
  const setHeartbeatEnabledMutation = useMutation({
    mutationFn: ({ agent, enabled }: { agent: InstanceSchedulerHeartbeatAgent; enabled: boolean }) =>
      setHeartbeatEnabled(agent, enabled),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["instance", "scheduler-heartbeats"] });
    },
  });
  const setHeartbeatIntervalMutation = useMutation({
    mutationFn: ({ agent, intervalSec }: { agent: InstanceSchedulerHeartbeatAgent; intervalSec: number }) =>
      setHeartbeatInterval(agent, intervalSec),
    onSuccess: async (_, variables) => {
      setIntervalDrafts((current) => {
        const next = { ...current };
        delete next[variables.agent.id];
        return next;
      });
      await queryClient.invalidateQueries({ queryKey: ["instance", "scheduler-heartbeats"] });
    },
  });

  const agents = heartbeats.data ?? [];
  const grouped = useMemo(() => {
    const map = new Map<string, { organizationName: string; orgId: string; agents: InstanceSchedulerHeartbeatAgent[] }>();
    for (const agent of agents) {
      const group = map.get(agent.orgId) ?? { organizationName: agent.organizationName, orgId: agent.orgId, agents: [] };
      group.agents.push(agent);
      map.set(agent.orgId, group);
    }
    return [...map.values()];
  }, [agents]);
  const scheduledCount = agents.filter((agent) => agent.schedulerActive).length;
  const inactiveCount = agents.filter((agent) => agent.heartbeatEnabled && !agent.schedulerActive).length;
  const disabledCount = agents.filter((agent) => !agent.heartbeatEnabled).length;

  return (
    <section className="runtime-settings heartbeat-settings" aria-label="心跳设置">
      {heartbeats.error && <ErrorNotice error={heartbeats.error} />}
      {setHeartbeatEnabledMutation.error && <ErrorNotice error={setHeartbeatEnabledMutation.error} />}
      {setHeartbeatIntervalMutation.error && <ErrorNotice error={setHeartbeatIntervalMutation.error} />}

      <div className="panel-heading runtime-provider-heading">
        <div className="settings-section-heading-copy">
          <p className="eyebrow">Timer Heartbeats</p>
          <div className="runtime-provider-title-line">
            <h3>心跳</h3>
            <p className="muted">控制实例内所有组织的智能体定时心跳。</p>
          </div>
        </div>
      </div>

      <div className="runtime-settings-grid heartbeat-settings-grid">
        <section className="runtime-settings-column heartbeat-scheduler-section">
          <div className="runtime-settings-title">
            <h4>Scheduler</h4>
            <div className="runtime-settings-title-actions heartbeat-instance-summary" aria-label="定时心跳汇总">
              <span><strong>{scheduledCount}</strong> 已调度</span>
              <span><strong>{inactiveCount}</strong> 未激活</span>
              <span><strong>{disabledCount}</strong> 关闭</span>
              <span><strong>{grouped.length}</strong> 组织</span>
            </div>
          </div>
          {agents.length === 0 ? (
            <div className="heartbeat-empty-state">暂无可调度智能体。</div>
          ) : (
            <div className="runtime-provider-list runtime-provider-group-list heartbeat-provider-list">
              {grouped.map((group) => (
                <section className="runtime-provider-group heartbeat-instance-group" key={group.orgId}>
                  <div className="runtime-provider-group-header">
                    <div className="heartbeat-instance-group-title">
                      <Link to={`/orgs/${group.orgId}/heartbeat-runs`}>{group.organizationName}</Link>
                      <span>{group.agents.length} agents</span>
                    </div>
                  </div>
                  {group.agents.map((agent) => {
                    const state = schedulerState(agent);
                    const saving =
                      setHeartbeatEnabledMutation.isPending &&
                      setHeartbeatEnabledMutation.variables?.agent.id === agent.id;
                    const savingInterval =
                      setHeartbeatIntervalMutation.isPending &&
                      setHeartbeatIntervalMutation.variables?.agent.id === agent.id;
                    const intervalValue = intervalDrafts[agent.id] ?? String(effectiveIntervalSec(agent.intervalSec));
                    const nextInterval = Number(intervalValue);
                    return (
                      <article className="heartbeat-settings-row" data-testid="instance-heartbeat-row" key={agent.id}>
                        <div className="heartbeat-agent-cell">
                          <div className="heartbeat-agent-title-line">
                            <Link to={`/orgs/${agent.orgId}/agents/${agent.id}`}>{agent.agentName}</Link>
                          </div>
                          <p>{agent.title ?? roleLabel(agent.role)} · {statusLabel(agent.status)}</p>
                        </div>
                        <div className="heartbeat-scheduler-cell">
                          <strong className={state.className}>{state.label}</strong>
                          <p>{formatInterval(agent.intervalSec)}</p>
                          <p title={formatDateTime(agent.lastHeartbeatAt)}>最近心跳 {relativeTime(agent.lastHeartbeatAt)}</p>
                        </div>
                        <div className="heartbeat-row-actions">
                          <div className="heartbeat-toggle-actions" aria-label={`定时心跳状态 ${agent.agentName}`}>
                            <button
                              className={agent.heartbeatEnabled ? "active" : ""}
                              disabled={saving}
                              onClick={() =>
                                !agent.heartbeatEnabled &&
                                setHeartbeatEnabledMutation.mutate({ agent, enabled: true })
                              }
                              type="button"
                            >
                              启用
                            </button>
                            <button
                              className={!agent.heartbeatEnabled ? "active" : ""}
                              disabled={saving}
                              onClick={() =>
                                agent.heartbeatEnabled &&
                                setHeartbeatEnabledMutation.mutate({ agent, enabled: false })
                              }
                              type="button"
                            >
                              关闭
                            </button>
                          </div>
                          <label className="heartbeat-interval-control">
                            <span>间隔</span>
                            <input
                              aria-label={`${agent.agentName} 心跳间隔秒数`}
                              min="1"
                              type="number"
                              value={intervalValue}
                              onChange={(event) => setIntervalDrafts((current) => ({ ...current, [agent.id]: event.target.value }))}
                            />
                          </label>
                          <button
                            className="secondary small-button"
                            disabled={savingInterval || !Number.isFinite(nextInterval) || nextInterval <= 0}
                            onClick={() => setHeartbeatIntervalMutation.mutate({ agent, intervalSec: nextInterval })}
                            type="button"
                          >
                            保存间隔
                          </button>
                        </div>
                      </article>
                    );
                  })}
                </section>
              ))}
            </div>
          )}
        </section>
      </div>
    </section>
  );
}

export function InstanceHeartbeatsPage() {
  return (
    <div className="workspace-content">
      <InstanceHeartbeatsPanel />
    </div>
  );
}
