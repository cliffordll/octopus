import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, NavLink, useNavigate, useParams } from "react-router-dom";
import { agentsApi } from "../api/agents";
import { heartbeatApi } from "../api/heartbeat";
import { issuesApi } from "../api/issues";
import type { AgentDetail, AgentRole, AgentRuntimeType, HeartbeatRun, UpdateAgentPayload } from "../api/types";
import { Badge } from "../components/Badge";
import { AgentsWorkspace } from "../components/ContextWorkspace";
import { ErrorNotice } from "../components/ErrorNotice";

const ROLES: AgentRole[] = ["ceo", "cto", "cmo", "cfo", "engineer", "designer", "pm", "qa", "devops", "researcher", "general"];
const RUNTIMES: AgentRuntimeType[] = ["process", "http", "codex_local", "claude_local", "opencode_local"];

function readJsonObject(value: string, label: string): Record<string, unknown> {
  const parsed: unknown = JSON.parse(value);
  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error(`${label} 必须是 JSON 对象`);
  }
  return parsed as Record<string, unknown>;
}

function parseCsv(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function formatRunTime(value?: string | null): string {
  return value || "无";
}

function summarizeRun(run: HeartbeatRun | null): string {
  if (!run) return "No runs yet.";
  if (run.error?.trim()) return run.error.trim();
  const summary = run.resultJson?.summary ?? run.resultJson?.result ?? run.resultJson?.message;
  return typeof summary === "string" && summary.trim() ? summary.trim() : run.id;
}

function runMetric(run: HeartbeatRun | null, key: string): string {
  const value = run?.usageJson?.[key];
  if (typeof value === "number") return String(value);
  if (typeof value === "string" && value.trim()) return value;
  return "-";
}

type InstructionDoc = {
  content: string;
  key: string;
  name: string;
  path: string;
  source: string;
};

function stringConfig(config: Record<string, unknown>, key: string): string {
  const value = config[key];
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

function managedInstructionFiles(config: Record<string, unknown>): InstructionDoc[] {
  const files = config.managedInstructionFiles;
  if (!Array.isArray(files)) return [];
  return files
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
    .map((item, index) => {
      const name = typeof item.name === "string" && item.name.trim() ? item.name.trim() : `instruction-${index + 1}.md`;
      const path = typeof item.path === "string" && item.path.trim() ? item.path.trim() : name;
      const content = typeof item.content === "string" ? item.content : "";
      return { content, key: `managed:${path}:${index}`, name, path, source: "managedInstructionFiles" };
    });
}

function buildInstructionDocs(agent: AgentDetail): InstructionDoc[] {
  const config = agent.agentRuntimeConfig ?? {};
  const docs: InstructionDoc[] = [];
  const promptTemplate = stringConfig(config, "promptTemplate") || agent.capabilities || "";
  const instructionsFilePath = stringConfig(config, "instructionsFilePath");
  if (instructionsFilePath || promptTemplate) {
    docs.push({
      content: promptTemplate,
      key: "soul",
      name: "SOUL.md",
      path: instructionsFilePath || "SOUL.md",
      source: instructionsFilePath ? "instructionsFilePath" : "promptTemplate",
    });
  }
  const agentsMdPath = stringConfig(config, "agentsMdPath");
  if (agentsMdPath) {
    docs.push({
      content: "",
      key: "agents-md",
      name: "AGENTS.md",
      path: agentsMdPath,
      source: "agentsMdPath",
    });
  }
  docs.push(...managedInstructionFiles(config));
  return docs;
}

function AgentRunDetail({ run }: { run: HeartbeatRun | null }) {
  if (!run) {
    return (
      <section className="panel agent-run-detail-card">
        <p className="muted">No runs yet.</p>
      </section>
    );
  }
  const hasUsage = Boolean(run.usageJson && Object.keys(run.usageJson).length > 0);
  const hasSession = Boolean(run.sessionIdBefore || run.sessionIdAfter);
  return (
    <section className="panel agent-run-detail-card" data-testid="agent-runs-detail-pane">
      <div className="agent-run-detail-header">
        <div>
          <div className="meta-line">
            <Badge>{run.status}</Badge>
            <Badge>{run.invocationSource}</Badge>
            {run.triggerDetail && <Badge>{run.triggerDetail}</Badge>}
          </div>
          <h2>{run.id.slice(0, 8)}</h2>
          <p className="muted">{summarizeRun(run)}</p>
        </div>
        {run.processPid && <Badge>PID {run.processPid}</Badge>}
      </div>
      <dl className="detail-grid compact">
        <div><dt>Run ID</dt><dd>{run.id}</dd></div>
        <div><dt>Started</dt><dd>{formatRunTime(run.startedAt)}</dd></div>
        <div><dt>Finished</dt><dd>{formatRunTime(run.finishedAt)}</dd></div>
        <div><dt>Exit</dt><dd>{run.exitCode ?? "无"}</dd></div>
        <div><dt>Retry Of</dt><dd>{run.retryOfRunId ?? "无"}</dd></div>
        <div><dt>External Run</dt><dd>{run.externalRunId ?? "无"}</dd></div>
      </dl>
      {hasUsage && (
        <div className="agent-run-metrics">
          <div><span>Input</span><strong>{runMetric(run, "inputTokens")}</strong></div>
          <div><span>Output</span><strong>{runMetric(run, "outputTokens")}</strong></div>
          <div><span>Cached</span><strong>{runMetric(run, "cachedInputTokens")}</strong></div>
          <div><span>Cost</span><strong>{runMetric(run, "costCents")}</strong></div>
        </div>
      )}
      {hasSession && (
        <dl className="agent-run-session">
          <div><dt>Session Before</dt><dd>{run.sessionIdBefore ?? "无"}</dd></div>
          <div><dt>Session After</dt><dd>{run.sessionIdAfter ?? "无"}</dd></div>
        </dl>
      )}
      {run.error && <p className="error-notice">{run.error}</p>}
      {run.stdoutExcerpt && <pre className="run-excerpt">{run.stdoutExcerpt}</pre>}
      {run.stderrExcerpt && <pre className="run-excerpt error">{run.stderrExcerpt}</pre>}
    </section>
  );
}

export function AgentPage() {
  const { orgId = "", agentId = "", tab = "dashboard" } = useParams();
  const activeTab = ["dashboard", "profile", "configuration", "skills", "runs"].includes(tab) ? tab : "dashboard";
  const [name, setName] = useState("");
  const [title, setTitle] = useState("");
  const [role, setRole] = useState<AgentRole>("general");
  const [capabilities, setCapabilities] = useState("");
  const [reportsTo, setReportsTo] = useState("");
  const [runtime, setRuntime] = useState<AgentRuntimeType>("process");
  const [budgetMonthlyCents, setBudgetMonthlyCents] = useState("0");
  const [agentRuntimeConfig, setAgentRuntimeConfig] = useState("{}");
  const [runtimeConfig, setRuntimeConfig] = useState("{}");
  const [desiredSkills, setDesiredSkills] = useState("");
  const [skillsToEnable, setSkillsToEnable] = useState("");
  const [privateSkillName, setPrivateSkillName] = useState("");
  const [privateSkillMarkdown, setPrivateSkillMarkdown] = useState("");
  const [adapterTestChecks, setAdapterTestChecks] = useState<Array<{ label?: string; id?: string; status?: string; message?: string }>>([]);
  const [configurationError, setConfigurationError] = useState<string | null>(null);
  const [taskDialogOpen, setTaskDialogOpen] = useState(false);
  const [taskTitle, setTaskTitle] = useState("");
  const [selectedRunId, setSelectedRunId] = useState("");
  const [selectedInstructionKey, setSelectedInstructionKey] = useState("");
  const [showInstructionForm, setShowInstructionForm] = useState(false);
  const [newInstructionName, setNewInstructionName] = useState("");
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const agent = useQuery({ queryKey: ["agent", agentId], queryFn: () => agentsApi.get(agentId) });
  const organizationAgents = useQuery({ queryKey: ["agents", orgId], queryFn: () => agentsApi.list(orgId) });
  const runtimeState = useQuery({
    queryKey: ["agent-runtime-state", agentId],
    queryFn: () => agentsApi.runtimeState(agentId),
  });
  const configRevisions = useQuery({
    queryKey: ["agent-config-revisions", agentId],
    queryFn: () => agentsApi.configRevisions(agentId),
    enabled: activeTab === "configuration",
  });
  const adapterModels = useQuery({
    queryKey: ["adapter-models", orgId, runtime],
    queryFn: () => agentsApi.adapterModels(orgId, runtime),
    enabled: activeTab === "configuration" && Boolean(orgId && runtime),
  });
  const adapterMetadata = useQuery({
    queryKey: ["adapter-metadata", orgId, runtime],
    queryFn: () => agentsApi.adapterMetadata(orgId, runtime),
    enabled: activeTab === "configuration" && Boolean(orgId && runtime),
  });
  const adapterQuotaWindows = useQuery({
    queryKey: ["adapter-quota-windows", orgId, runtime],
    queryFn: () => agentsApi.adapterQuotaWindows(orgId, runtime),
    enabled: activeTab === "configuration" && Boolean(orgId && runtime),
  });
  const skills = useQuery({
    queryKey: ["agent-skills", agentId],
    queryFn: () => agentsApi.skills(agentId),
    enabled: activeTab === "configuration" || activeTab === "skills",
  });
  const skillsAnalytics = useQuery({
    queryKey: ["agent-skills-analytics", agentId],
    queryFn: () => agentsApi.skillsAnalytics(agentId),
    enabled: activeTab === "configuration" || activeTab === "skills",
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
    setDesiredSkills((agent.data.desiredSkills ?? []).join(","));
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
  const rollbackRevision = useMutation({
    mutationFn: (revisionId: string) => agentsApi.rollbackConfigRevision(agentId, revisionId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["agent", agentId] });
      void queryClient.invalidateQueries({ queryKey: ["agent-config-revisions", agentId] });
    },
  });
  const resetSession = useMutation({
    mutationFn: () => agentsApi.resetSession(agentId, {}),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["agent-runtime-state", agentId] }),
  });
  const testAdapterEnvironment = useMutation({
    mutationFn: () => agentsApi.testAdapterEnvironment(orgId, runtime, readJsonObject(agentRuntimeConfig, "Agent runtime config")),
    onSuccess: (result) => setAdapterTestChecks(result.checks),
    onError: () => setAdapterTestChecks([]),
  });
  const syncSkills = useMutation({
    mutationFn: () => agentsApi.syncSkills(agentId, parseCsv(desiredSkills)),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["agent-skills", agentId] });
      void queryClient.invalidateQueries({ queryKey: ["agent", agentId] });
    },
  });
  const enableSkills = useMutation({
    mutationFn: () => agentsApi.enableSkills(agentId, parseCsv(skillsToEnable)),
    onSuccess: () => {
      setSkillsToEnable("");
      void queryClient.invalidateQueries({ queryKey: ["agent-skills", agentId] });
      void queryClient.invalidateQueries({ queryKey: ["agent", agentId] });
    },
  });
  const createPrivateSkill = useMutation({
    mutationFn: () => agentsApi.createPrivateSkill(agentId, {
      name: privateSkillName.trim(),
      markdown: privateSkillMarkdown.trim() || null,
    }),
    onSuccess: () => {
      setPrivateSkillName("");
      setPrivateSkillMarkdown("");
      void queryClient.invalidateQueries({ queryKey: ["agent-skills", agentId] });
    },
  });
  const assignTask = useMutation({
    mutationFn: () => issuesApi.create(orgId, {
      title: taskTitle.trim(),
      assigneeAgentId: agentId,
    }),
    onSuccess: (issue) => {
      setTaskDialogOpen(false);
      setTaskTitle("");
      void queryClient.invalidateQueries({ queryKey: ["issues", orgId] });
      navigate(`/orgs/${orgId}/issues/${issue.id}`);
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
        desiredSkills: parseCsv(desiredSkills),
        agentRuntimeType: runtime,
        agentRuntimeConfig: readJsonObject(agentRuntimeConfig, "Agent runtime config"),
        runtimeConfig: readJsonObject(runtimeConfig, "Runtime config"),
        budgetMonthlyCents: Number(budgetMonthlyCents),
      });
    } catch (error) {
      setConfigurationError(error instanceof Error ? error.message : "配置格式无效");
    }
  }
  function submitTask(event: FormEvent) {
    event.preventDefault();
    if (taskTitle.trim()) assignTask.mutate();
  }
  const canChat = agent.data?.agentRuntimeType === "codex_local" && agent.data.status !== "terminated";
  const runRows = Array.isArray(runs.data) ? runs.data : [];
  const sortedRuns = useMemo(
    () => [...runRows].sort((a, b) => String(b.createdAt ?? "").localeCompare(String(a.createdAt ?? ""))),
    [runRows],
  );
  const selectedRun = sortedRuns.find((run) => run.id === selectedRunId) ?? sortedRuns[0] ?? null;
  const revisionRows = Array.isArray(configRevisions.data) ? configRevisions.data : [];
  const adapterModelRows = Array.isArray(adapterModels.data) ? adapterModels.data : [];
  const skillEntries = Array.isArray(skills.data?.entries) ? skills.data.entries : [];
  const instructionDocs = agent.data ? buildInstructionDocs(agent.data) : [];
  const selectedInstruction = instructionDocs.find((doc) => doc.key === selectedInstructionKey) ?? instructionDocs[0];
  function defaultInstructionName() {
    const names = new Set(instructionDocs.map((doc) => doc.name.toLowerCase()));
    if (!names.has("NEW.md".toLowerCase())) return "NEW.md";
    let index = 2;
    while (names.has(`NEW-${index}.md`.toLowerCase())) index += 1;
    return `NEW-${index}.md`;
  }
  function openInstructionForm() {
    setNewInstructionName(defaultInstructionName());
    setShowInstructionForm(true);
  }
  function closeInstructionForm() {
    setShowInstructionForm(false);
    setNewInstructionName("");
  }
  function appendInstruction(event: FormEvent) {
    event.preventDefault();
    if (!agent.data || !newInstructionName.trim()) return;
    const existingFiles = managedInstructionFiles(agent.data.agentRuntimeConfig).map((doc) => ({
      content: doc.content,
      name: doc.name,
      path: doc.path,
    }));
    save.mutate({
      agentRuntimeConfig: {
        ...agent.data.agentRuntimeConfig,
        managedInstructionFiles: [
          ...existingFiles,
          {
            content: "",
            name: newInstructionName.trim(),
            path: newInstructionName.trim(),
          },
        ],
      },
    });
    closeInstructionForm();
  }
  if (agent.error) return <ErrorNotice error={agent.error} />;
  return (
    <AgentsWorkspace orgId={orgId}>
      <header className="page-header agent-page-header">
        <div className="agent-header-identity">
          <div className="agent-avatar-lg">{agent.data?.name?.slice(0, 1).toUpperCase() ?? "A"}</div>
          <div>
            <Link className="back-link" to={`/orgs/${orgId}/agents`}>返回智能体列表</Link>
            <div className="agent-title-row">
              <h1>{agent.data?.name ?? "载入中..."}</h1>
              {agent.data && <Badge>{agent.data.status}</Badge>}
            </div>
            {agent.data && (
              <div className="agent-header-meta">
                <Badge>{agent.data.role}</Badge>
                <Badge>{agent.data.agentRuntimeType}</Badge>
                <span>{agent.data.title ?? "No title"}</span>
              </div>
            )}
          </div>
        </div>
        {agent.data && (
          <div className="agent-header-actions">
            <button className="secondary" onClick={() => setTaskDialogOpen(true)} type="button">分配任务</button>
            {canChat ? (
              <Link className="button secondary" to={`/orgs/${orgId}/chats?agentId=${encodeURIComponent(agentId)}`}>聊天</Link>
            ) : (
              <button className="secondary" disabled type="button">聊天</button>
            )}
            <button disabled={agent.data.status === "paused" || agent.data.status === "terminated"} type="button" onClick={() => action.mutate("pause")}>暂停</button>
            <button className="secondary" disabled={agent.data.status !== "paused"} type="button" onClick={() => action.mutate("resume")}>恢复</button>
            <button className="danger" disabled={agent.data.status === "terminated"} type="button" onClick={() => action.mutate("terminate")}>终止</button>
            <button disabled={agent.data.status === "paused" || agent.data.status === "terminated"} type="button" onClick={() => invoke.mutate()}>运行心跳</button>
          </div>
        )}
      </header>
      {action.error && <ErrorNotice error={action.error} />}
      {invoke.error && <ErrorNotice error={invoke.error} />}
      {agent.data && (
        <>
          <nav aria-label="智能体详情导航" className="detail-tabs">
            <NavLink to={`/orgs/${orgId}/agents/${agentId}/dashboard`}>概览</NavLink>
            <NavLink to={`/orgs/${orgId}/agents/${agentId}/profile`}>说明</NavLink>
            <NavLink to={`/orgs/${orgId}/agents/${agentId}/configuration`}>配置</NavLink>
            <NavLink to={`/orgs/${orgId}/agents/${agentId}/skills`}>技能</NavLink>
            <NavLink to={`/orgs/${orgId}/agents/${agentId}/runs`}>运行</NavLink>
          </nav>
          {activeTab === "dashboard" && <div className="agent-dashboard">
            <section className="panel agent-latest-run-card">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Latest Run</p>
                  <h2>{selectedRun ? selectedRun.id.slice(0, 8) : "No runs yet"}</h2>
                  <p className="muted">{summarizeRun(selectedRun)}</p>
                </div>
                {selectedRun && <Badge>{selectedRun.status}</Badge>}
              </div>
              <dl className="detail-grid compact">
                <div><dt>Source</dt><dd>{selectedRun?.invocationSource ?? "-"}</dd></div>
                <div><dt>Started</dt><dd>{formatRunTime(selectedRun?.startedAt)}</dd></div>
                <div><dt>Finished</dt><dd>{formatRunTime(selectedRun?.finishedAt)}</dd></div>
                <div><dt>Last Heartbeat</dt><dd>{agent.data.lastHeartbeatAt ?? "暂无"}</dd></div>
              </dl>
            </section>
            <section className="panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Runtime</p>
                  <h2>Runtime State</h2>
                </div>
              </div>
              {runtimeState.error && <ErrorNotice error={runtimeState.error} />}
              {runtimeState.data && (
                <div className="agent-summary-grid">
                  <div className="summary-metric"><span>Last Run</span><strong>{runtimeState.data.lastRunStatus ?? "暂无"}</strong></div>
                  <div className="summary-metric"><span>Session</span><strong>{runtimeState.data.sessionDisplayId ?? "暂无"}</strong></div>
                  <div className="summary-metric"><span>Tokens</span><strong>{runtimeState.data.totalInputTokens + runtimeState.data.totalOutputTokens}</strong></div>
                  <div className="summary-metric"><span>Cost</span><strong>{runtimeState.data.totalCostCents} cents</strong></div>
                </div>
              )}
            </section>
            <section className="panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Profile</p>
                  <h2>智能体档案</h2>
                </div>
              </div>
              <dl className="agent-properties">
                <div><dt>职务</dt><dd>{agent.data.title ?? "未设置"}</dd></div>
                <div><dt>角色</dt><dd>{agent.data.role}</dd></div>
                <div><dt>上级</dt><dd>{agent.data.reportsTo ?? "未设置"}</dd></div>
                <div><dt>能力</dt><dd>{agent.data.capabilities ?? "未设置"}</dd></div>
              </dl>
            </section>
          </div>}
          {activeTab === "profile" && <section aria-label="Managed Instructions" className="agent-instructions-page">
            {save.error && <ErrorNotice error={save.error} />}
            <div className="agent-instructions-grid">
              <aside aria-label="Instruction files" className="instruction-files-card">
                <div className="instruction-card-header">
                  <h2>Files</h2>
                  <button
                    aria-expanded={showInstructionForm}
                    aria-label="新增文件"
                    className="icon-button"
                    onClick={() => (showInstructionForm ? closeInstructionForm() : openInstructionForm())}
                    type="button"
                  >
                    +
                  </button>
                </div>
                {showInstructionForm && (
                  <form className="instruction-create-form" onSubmit={appendInstruction}>
                    <label>
                      文件名
                      <input value={newInstructionName} onChange={(event) => setNewInstructionName(event.target.value)} required />
                    </label>
                    <div className="instruction-create-actions">
                      <button className="secondary small-button" onClick={closeInstructionForm} type="button">取消</button>
                      <button className="small-button" disabled={save.isPending} type="submit">确认</button>
                    </div>
                  </form>
                )}
                <ul className="instruction-file-list">
                  {instructionDocs.map((doc) => (
                    <li
                      className={selectedInstruction?.key === doc.key ? "selected" : undefined}
                      key={doc.key}
                    >
                      <button onClick={() => setSelectedInstructionKey(doc.key)} type="button">
                        <code>{doc.name}</code>
                      </button>
                    </li>
                  ))}
                </ul>
              </aside>
              <article aria-label="Instruction content" className="instruction-content-card">
                {selectedInstruction?.content ? (
                  <pre>{selectedInstruction.content}</pre>
                ) : (
                  <div className="instruction-empty-content" />
                )}
              </article>
            </div>
          </section>}
          {activeTab === "configuration" && (
            <div className="agent-configuration-layout">
              <form className="panel agent-config-card" onSubmit={submit}>
                <div className="panel-heading">
                  <div>
                    <p className="eyebrow">Configuration</p>
                    <h2>基础配置</h2>
                    <p className="muted">按上游详情页的属性行布局展示，运行配置保留可编辑 JSON。</p>
                  </div>
                </div>
                <div className="agent-property-list">
                  <label className="agent-property-row"><span>智能体名称</span><input value={name} onChange={(event) => setName(event.target.value)} required /></label>
                  <label className="agent-property-row"><span>职务</span><input value={title} onChange={(event) => setTitle(event.target.value)} /></label>
                  <label className="agent-property-row">
                    <span>角色</span>
                  <select value={role} onChange={(event) => setRole(event.target.value as AgentRole)}>
                    {ROLES.map((item) => <option key={item}>{item}</option>)}
                  </select>
                </label>
                  <label className="agent-property-row">
                    <span>上级智能体</span>
                  <select value={reportsTo} onChange={(event) => setReportsTo(event.target.value)}>
                    <option value="">未设置</option>
                    {(organizationAgents.data ?? [])
                      .filter((item) => item.id !== agentId)
                      .map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
                  </select>
                </label>
                  <label className="agent-property-row agent-property-row-start"><span>能力描述</span><textarea value={capabilities} onChange={(event) => setCapabilities(event.target.value)} /></label>
                  <label className="agent-property-row">
                    <span>Runtime</span>
                  <select value={runtime} onChange={(event) => setRuntime(event.target.value as AgentRuntimeType)}>
                    {RUNTIMES.map((item) => <option key={item}>{item}</option>)}
                  </select>
                </label>
                  <label className="agent-property-row"><span>月度预算（cents）</span><input min="0" type="number" value={budgetMonthlyCents} onChange={(event) => setBudgetMonthlyCents(event.target.value)} required /></label>
                  <label className="agent-property-row"><span>Desired Skills</span><input value={desiredSkills} onChange={(event) => setDesiredSkills(event.target.value)} /></label>
                  <label className="agent-property-row agent-property-row-start"><span>Agent runtime config</span><textarea className="config-editor" value={agentRuntimeConfig} onChange={(event) => setAgentRuntimeConfig(event.target.value)} /></label>
                  <label className="agent-property-row agent-property-row-start"><span>Runtime config</span><textarea className="config-editor" value={runtimeConfig} onChange={(event) => setRuntimeConfig(event.target.value)} /></label>
                </div>
                {configurationError && <p className="error-notice">{configurationError}</p>}
                {save.error && <ErrorNotice error={save.error} />}
                <div className="agent-property-actions">
                  <button disabled={save.isPending} type="submit">保存配置</button>
                </div>
              </form>
              <section className="panel agent-config-revisions-card">
                <div className="panel-heading">
                  <div>
                    <p className="eyebrow">Adapter</p>
                    <h2>Runtime Adapter</h2>
                  </div>
                  <button disabled={testAdapterEnvironment.isPending} onClick={() => testAdapterEnvironment.mutate()} type="button">
                    测试环境
                  </button>
                </div>
                {adapterModels.error && <ErrorNotice error={adapterModels.error} />}
                {adapterMetadata.error && <ErrorNotice error={adapterMetadata.error} />}
                {adapterQuotaWindows.error && <ErrorNotice error={adapterQuotaWindows.error} />}
                {testAdapterEnvironment.error && <ErrorNotice error={testAdapterEnvironment.error} />}
                <div className="agent-summary-grid">
                  <div className="summary-metric"><span>Runtime</span><strong>{runtime}</strong></div>
                  <div className="summary-metric"><span>Models</span><strong>{adapterModelRows.length}</strong></div>
                  <div className="summary-metric"><span>Skills</span><strong>{adapterMetadata.data?.capabilities?.skills ? "supported" : "unsupported"}</strong></div>
                  <div className="summary-metric"><span>Quota</span><strong>{adapterQuotaWindows.data?.ok ? "ok" : (adapterQuotaWindows.data?.error ?? "unknown")}</strong></div>
                </div>
                <div className="list">
                  {adapterModelRows.map((model) => (
                    <article className="row" key={model.id}>
                      <strong>{model.label}</strong>
                      <span className="muted">{model.id}</span>
                    </article>
                  ))}
                </div>
                {adapterTestChecks.length > 0 && (
                  <div className="list">
                    {adapterTestChecks.map((check) => (
                      <article className="row" key={check.id ?? check.label}>
                        <strong>{check.label ?? check.id}</strong>
                        <Badge>{check.status ?? "unknown"}</Badge>
                        {check.message && <span className="muted">{check.message}</span>}
                      </article>
                    ))}
                  </div>
                )}
              </section>
              <section className="panel agent-config-revisions-card">
                <div className="panel-heading">
                  <div>
                    <p className="eyebrow">Skills</p>
                    <h2>Agent Skills</h2>
                  </div>
                  <Badge>{skills.data?.mode ?? "unknown"}</Badge>
                </div>
                {skills.error && <ErrorNotice error={skills.error} />}
                {skillsAnalytics.error && <ErrorNotice error={skillsAnalytics.error} />}
                {syncSkills.error && <ErrorNotice error={syncSkills.error} />}
                {enableSkills.error && <ErrorNotice error={enableSkills.error} />}
                {createPrivateSkill.error && <ErrorNotice error={createPrivateSkill.error} />}
                <div className="agent-summary-grid">
                  <div className="summary-metric"><span>Desired</span><strong>{skills.data?.desiredSkills?.length ?? 0}</strong></div>
                  <div className="summary-metric"><span>Entries</span><strong>{skillEntries.length}</strong></div>
                  <div className="summary-metric"><span>Usage</span><strong>{skillsAnalytics.data?.totalCount ?? 0}</strong></div>
                </div>
                <div className="list">
                  {skillEntries.map((entry) => (
                    <article className="row" key={String(entry.key ?? entry.selectionKey ?? entry.runtimeName)}>
                      <strong>{String(entry.runtimeName ?? entry.key ?? entry.selectionKey ?? "skill")}</strong>
                      {Boolean(entry.key) && <span className="muted">{String(entry.key)}</span>}
                    </article>
                  ))}
                </div>
                <div className="form">
                  <label>
                    Enable Skills
                    <input value={skillsToEnable} onChange={(event) => setSkillsToEnable(event.target.value)} />
                  </label>
                  <button disabled={enableSkills.isPending} onClick={() => enableSkills.mutate()} type="button">启用技能</button>
                  <button disabled={syncSkills.isPending} onClick={() => syncSkills.mutate()} type="button">同步技能</button>
                  <label>
                    Private Skill Name
                    <input value={privateSkillName} onChange={(event) => setPrivateSkillName(event.target.value)} />
                  </label>
                  <label>
                    Private Skill Markdown
                    <textarea value={privateSkillMarkdown} onChange={(event) => setPrivateSkillMarkdown(event.target.value)} />
                  </label>
                  <button disabled={!privateSkillName.trim() || createPrivateSkill.isPending} onClick={() => createPrivateSkill.mutate()} type="button">创建私有技能</button>
                </div>
              </section>
              <section className="panel agent-config-revisions-card">
                <div className="panel-heading">
                  <div>
                    <p className="eyebrow">Runtime</p>
                    <h2>Runtime State</h2>
                  </div>
                  <button disabled={resetSession.isPending} onClick={() => resetSession.mutate()} type="button">
                    重置会话
                  </button>
                </div>
                {runtimeState.error && <ErrorNotice error={runtimeState.error} />}
                {resetSession.error && <ErrorNotice error={resetSession.error} />}
                {runtimeState.data && (
                  <div className="agent-summary-grid">
                    <div className="summary-metric"><span>Session</span><strong>{runtimeState.data.sessionDisplayId ?? "暂无"}</strong></div>
                    <div className="summary-metric"><span>Last Run</span><strong>{runtimeState.data.lastRunStatus ?? "暂无"}</strong></div>
                  </div>
                )}
              </section>
              <section className="panel agent-config-revisions-card">
                <div className="panel-heading">
                  <div>
                    <p className="eyebrow">History</p>
                    <h2>Config Revisions</h2>
                  </div>
                </div>
                {configRevisions.error && <ErrorNotice error={configRevisions.error} />}
                {rollbackRevision.error && <ErrorNotice error={rollbackRevision.error} />}
                {configRevisions.isSuccess && revisionRows.length === 0 && <p className="muted">暂无配置版本。</p>}
                <div className="list">
                  {revisionRows.map((revision) => (
                    <article className="row" key={revision.id}>
                      <div>
                        <strong>{revision.id}</strong>
                        <p className="muted">{revision.createdAt || "未记录创建时间"}</p>
                      </div>
                      <button
                        className="secondary"
                        disabled={rollbackRevision.isPending}
                        onClick={() => rollbackRevision.mutate(revision.id)}
                        type="button"
                      >
                        回滚
                      </button>
                    </article>
                  ))}
                </div>
              </section>
            </div>
          )}
          {activeTab === "skills" && <section className="panel agent-config-revisions-card">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">Skills</p>
                <h2>Agent Skills</h2>
              </div>
              <Badge>{skills.data?.mode ?? "unknown"}</Badge>
            </div>
            {skills.error && <ErrorNotice error={skills.error} />}
            {skillsAnalytics.error && <ErrorNotice error={skillsAnalytics.error} />}
            {syncSkills.error && <ErrorNotice error={syncSkills.error} />}
            {enableSkills.error && <ErrorNotice error={enableSkills.error} />}
            {createPrivateSkill.error && <ErrorNotice error={createPrivateSkill.error} />}
            <div className="agent-summary-grid">
              <div className="summary-metric"><span>Desired</span><strong>{skills.data?.desiredSkills?.length ?? 0}</strong></div>
              <div className="summary-metric"><span>Entries</span><strong>{skillEntries.length}</strong></div>
              <div className="summary-metric"><span>Usage</span><strong>{skillsAnalytics.data?.totalCount ?? 0}</strong></div>
            </div>
            <div className="list">
              {skillEntries.map((entry) => (
                <article className="row" key={String(entry.key ?? entry.selectionKey ?? entry.runtimeName)}>
                  <strong>{String(entry.runtimeName ?? entry.key ?? entry.selectionKey ?? "skill")}</strong>
                  {Boolean(entry.key) && <span className="muted">{String(entry.key)}</span>}
                </article>
              ))}
            </div>
            <div className="form">
              <label>
                Desired Skills
                <input value={desiredSkills} onChange={(event) => setDesiredSkills(event.target.value)} />
              </label>
              <label>
                Enable Skills
                <input value={skillsToEnable} onChange={(event) => setSkillsToEnable(event.target.value)} />
              </label>
              <button disabled={enableSkills.isPending} onClick={() => enableSkills.mutate()} type="button">启用技能</button>
              <button disabled={syncSkills.isPending} onClick={() => syncSkills.mutate()} type="button">同步技能</button>
              <label>
                Private Skill Name
                <input value={privateSkillName} onChange={(event) => setPrivateSkillName(event.target.value)} />
              </label>
              <label>
                Private Skill Markdown
                <textarea value={privateSkillMarkdown} onChange={(event) => setPrivateSkillMarkdown(event.target.value)} />
              </label>
              <button disabled={!privateSkillName.trim() || createPrivateSkill.isPending} onClick={() => createPrivateSkill.mutate()} type="button">创建私有技能</button>
            </div>
          </section>}
          {activeTab === "runs" && <div className="agent-runs-layout">
            {runs.error && <ErrorNotice error={runs.error} />}
            <AgentRunDetail run={selectedRun} />
            <aside className="panel agent-run-rail" data-testid="agent-runs-list-pane">
              <div className="panel-heading">
                <div>
                  <h2>Runs</h2>
                  <p className="muted">最近运行</p>
                </div>
              </div>
              {runs.isSuccess && sortedRuns.length === 0 && <p className="muted">No runs yet.</p>}
              {sortedRuns.map((run) => (
                <button
                  className={`agent-run-list-button ${selectedRun?.id === run.id ? "selected" : ""}`}
                  key={run.id}
                  onClick={() => setSelectedRunId(run.id)}
                  type="button"
                >
                  <span>
                    <strong>{run.id.slice(0, 8)}</strong>
                    <small>{summarizeRun(run)}</small>
                  </span>
                  <Badge>{run.status}</Badge>
                </button>
              ))}
            </aside>
          </div>}
        </>
      )}
      {taskDialogOpen && agent.data && (
        <div
          className="modal-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setTaskDialogOpen(false);
          }}
          role="presentation"
        >
          <section aria-labelledby="assign-task-title" aria-modal="true" className="panel task-modal" role="dialog">
            <div className="task-modal-header">
              <h2 id="assign-task-title">分配任务</h2>
              <button aria-label="关闭" className="secondary" onClick={() => setTaskDialogOpen(false)} type="button">关闭</button>
            </div>
            <p className="muted">负责人：{agent.data.name}</p>
            <form className="form" onSubmit={submitTask}>
              <label>
                任务标题
                <input autoFocus value={taskTitle} onChange={(event) => setTaskTitle(event.target.value)} required />
              </label>
              {assignTask.error && <ErrorNotice error={assignTask.error} />}
              <div className="task-modal-actions">
                <button className="secondary" onClick={() => setTaskDialogOpen(false)} type="button">取消</button>
                <button disabled={assignTask.isPending} type="submit">创建任务</button>
              </div>
            </form>
          </section>
        </div>
      )}
    </AgentsWorkspace>
  );
}
