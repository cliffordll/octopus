import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { Link, NavLink, useParams } from "react-router-dom";
import { agentsApi } from "../api/agents";
import { heartbeatApi } from "../api/heartbeat";
import type { AgentRole, AgentRuntimeType, UpdateAgentPayload } from "../api/types";
import { Badge } from "../components/Badge";
import { AgentsWorkspace } from "../components/ContextWorkspace";
import { ErrorNotice } from "../components/ErrorNotice";

const ROLES: AgentRole[] = ["ceo", "cto", "cmo", "cfo", "engineer", "designer", "pm", "qa", "devops", "researcher", "general"];
const RUNTIMES: AgentRuntimeType[] = ["process", "codex_local"];

function readJsonObject(value: string, label: string): Record<string, unknown> {
  const parsed: unknown = JSON.parse(value);
  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error(`${label} 必须是 JSON 对象`);
  }
  return parsed as Record<string, unknown>;
}

export function AgentPage() {
  const { orgId = "", agentId = "", tab = "dashboard" } = useParams();
  const activeTab = ["dashboard", "configuration", "runs"].includes(tab) ? tab : "dashboard";
  const [name, setName] = useState("");
  const [title, setTitle] = useState("");
  const [role, setRole] = useState<AgentRole>("general");
  const [capabilities, setCapabilities] = useState("");
  const [reportsTo, setReportsTo] = useState("");
  const [runtime, setRuntime] = useState<AgentRuntimeType>("process");
  const [budgetMonthlyCents, setBudgetMonthlyCents] = useState("0");
  const [agentRuntimeConfig, setAgentRuntimeConfig] = useState("{}");
  const [runtimeConfig, setRuntimeConfig] = useState("{}");
  const [configurationError, setConfigurationError] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const agent = useQuery({ queryKey: ["agent", agentId], queryFn: () => agentsApi.get(agentId) });
  const organizationAgents = useQuery({ queryKey: ["agents", orgId], queryFn: () => agentsApi.list(orgId) });
  const runtimeState = useQuery({
    queryKey: ["agent-runtime-state", agentId],
    queryFn: () => agentsApi.runtimeState(agentId),
  });
  const runs = useQuery({
    queryKey: ["heartbeat-runs", orgId, agentId],
    queryFn: () => heartbeatApi.list(orgId, agentId),
  });
  useEffect(() => {
    if (!agent.data) return;
    setName(agent.data.name);
    setTitle(agent.data.title ?? "");
    setRole(agent.data.role);
    setCapabilities(agent.data.capabilities ?? "");
    setReportsTo(agent.data.reportsTo ?? "");
    setRuntime(agent.data.agentRuntimeType);
    setBudgetMonthlyCents(String(agent.data.budgetMonthlyCents ?? 0));
    setAgentRuntimeConfig(JSON.stringify(agent.data.agentRuntimeConfig ?? {}, null, 2));
    setRuntimeConfig(JSON.stringify(agent.data.runtimeConfig ?? {}, null, 2));
  }, [agent.data]);
  const action = useMutation({
    mutationFn: (operation: "pause" | "resume" | "terminate") => agentsApi[operation](agentId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["agent", agentId] });
      void queryClient.invalidateQueries({ queryKey: ["agents", orgId] });
    },
  });
  const save = useMutation({
    mutationFn: (payload: UpdateAgentPayload) => agentsApi.update(agentId, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["agent", agentId] });
      void queryClient.invalidateQueries({ queryKey: ["agents", orgId] });
    },
  });
  const invoke = useMutation({
    mutationFn: () => heartbeatApi.invoke(agentId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["heartbeat-runs", orgId, agentId] });
      void queryClient.invalidateQueries({ queryKey: ["agent-runtime-state", agentId] });
    },
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    if (!name.trim()) return;
    try {
      setConfigurationError(null);
      save.mutate({
        name: name.trim(),
        title: title.trim() || null,
        role,
        reportsTo: reportsTo || null,
        capabilities: capabilities.trim() || null,
        agentRuntimeType: runtime,
        agentRuntimeConfig: readJsonObject(agentRuntimeConfig, "Agent runtime config"),
        runtimeConfig: readJsonObject(runtimeConfig, "Runtime config"),
        budgetMonthlyCents: Number(budgetMonthlyCents),
      });
    } catch (error) {
      setConfigurationError(error instanceof Error ? error.message : "配置格式无效");
    }
  }
  if (agent.error) return <ErrorNotice error={agent.error} />;
  return (
    <AgentsWorkspace orgId={orgId}>
      <header className="page-header">
        <div>
          <Link className="back-link" to={`/orgs/${orgId}/agents`}>返回智能体列表</Link>
          <h1>{agent.data?.name ?? "载入中..."}</h1>
        </div>
      </header>
      {agent.data && (
        <>
          <nav aria-label="智能体详情导航" className="detail-tabs">
            <NavLink to={`/orgs/${orgId}/agents/${agentId}/dashboard`}>概览</NavLink>
            <NavLink to={`/orgs/${orgId}/agents/${agentId}/configuration`}>配置</NavLink>
            <NavLink to={`/orgs/${orgId}/agents/${agentId}/runs`}>运行</NavLink>
          </nav>
          {activeTab === "dashboard" && <div className="agent-dashboard">
          <section className="panel agent-overview">
            <div className="meta-line">
              <Badge>{agent.data.role}</Badge><Badge>{agent.data.status}</Badge><Badge>{agent.data.agentRuntimeType}</Badge>
            </div>
            <dl className="agent-properties">
              <div><dt>职务</dt><dd>{agent.data.title ?? "未设置"}</dd></div>
              <div><dt>上级</dt><dd>{agent.data.reportsTo ?? "未设置"}</dd></div>
              <div><dt>最近 Heartbeat</dt><dd>{agent.data.lastHeartbeatAt ?? "暂无"}</dd></div>
            </dl>
            <div className="actions">
              <button disabled={agent.data.status === "paused" || agent.data.status === "terminated"} type="button" onClick={() => action.mutate("pause")}>暂停</button>
              <button className="secondary" disabled={agent.data.status !== "paused"} type="button" onClick={() => action.mutate("resume")}>恢复</button>
              <button className="danger" disabled={agent.data.status === "terminated"} type="button" onClick={() => action.mutate("terminate")}>终止</button>
            </div>
            <button disabled={agent.data.status === "paused" || agent.data.status === "terminated"} type="button" onClick={() => invoke.mutate()}>触发 Heartbeat</button>
            {action.error && <ErrorNotice error={action.error} />}
            {invoke.error && <ErrorNotice error={invoke.error} />}
          </section>
          <section className="panel">
            <h2>Runtime 状态</h2>
            {runtimeState.error && <ErrorNotice error={runtimeState.error} />}
            {runtimeState.data && (
              <dl className="agent-properties">
                <div><dt>最近运行</dt><dd>{runtimeState.data.lastRunStatus ?? "暂无"}</dd></div>
                <div><dt>会话</dt><dd>{runtimeState.data.sessionDisplayId ?? "暂无"}</dd></div>
                <div><dt>Tokens</dt><dd>{runtimeState.data.totalInputTokens + runtimeState.data.totalOutputTokens}</dd></div>
                <div><dt>成本</dt><dd>{runtimeState.data.totalCostCents} cents</dd></div>
              </dl>
            )}
          </section>
          </div>}
          {activeTab === "configuration" && <form className="panel form agent-configuration" onSubmit={submit}>
            <h2>基础配置</h2>
            <label>智能体名称<input value={name} onChange={(event) => setName(event.target.value)} required /></label>
            <label>职务<input value={title} onChange={(event) => setTitle(event.target.value)} /></label>
            <label>
              角色
              <select value={role} onChange={(event) => setRole(event.target.value as AgentRole)}>
                {ROLES.map((item) => <option key={item}>{item}</option>)}
              </select>
            </label>
            <label>
              上级智能体
              <select value={reportsTo} onChange={(event) => setReportsTo(event.target.value)}>
                <option value="">未设置</option>
                {(organizationAgents.data ?? [])
                  .filter((item) => item.id !== agentId)
                  .map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
              </select>
            </label>
            <label>能力描述<textarea value={capabilities} onChange={(event) => setCapabilities(event.target.value)} /></label>
            <h2 className="form-section-title">执行配置</h2>
            <label>
              Runtime
              <select value={runtime} onChange={(event) => setRuntime(event.target.value as AgentRuntimeType)}>
                {RUNTIMES.map((item) => <option key={item}>{item}</option>)}
              </select>
            </label>
            <label>月度预算（cents）<input min="0" type="number" value={budgetMonthlyCents} onChange={(event) => setBudgetMonthlyCents(event.target.value)} required /></label>
            <label>Agent runtime config<textarea className="config-editor" value={agentRuntimeConfig} onChange={(event) => setAgentRuntimeConfig(event.target.value)} /></label>
            <label>Runtime config<textarea className="config-editor" value={runtimeConfig} onChange={(event) => setRuntimeConfig(event.target.value)} /></label>
            {configurationError && <p className="error-notice">{configurationError}</p>}
            {save.error && <ErrorNotice error={save.error} />}
            <button disabled={save.isPending} type="submit">保存配置</button>
          </form>}
          {activeTab === "runs" && <section className="panel agent-runs">
            <h2>Heartbeat Runs</h2>
            {runs.error && <ErrorNotice error={runs.error} />}
            <div className="list">
              {runs.data?.map((run) => (
                <article className="row" key={run.id}>
                  <span>{run.invocationSource}</span>
                  <Badge>{run.status}</Badge>
                </article>
              ))}
            </div>
          </section>}
        </>
      )}
    </AgentsWorkspace>
  );
}
