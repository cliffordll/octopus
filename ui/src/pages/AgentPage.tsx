import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState, type CSSProperties, type FormEvent, type KeyboardEvent, type MouseEvent } from "react";
import { Link, NavLink, useNavigate, useParams } from "react-router-dom";
import { agentsApi } from "../api/agents";
import { heartbeatApi } from "../api/heartbeat";
import { issuesApi } from "../api/issues";
import type { AgentRole, AgentRuntimeType, HeartbeatRun, HeartbeatRunEvent, LogReadResult, UpdateAgentPayload, WorkspaceOperation } from "../api/types";
import { Badge } from "../components/Badge";
import { AgentsWorkspace } from "../components/ContextWorkspace";
import { ErrorNotice } from "../components/ErrorNotice";

const ROLES: AgentRole[] = ["ceo", "cto", "cmo", "cfo", "engineer", "designer", "pm", "qa", "devops", "researcher", "general"];
const RUNTIMES: AgentRuntimeType[] = [
  "process",
  "http",
  "claude_local",
  "codex_local",
  "gemini_local",
  "opencode_local",
  "pi_local",
  "cursor",
  "openclaw_gateway",
  "hermes_local",
];

function readJsonObject(value: string, label: string): Record<string, unknown> {
  const parsed: unknown = JSON.parse(value);
  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error(`${label} 必须是 JSON 对象`);
  }
  return parsed as Record<string, unknown>;
}

function validatedAgentRuntimeConfig(runtime: AgentRuntimeType, value: string): Record<string, unknown> {
  const config = readJsonObject(value, "Agent runtime config");
  if (runtime !== "opencode_local") return config;
  const model = typeof config.model === "string" ? config.model.trim() : "";
  const [provider, modelName] = model.split("/", 2);
  if (!model || !provider?.trim() || !modelName?.trim()) {
    throw new Error("OpenCode model 必须使用 provider/model 格式，例如 openai/gpt-5。");
  }
  return { ...config, model };
}

function parseCsv(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

type InstructionDoc = {
  content: string;
  editable: boolean;
  isEntryFile: boolean;
  key: string;
  name: string;
  path: string;
  source: string;
  virtual: boolean;
};

type InstructionFileTreeNode = {
  children: Map<string, InstructionFileTreeNode>;
  files: InstructionDoc[];
  name: string;
  path: string;
};

function createInstructionFileTreeNode(name: string, path: string): InstructionFileTreeNode {
  return { children: new Map(), files: [], name, path };
}

function buildInstructionFileTree(files: InstructionDoc[]): InstructionFileTreeNode {
  const root = createInstructionFileTreeNode("", "");
  for (const file of [...files].sort((a, b) => a.path.localeCompare(b.path))) {
    const parts = file.path.split("/").filter(Boolean);
    if (parts.length <= 1) {
      root.files.push(file);
      continue;
    }
    let node = root;
    for (const segment of parts.slice(0, -1)) {
      const path = node.path ? `${node.path}/${segment}` : segment;
      let child = node.children.get(segment);
      if (!child) {
        child = createInstructionFileTreeNode(segment, path);
        node.children.set(segment, child);
      }
      node = child;
    }
    node.files.push(file);
  }
  return root;
}

function instructionFileDirectoryAncestors(path: string): string[] {
  const parts = path.split("/").filter(Boolean);
  if (parts.length <= 1) return [];
  return parts.slice(0, -1).map((_, index) => parts.slice(0, index + 1).join("/"));
}

function instructionFileTreeCount(node: InstructionFileTreeNode): number {
  let count = node.files.length;
  for (const child of node.children.values()) count += instructionFileTreeCount(child);
  return count;
}

function InstructionFileTree({
  expandedDirs,
  files,
  onSelect,
  onToggle,
  selectedPath,
}: {
  expandedDirs: Set<string>;
  files: InstructionDoc[];
  onSelect: (path: string) => void;
  onToggle: (path: string) => void;
  selectedPath: string;
}) {
  const tree = buildInstructionFileTree(files);
  function renderFile(file: InstructionDoc, level: number) {
    return (
      <button
        className={`instruction-file-button ${selectedPath === file.path ? "selected" : ""}`}
        key={file.path}
        onClick={() => onSelect(file.path)}
        style={{ "--instruction-file-depth": level } as CSSProperties}
        type="button"
      >
        <span className="instruction-file-label">
          <span className="instruction-file-icon" aria-hidden="true">F</span>
          <span>{file.path.split("/").at(-1) ?? file.path}</span>
        </span>
      </button>
    );
  }
  function renderNode(node: InstructionFileTreeNode, level = 0) {
    const directories = Array.from(node.children.values()).sort((a, b) => a.name.localeCompare(b.name));
    return (
      <>
        {node.files.map((file) => renderFile(file, level))}
        {directories.map((directory) => {
          const expanded = expandedDirs.has(directory.path);
          return (
            <div className="instruction-directory" key={directory.path}>
              <button
                aria-expanded={expanded}
                className="instruction-directory-button"
                onClick={() => onToggle(directory.path)}
                style={{ "--instruction-file-depth": level } as CSSProperties}
                type="button"
              >
                <span className="instruction-file-label">
                  <span className="instruction-directory-icon" aria-hidden="true">D</span>
                  <span>{directory.name}</span>
                </span>
                <small>{instructionFileTreeCount(directory)}</small>
                <span className="instruction-directory-toggle" aria-hidden="true">{expanded ? "v" : ">"}</span>
              </button>
              {expanded && <div className="instruction-directory-children">{renderNode(directory, level + 1)}</div>}
            </div>
          );
        })}
      </>
    );
  }
  return <div className="instruction-file-tree">{renderNode(tree)}</div>;
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

function skillField(entry: Record<string, unknown>, keys: string[], fallback = "-"): string {
  for (const key of keys) {
    const value = entry[key];
    if (typeof value === "string" && value.trim()) return value.trim();
    if (typeof value === "number" || typeof value === "boolean") return String(value);
  }
  return fallback;
}

function skillNestedString(entry: Record<string, unknown>, path: string[]): string {
  let current: unknown = entry;
  for (const key of path) {
    if (!current || typeof current !== "object" || Array.isArray(current)) return "";
    current = (current as Record<string, unknown>)[key];
  }
  return typeof current === "string" && current.trim() ? current.trim() : "";
}

function normalizeSkillSource(value: string): string {
  return value.trim().toLowerCase().replaceAll("-", "_");
}

function skillSourceCandidates(entry: Record<string, unknown>): string[] {
  const keys = ["sourceClass", "source", "origin", "sourceBadge", "scope", "kind", "sourceKind", "sourceLocator", "sourcePath", "locationLabel", "selectionKey"];
  return [
    skillNestedString(entry, ["metadata", "sourceKind"]),
    ...keys.map((key) => skillField(entry, [key], "")),
  ]
    .map(normalizeSkillSource)
    .filter(Boolean);
}

function skillSourceKind(entry: Record<string, unknown>): string {
  return skillSourceCandidates(entry)[0] ?? "";
}

function isCommunitySkillEntry(entry: Record<string, unknown>): boolean {
  return skillSourceCandidates(entry).some((sourceKind) => (
    sourceKind === "community"
    || sourceKind === "community_preset"
    || sourceKind.includes("/community/")
    || sourceKind.includes("\\community\\")
  ));
}

function nestedSkillField(entry: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    const direct = entry[key];
    if (typeof direct === "string" && direct.trim() && direct.trim() !== "---") return direct.trim();
    if (direct && typeof direct === "object" && !Array.isArray(direct)) {
      const nested = nestedSkillField(direct as Record<string, unknown>, keys);
      if (nested) return nested;
    }
  }
  return "";
}

function descriptionFromMarkdown(value: unknown): string {
  if (typeof value !== "string" || !value.trim()) return "";
  const lines = value.split(/\r?\n/);
  if (lines[0]?.trim() === "---") {
    for (const line of lines.slice(1)) {
      const trimmed = line.trim();
      if (trimmed === "---") break;
      const match = trimmed.match(/^description\s*:\s*["']?(.+?)["']?$/i);
      if (match?.[1]?.trim()) return match[1].trim();
    }
  }
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed === "---" || trimmed.startsWith("#")) continue;
    if (/^[a-z0-9_-]+\s*:/i.test(trimmed)) continue;
    return trimmed;
  }
  return "";
}

function skillDescription(entry: Record<string, unknown>): string {
  const explicit = nestedSkillField(entry, ["description", "summary"]);
  if (explicit) return explicit;
  return descriptionFromMarkdown(entry.markdown ?? entry.prompt ?? entry.content);
}

function booleanSkillField(entry: Record<string, unknown>, key: string): boolean {
  return entry[key] === true;
}

function skillLoadNote(entry: Record<string, unknown>, enabled: boolean): string {
  const explicit = skillField(entry, ["loadNote", "loadingNote", "detail"], "");
  if (explicit) return explicit;
  if (booleanSkillField(entry, "alwaysEnabled")) return "每次智能体运行都会自动加载。";
  if (enabled) return "当前智能体已使用该技能，后续运行可加载。";
  return "";
}

function hasJsonObject(value: Record<string, unknown> | null | undefined): value is Record<string, unknown> {
  return Boolean(value && Object.keys(value).length > 0);
}

function formattedJson(value: Record<string, unknown>): string {
  return JSON.stringify(value, null, 2);
}

function skillEntryName(entry: Record<string, unknown>): string {
  return skillField(entry, ["runtimeName", "name", "key", "selectionKey"], "skill");
}

function skillActionName(entry: Record<string, unknown>): string {
  return skillField(entry, ["selectionKey", "key", "name", "runtimeName"], "skill");
}

function skillEntryKey(entry: Record<string, unknown>, index: number): string {
  return String(entry.key ?? entry.selectionKey ?? entry.runtimeName ?? entry.name ?? index);
}

function skillEnabled(entry: Record<string, unknown>, desiredSkills: string[]): boolean {
  const value = entry.enabled;
  if (typeof value === "boolean") return value;
  const names = skillAliases(entry)
    .map((item) => item.toLowerCase())
    .filter(Boolean);
  const desired = desiredSkills.map((item) => item.toLowerCase());
  return names.some((name) => desired.includes(name));
}

function skillAliases(entry: Record<string, unknown>): string[] {
  return [entry.key, entry.name, entry.runtimeName, entry.selectionKey]
    .map((item) => (typeof item === "string" ? item.toLowerCase() : ""))
    .filter(Boolean);
}

function skillSourceGroup(entry: Record<string, unknown>): "组织技能" | "外部技能" {
  const sourceClass = skillSourceKind(entry);
  return ["bundled", "built_in", "organization", "community", "community_preset"].includes(sourceClass)
    || sourceClass.includes("bundled")
    || isCommunitySkillEntry(entry)
    ? "组织技能"
    : "外部技能";
}

function skillState(entry: Record<string, unknown>): string {
  return skillField(entry, ["state", "status"], "available");
}

function skillSourceLabel(entry: Record<string, unknown>): string {
  if (isCommunitySkillEntry(entry)) return "community";
  return skillNestedString(entry, ["metadata", "sourceKind"])
    || skillField(entry, ["sourceClass", "source", "origin", "sourceBadge", "scope", "kind", "sourceKind", "sourceLocator", "sourcePath", "selectionKey"], "runtime");
}

function skillDisplaySourceText(value: string | null | undefined, bundled: boolean): string {
  if (bundled) return "built-in";
  if (!value) return "-";
  const normalized = normalizeSkillSource(value);
  if (normalized === "community_preset") return "community";
  return value;
}

function isBuiltInSkillEntry(entry: Record<string, unknown>): boolean {
  const sourceClass = skillSourceKind(entry);
  return ["bundled", "built_in", "octopus_bundled", "system_bundled", "rudder_bundled"].includes(sourceClass);
}

function visibleSkillWarning(warning: string): boolean {
  return !/^skillsRootPath does not exist:/i.test(warning.trim());
}

function AgentRunDetail({
  events = [],
  eventsError,
  eventsLoading,
  log,
  logError,
  operations = [],
  operationsError,
  operationsLoading,
  run,
}: {
  events?: HeartbeatRunEvent[];
  eventsError?: unknown;
  eventsLoading?: boolean;
  log?: LogReadResult | null;
  logError?: unknown;
  operations?: WorkspaceOperation[];
  operationsError?: unknown;
  operationsLoading?: boolean;
  run: HeartbeatRun | null;
}) {
  if (!run) {
    return (
      <section className="panel agent-run-detail-card">
        <p className="muted">No runs yet.</p>
      </section>
    );
  }
  const hasUsage = Boolean(run.usageJson && Object.keys(run.usageJson).length > 0);
  const hasSession = Boolean(run.sessionIdBefore || run.sessionIdAfter);
  const hasContext = hasJsonObject(run.contextSnapshot);
  const hasResult = hasJsonObject(run.resultJson);
  const hasUsageJson = hasJsonObject(run.usageJson);
  const contextSnapshot = run.contextSnapshot ?? {};
  const resultJson = run.resultJson ?? {};
  const usageJson = run.usageJson ?? {};
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
        <div><dt>Error Code</dt><dd>{run.errorCode ?? "无"}</dd></div>
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
      {(run.stdoutExcerpt || run.stderrExcerpt) && (
        <section className="agent-run-debug-section">
          <h3>运行输出</h3>
          {run.stdoutExcerpt && (
            <div>
              <span className="agent-run-section-label">stdout</span>
              <pre className="run-excerpt">{run.stdoutExcerpt}</pre>
            </div>
          )}
          {run.stderrExcerpt && (
            <div>
              <span className="agent-run-section-label">stderr</span>
              <pre className="run-excerpt error">{run.stderrExcerpt}</pre>
            </div>
          )}
        </section>
      )}
      {(hasContext || hasResult || hasUsageJson) && (
        <section className="agent-run-debug-section">
          <h3>调试快照</h3>
          <div className="agent-run-json-grid">
            {hasContext && (
              <div>
                <span className="agent-run-section-label">contextSnapshot</span>
                <pre className="agent-run-json">{formattedJson(contextSnapshot)}</pre>
              </div>
            )}
            {hasResult && (
              <div>
                <span className="agent-run-section-label">resultJson</span>
                <pre className="agent-run-json">{formattedJson(resultJson)}</pre>
              </div>
            )}
            {hasUsageJson && (
              <div>
                <span className="agent-run-section-label">usageJson</span>
                <pre className="agent-run-json">{formattedJson(usageJson)}</pre>
              </div>
            )}
          </div>
        </section>
      )}
      <section className="agent-run-debug-section">
        <h3>事件</h3>
        {Boolean(eventsError) && <ErrorNotice error={eventsError} />}
        {eventsLoading && <p className="muted">加载事件中...</p>}
        {!eventsLoading && events.length === 0 && <p className="muted">暂无事件。</p>}
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
                {event.message && <p>{event.message}</p>}
                {hasJsonObject(event.payload) && <pre className="agent-run-json">{formattedJson(event.payload)}</pre>}
                <small className="muted">{event.createdAt}</small>
              </article>
            ))}
          </div>
        )}
      </section>
      <section className="agent-run-debug-section">
        <h3>原始日志</h3>
        {Boolean(logError) && <ErrorNotice error={logError} />}
        {log?.content ? (
          <pre className="agent-run-json">{log.content}</pre>
        ) : (
          <p className="muted">暂无日志。</p>
        )}
      </section>
      <section className="agent-run-debug-section">
        <h3>工作区操作</h3>
        {Boolean(operationsError) && <ErrorNotice error={operationsError} />}
        {operationsLoading && <p className="muted">加载工作区操作中...</p>}
        {!operationsLoading && operations.length === 0 && <p className="muted">暂无工作区操作。</p>}
        {operations.length > 0 && (
          <div className="agent-run-events">
            {operations.map((operation) => (
              <article className="agent-run-event" key={operation.id}>
                <div className="agent-run-event-header">
                  <strong>{operation.phase}</strong>
                  <Badge>{operation.status}</Badge>
                  {operation.exitCode !== undefined && operation.exitCode !== null && <Badge>Exit {operation.exitCode}</Badge>}
                </div>
                {operation.command && <p>{operation.command}</p>}
                {operation.stderrExcerpt && <pre className="run-excerpt error">{operation.stderrExcerpt}</pre>}
                {operation.stdoutExcerpt && <pre className="run-excerpt">{operation.stdoutExcerpt}</pre>}
                <small className="muted">{operation.cwd ?? operation.id}</small>
              </article>
            ))}
          </div>
        )}
      </section>
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
  const [newSkillName, setNewSkillName] = useState("");
  const [newSkillSlug, setNewSkillSlug] = useState("");
  const [newSkillDescription, setNewSkillDescription] = useState("");
  const [newSkillMarkdown, setNewSkillMarkdown] = useState("");
  const [skillDialogOpen, setSkillDialogOpen] = useState(false);
  const [selectedSkillKey, setSelectedSkillKey] = useState("");
  const [adapterTestChecks, setAdapterTestChecks] = useState<Array<{ label?: string; id?: string; status?: string; message?: string }>>([]);
  const [configurationError, setConfigurationError] = useState<string | null>(null);
  const [taskDialogOpen, setTaskDialogOpen] = useState(false);
  const [taskTitle, setTaskTitle] = useState("");
  const [selectedRunId, setSelectedRunId] = useState("");
  const [selectedInstructionKey, setSelectedInstructionKey] = useState("");
  const [expandedInstructionDirs, setExpandedInstructionDirs] = useState<Set<string>>(new Set());
  const [showInstructionForm, setShowInstructionForm] = useState(false);
  const [newInstructionName, setNewInstructionName] = useState("");
  const [instructionDraft, setInstructionDraft] = useState("");
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const agent = useQuery({ queryKey: ["agent", agentId], queryFn: () => agentsApi.get(agentId) });
  const organizationAgents = useQuery({ queryKey: ["agents", orgId], queryFn: () => agentsApi.list(orgId) });
  const runtimeState = useQuery({
    queryKey: ["agent-runtime-state", agentId],
    queryFn: () => agentsApi.runtimeState(agentId),
  });
  const configuration = useQuery({
    queryKey: ["agent-configuration", agentId],
    queryFn: () => agentsApi.configuration(agentId),
    enabled: activeTab === "configuration",
  });
  const configRevisions = useQuery({
    queryKey: ["agent-config-revisions", agentId],
    queryFn: () => agentsApi.configRevisions(agentId),
    enabled: activeTab === "configuration",
  });
  const taskSessions = useQuery({
    queryKey: ["agent-task-sessions", agentId],
    queryFn: () => agentsApi.taskSessions(agentId),
    enabled: activeTab === "configuration" || activeTab === "runs",
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
    enabled: activeTab === "skills",
  });
  const instructionsBundle = useQuery({
    queryKey: ["agent-instructions-bundle", agentId],
    queryFn: () => agentsApi.instructionsBundle(agentId),
    enabled: activeTab === "profile",
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
  const wakeup = useMutation({
    mutationFn: () => heartbeatApi.wakeup(agentId),
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
    mutationFn: () => agentsApi.testAdapterEnvironment(orgId, runtime, validatedAgentRuntimeConfig(runtime, agentRuntimeConfig)),
    onSuccess: (result) => setAdapterTestChecks(result.checks),
    onError: () => setAdapterTestChecks([]),
  });
  const syncSkills = useMutation({
    mutationFn: (nextDesiredSkills?: string[]) => agentsApi.syncSkills(agentId, nextDesiredSkills ?? parseCsv(desiredSkills)),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["agent-skills", agentId] });
      void queryClient.invalidateQueries({ queryKey: ["agent", agentId] });
    },
  });
  const enableSkills = useMutation({
    mutationFn: (names?: string[]) => agentsApi.enableSkills(agentId, names ?? parseCsv(skillsToEnable)),
    onSuccess: () => {
      setSkillsToEnable("");
      void queryClient.invalidateQueries({ queryKey: ["agent-skills", agentId] });
      void queryClient.invalidateQueries({ queryKey: ["agent", agentId] });
    },
  });
  const createPrivateSkill = useMutation({
    mutationFn: () => agentsApi.createPrivateSkill(agentId, {
      name: newSkillName.trim(),
      slug: newSkillSlug.trim() || null,
      description: newSkillDescription.trim() || null,
      markdown: newSkillMarkdown.trim() || null,
    }),
    onSuccess: () => {
      setNewSkillName("");
      setNewSkillSlug("");
      setNewSkillDescription("");
      setNewSkillMarkdown("");
      setSkillDialogOpen(false);
      void queryClient.invalidateQueries({ queryKey: ["agent-skills", agentId] });
    },
  });
  const upsertInstruction = useMutation({
    mutationFn: ({ path, content }: { path: string; content: string }) =>
      agentsApi.upsertInstructionFile(agentId, { path, content, clearLegacyPromptTemplate: true }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["agent-instructions-bundle", agentId] });
      void queryClient.invalidateQueries({ queryKey: ["agent-instructions-file", agentId] });
    },
  });
  const deleteInstruction = useMutation({
    mutationFn: (path: string) => agentsApi.deleteInstructionFile(agentId, path),
    onSuccess: () => {
      setSelectedInstructionKey("");
      setInstructionDraft("");
      void queryClient.invalidateQueries({ queryKey: ["agent-instructions-bundle", agentId] });
      void queryClient.invalidateQueries({ queryKey: ["agent-instructions-file", agentId] });
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
        agentRuntimeConfig: validatedAgentRuntimeConfig(runtime, agentRuntimeConfig),
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
  const canChat = agent.data?.status !== "terminated";
  const runRows = Array.isArray(runs.data) ? runs.data : [];
  const sortedRuns = useMemo(
    () => [...runRows].sort((a, b) => String(b.createdAt ?? "").localeCompare(String(a.createdAt ?? ""))),
    [runRows],
  );
  const selectedRun = sortedRuns.find((run) => run.id === selectedRunId) ?? sortedRuns[0] ?? null;
  const runEvents = useQuery({
    queryKey: ["heartbeat-run-events", selectedRun?.id],
    queryFn: () => heartbeatApi.listEvents(selectedRun!.id),
    enabled: activeTab === "runs" && Boolean(selectedRun?.id),
    refetchInterval: selectedRun?.status === "running" ? 5000 : false,
  });
  const runLog = useQuery({
    queryKey: ["heartbeat-run-log", selectedRun?.id],
    queryFn: () => heartbeatApi.getLog(selectedRun!.id),
    enabled: activeTab === "runs" && Boolean(selectedRun?.id),
    refetchInterval: selectedRun?.status === "running" ? 5000 : false,
  });
  const runWorkspaceOperations = useQuery({
    queryKey: ["heartbeat-run-workspace-operations", selectedRun?.id],
    queryFn: () => heartbeatApi.listWorkspaceOperations(selectedRun!.id),
    enabled: activeTab === "runs" && Boolean(selectedRun?.id),
    refetchInterval: selectedRun?.status === "running" ? 5000 : false,
  });
  const revisionRows = Array.isArray(configRevisions.data) ? configRevisions.data : [];
  const taskSessionRows = Array.isArray(taskSessions.data) ? taskSessions.data : [];
  const adapterModelRows = Array.isArray(adapterModels.data) ? adapterModels.data : [];
  const permissionRows = Object.entries(configuration.data?.permissions ?? {});
  const skillEntries = Array.isArray(skills.data?.entries) ? skills.data.entries : [];
  const desiredSkillRows = Array.isArray(skills.data?.desiredSkills) ? skills.data.desiredSkills : parseCsv(desiredSkills);
  const builtInSkillEntries = skillEntries.filter(isBuiltInSkillEntry);
  const communitySkillEntries = skillEntries.filter((entry) => !isBuiltInSkillEntry(entry) && isCommunitySkillEntry(entry));
  const externalSkillEntries = skillEntries.filter((entry) => skillSourceGroup(entry) === "外部技能");
  const skillWarnings = (skills.data?.warnings ?? []).filter(visibleSkillWarning);
  const bundleFiles = Array.isArray(instructionsBundle.data?.files) ? instructionsBundle.data.files : [];
  const instructionDocs: InstructionDoc[] = instructionsBundle.data
    ? bundleFiles.map((file) => ({
      content: "",
      editable: file.editable,
      isEntryFile: file.isEntryFile,
      key: file.path,
      name: file.path.split("/").at(-1) ?? file.path,
      path: file.path,
      source: file.virtual ? "virtual" : "instructions-bundle",
      virtual: file.virtual,
    }))
    : [];
  const selectedInstruction = instructionDocs.find((doc) => doc.key === selectedInstructionKey) ?? instructionDocs[0];
  const selectedBundleFile = useQuery({
    queryKey: ["agent-instructions-file", agentId, selectedInstruction?.path],
    queryFn: () => agentsApi.readInstructionFile(agentId, selectedInstruction!.path),
    enabled: activeTab === "profile" && bundleFiles.length > 0 && Boolean(selectedInstruction?.path),
  });
  const selectedInstructionContent = selectedBundleFile.data?.content ?? selectedInstruction?.content ?? "";
  useEffect(() => {
    if (!selectedInstruction?.path) return;
    const ancestors = instructionFileDirectoryAncestors(selectedInstruction.path);
    if (ancestors.length === 0) return;
    setExpandedInstructionDirs((current) => {
      const next = new Set(current);
      for (const ancestor of ancestors) next.add(ancestor);
      return next.size === current.size ? current : next;
    });
  }, [selectedInstruction?.path]);
  useEffect(() => {
    setInstructionDraft(selectedInstructionContent);
  }, [selectedInstructionContent]);
  function toggleInstructionDir(path: string) {
    setExpandedInstructionDirs((current) => {
      const next = new Set(current);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }
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
    if (!newInstructionName.trim()) return;
    upsertInstruction.mutate({ path: newInstructionName.trim(), content: "" });
    setSelectedInstructionKey(newInstructionName.trim());
    closeInstructionForm();
  }
  function enableSkill(name: string) {
    if (!name.trim()) return;
    enableSkills.mutate([name.trim()]);
  }
  function closeSkillDialog() {
    setSkillDialogOpen(false);
    setNewSkillName("");
    setNewSkillSlug("");
    setNewSkillDescription("");
    setNewSkillMarkdown("");
  }
  function disableSkill(name: string) {
    if (!name.trim()) return;
    const target = name.trim().toLowerCase();
    const entry = skillEntries.find((item) => skillAliases(item).includes(target));
    const targets = new Set(entry ? skillAliases(entry) : [target]);
    const nextDesired = desiredSkillRows.filter((item) => !targets.has(item.toLowerCase()));
    syncSkills.mutate(nextDesired);
  }
  function forkSkill(entry: Record<string, unknown>) {
    const name = `${skillEntryName(entry)}-fork`;
    const markdown = String(entry.markdown ?? entry.prompt ?? entry.content ?? "");
    agentsApi.createPrivateSkill(agentId, { name, markdown: markdown || null }).then(() => {
      void queryClient.invalidateQueries({ queryKey: ["agent-skills", agentId] });
    });
  }
  if (agent.error) return <ErrorNotice error={agent.error} />;
  return (
    <AgentsWorkspace contentClassName="org-content-full" orgId={orgId}>
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
            <button className="secondary" disabled={agent.data.status === "terminated" || wakeup.isPending} type="button" onClick={() => wakeup.mutate()}>唤醒</button>
            <button disabled={agent.data.status === "paused" || agent.data.status === "terminated"} type="button" onClick={() => invoke.mutate()}>运行心跳</button>
          </div>
        )}
      </header>
      {action.error && <ErrorNotice error={action.error} />}
      {invoke.error && <ErrorNotice error={invoke.error} />}
      {wakeup.error && <ErrorNotice error={wakeup.error} />}
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
            {instructionsBundle.error && <ErrorNotice error={instructionsBundle.error} />}
            {selectedBundleFile.error && <ErrorNotice error={selectedBundleFile.error} />}
            {upsertInstruction.error && <ErrorNotice error={upsertInstruction.error} />}
            {deleteInstruction.error && <ErrorNotice error={deleteInstruction.error} />}
            <div className="agent-instructions-grid">
              <aside aria-label="说明文件列表" className="instruction-files-card">
                <div className="instruction-card-header">
                  <h2>文件</h2>
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
                      <button className="small-button" disabled={upsertInstruction.isPending} type="submit">确认</button>
                    </div>
                  </form>
                )}
                <InstructionFileTree
                  expandedDirs={expandedInstructionDirs}
                  files={instructionDocs}
                  onSelect={setSelectedInstructionKey}
                  onToggle={toggleInstructionDir}
                  selectedPath={selectedInstruction?.path ?? ""}
                />
              </aside>
              <article aria-label="说明文件内容" className="instruction-content-card">
                {selectedInstruction ? (
                  <>
                    <textarea
                      aria-label="说明文件内容"
                      className="instruction-content-editor"
                      readOnly={selectedBundleFile.data?.editable === false}
                      value={instructionDraft}
                      onChange={(event) => setInstructionDraft(event.target.value)}
                    />
                    <div className="instruction-create-actions">
                      <button
                        className="danger"
                        disabled={selectedInstruction.isEntryFile || selectedBundleFile.data?.editable === false || deleteInstruction.isPending}
                        onClick={() => deleteInstruction.mutate(selectedInstruction.path)}
                        type="button"
                      >
                        删除文件
                      </button>
                      <button
                        disabled={selectedBundleFile.data?.editable === false || upsertInstruction.isPending}
                        onClick={() => upsertInstruction.mutate({ path: selectedInstruction.path, content: instructionDraft })}
                        type="button"
                      >
                        保存文件
                      </button>
                    </div>
                  </>
                ) : selectedInstructionContent ? (
                  <pre>{selectedInstructionContent}</pre>
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
                  </div>
                </div>
                <div className="agent-config-sections">
                  <section className="agent-config-section">
                    <div className="agent-config-section-heading">
                      <h2>身份</h2>
                      <p className="muted">智能体的名称、职责和组织汇报关系。</p>
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
                    </div>
                  </section>
                  <section className="agent-config-section">
                    <div className="agent-config-section-heading">
                      <h2>智能体运行时</h2>
                      <p className="muted">选择本地或外部运行适配器，并维护适配器配置。</p>
                    </div>
                    <div className="agent-property-list">
                      <label className="agent-property-row">
                        <span>Runtime</span>
                        <select value={runtime} onChange={(event) => setRuntime(event.target.value as AgentRuntimeType)}>
                          {RUNTIMES.map((item) => <option key={item}>{item}</option>)}
                        </select>
                      </label>
                      <label className="agent-property-row agent-property-row-start"><span>Agent runtime config</span><textarea className="config-editor" value={agentRuntimeConfig} onChange={(event) => setAgentRuntimeConfig(event.target.value)} /></label>
                    </div>
                  </section>
                  <section className="agent-config-section">
                    <div className="agent-config-section-heading">
                      <h2>运行策略</h2>
                      <p className="muted">预算、技能偏好和运行上下文策略。</p>
                    </div>
                    <div className="agent-property-list">
                      <label className="agent-property-row"><span>月度预算（cents）</span><input min="0" type="number" value={budgetMonthlyCents} onChange={(event) => setBudgetMonthlyCents(event.target.value)} required /></label>
                      <label className="agent-property-row"><span>Desired Skills</span><input value={desiredSkills} onChange={(event) => setDesiredSkills(event.target.value)} /></label>
                      <label className="agent-property-row agent-property-row-start"><span>Runtime config</span><textarea className="config-editor" value={runtimeConfig} onChange={(event) => setRuntimeConfig(event.target.value)} /></label>
                    </div>
                  </section>
                  <section className="agent-config-section">
                    <div className="agent-config-section-heading">
                      <h2>权限</h2>
                      <p className="muted">服务端返回的当前智能体权限快照。</p>
                    </div>
                    <div className="agent-permission-grid">
                      {permissionRows.length > 0 ? permissionRows.map(([key, enabled]) => (
                        <div className="agent-permission-item" key={key}>
                          <span>{key}</span>
                          <Badge>{enabled ? "允许" : "不允许"}</Badge>
                        </div>
                      )) : (
                        <p className="muted">当前接口未返回权限明细。</p>
                      )}
                    </div>
                  </section>
                  <section className="agent-config-section">
                    <div className="agent-config-section-heading">
                      <h2>API 密钥</h2>
                      <p className="muted">密钥不在页面明文保存；运行时通过环境变量、本地 CLI 登录或后续真实 secret 绑定提供。</p>
                    </div>
                    <div className="agent-summary-grid">
                      <div className="summary-metric"><span>本地 Agent JWT</span><strong>{adapterMetadata.data?.supportsLocalAgentJwt ? "支持" : "未开启"}</strong></div>
                      <div className="summary-metric"><span>认证检查</span><strong>{adapterTestChecks.find((check) => check.id === "auth")?.status ?? "未测试"}</strong></div>
                    </div>
                  </section>
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
                    <p className="eyebrow">Snapshot</p>
                    <h2>配置快照</h2>
                  </div>
                </div>
                {configuration.error && <ErrorNotice error={configuration.error} />}
                {configuration.data && (
                  <div className="agent-summary-grid">
                    <div className="summary-metric"><span>状态</span><strong>{configuration.data.status ?? "未知"}</strong></div>
                    <div className="summary-metric"><span>角色</span><strong>{configuration.data.role ?? "未知"}</strong></div>
                    <div className="summary-metric"><span>运行时</span><strong>{configuration.data.agentRuntimeType ?? "未知"}</strong></div>
                    <div className="summary-metric"><span>更新时间</span><strong>{configuration.data.updatedAt ?? "未记录"}</strong></div>
                  </div>
                )}
              </section>
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
                  <div className="summary-metric"><span>技能</span><strong>{adapterMetadata.data?.capabilities?.skills ? "支持" : "不支持"}</strong></div>
                  <div className="summary-metric"><span>Quota</span><strong>{adapterQuotaWindows.data?.ok ? "ok" : (adapterQuotaWindows.data?.error ?? "unknown")}</strong></div>
                </div>
                {adapterMetadata.data?.agentConfigurationDoc && (
                  <pre className="run-excerpt">{adapterMetadata.data.agentConfigurationDoc}</pre>
                )}
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
                    <p className="eyebrow">Runtime</p>
                    <h2>Runtime State</h2>
                  </div>
                  <button disabled={resetSession.isPending} onClick={() => resetSession.mutate()} type="button">
                    重置会话
                  </button>
                </div>
                {runtimeState.error && <ErrorNotice error={runtimeState.error} />}
                {resetSession.error && <ErrorNotice error={resetSession.error} />}
                {taskSessions.error && <ErrorNotice error={taskSessions.error} />}
                {runtimeState.data && (
                  <div className="agent-summary-grid">
                    <div className="summary-metric"><span>Session</span><strong>{runtimeState.data.sessionDisplayId ?? "暂无"}</strong></div>
                    <div className="summary-metric"><span>Last Run</span><strong>{runtimeState.data.lastRunStatus ?? "暂无"}</strong></div>
                  </div>
                )}
                <div className="list">
                  {taskSessionRows.map((session) => (
                    <article className="row" key={session.id}>
                      <div>
                        <strong>{session.taskKey}</strong>
                        <p className="muted">{session.sessionDisplayId ?? "暂无会话"} · {session.updatedAt}</p>
                      </div>
                      <Badge>{session.status}</Badge>
                    </article>
                  ))}
                </div>
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
          {activeTab === "skills" && <section className="agent-skills-page">
            <div className="agent-skills-page-header">
              <div>
                <h2>技能管理</h2>
                <p className="muted">管理当前智能体的技能列表、使用状态和私有技能安装。</p>
              </div>
              <button onClick={() => setSkillDialogOpen(true)} type="button">创建技能</button>
            </div>
            {skills.error && <ErrorNotice error={skills.error} />}
            {skillsAnalytics.error && <ErrorNotice error={skillsAnalytics.error} />}
            {syncSkills.error && <ErrorNotice error={syncSkills.error} />}
            {enableSkills.error && <ErrorNotice error={enableSkills.error} />}
            {createPrivateSkill.error && <ErrorNotice error={createPrivateSkill.error} />}
            <div className="agent-skills-library">
              {skillsAnalytics.data && (
                <section className="agent-skill-tags-card agent-skill-analytics-card">
                  <div className="agent-skill-source-heading">
                    <h3>使用分析</h3>
                    <Badge>{skillsAnalytics.data.windowDays ?? 30} 天</Badge>
                  </div>
                  <div className="agent-summary-grid">
                    <div className="summary-metric"><span>总次数</span><strong>{skillsAnalytics.data.totalCount ?? 0}</strong></div>
                    <div className="summary-metric"><span>运行次数</span><strong>{skillsAnalytics.data.totalRunsWithSkills ?? 0}</strong></div>
                    <div className="summary-metric"><span>技能数</span><strong>{skillsAnalytics.data.skills.length}</strong></div>
                  </div>
                </section>
              )}
              {[
                { label: "built-in", rows: builtInSkillEntries },
                { label: "community", rows: communitySkillEntries },
                { label: "外部技能", rows: externalSkillEntries },
              ].map((group) => (
                <section className="agent-skill-tags-card agent-skill-source-group" key={group.label}>
                  <div className="agent-skill-source-heading">
                    <h3>{group.label}</h3>
                    <Badge>{group.rows.length}</Badge>
                  </div>
                  <div className="agent-skill-tag-list">
                    {group.rows.map((entry, index) => {
                      const key = skillEntryKey(entry, index);
                      const selected = selectedSkillKey === key;
                      const name = skillEntryName(entry);
                      const actionName = skillActionName(entry);
                      const enabled = skillEnabled(entry, desiredSkillRows);
                      const isBundled = isBuiltInSkillEntry(entry);
                      const description = skillDescription(entry) || skillField(entry, ["detail"], "");
                      const version = skillField(entry, ["version"], "");
                      const sourceLabel = skillSourceLabel(entry);
                      const originLabel = skillField(entry, ["originLabel"], "");
                      const sourceText = skillDisplaySourceText(originLabel || sourceLabel, isBundled);
                      const loadNote = skillLoadNote(entry, enabled);
                      const state = skillState(entry);
                      const toggleSelectedSkill = () => setSelectedSkillKey(selected ? "" : key);
                      const onSkillKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
                        if (event.key !== "Enter" && event.key !== " ") return;
                        event.preventDefault();
                        toggleSelectedSkill();
                      };
                      const stopSkillActionClick = (event: MouseEvent) => event.stopPropagation();
                      return (
                        <article className={`agent-skill-tag ${selected ? "selected" : ""}`} key={key}>
                          <div
                            className="agent-skill-tag-main"
                            onClick={toggleSelectedSkill}
                            onKeyDown={onSkillKeyDown}
                            role="button"
                            tabIndex={0}
                          >
                            <span className="agent-skill-tag-title-row">
                              <code>{name}</code>
                              <span className="agent-skill-title-actions">
                                <span className={`agent-skill-enabled-pill ${enabled ? "enabled" : ""}`}>{enabled ? "使用中" : "未使用"}</span>
                                {isBundled ? (
                                  <button className="secondary small-button" disabled={createPrivateSkill.isPending} onClick={(event) => { stopSkillActionClick(event); forkSkill(entry); }} type="button">派生</button>
                                ) : (
                                  <>
                                    <button
                                      className="secondary small-button"
                                      disabled={enableSkills.isPending || syncSkills.isPending}
                                      onClick={(event) => {
                                        stopSkillActionClick(event);
                                        if (enabled) disableSkill(actionName);
                                        else enableSkill(actionName);
                                      }}
                                      type="button"
                                    >
                                      {enabled ? "取消使用" : "使用"}
                                    </button>
                                    <button className="danger small-button" disabled onClick={stopSkillActionClick} type="button">删除</button>
                                  </>
                                )}
                              </span>
                            </span>
                            <span className="agent-skill-tag-description">{description || "未填写描述"}</span>
                            {loadNote && <span className="agent-skill-tag-note">{loadNote}</span>}
                            <span className="agent-skill-tag-facts">
                              {!isCommunitySkillEntry(entry) && <span>{sourceText}</span>}
                              <span>{state}</span>
                              <span>{version ? `v${version}` : "-"}</span>
                            </span>
                          </div>
                        </article>
                      );
                    })}
                  </div>
                </section>
              ))}
            </div>
            {skillWarnings.map((warning) => <p className="error-notice" key={warning}>{warning}</p>)}
            {skillDialogOpen && (
              <div aria-modal="true" className="modal-backdrop" role="dialog">
                <section className="panel task-modal skill-create-dialog">
                  <div className="task-modal-header">
                    <div>
                      <h2>创建技能</h2>
                      <p className="muted">安装为当前智能体私有技能。Short name 可选，不填时由服务端根据名称生成。</p>
                    </div>
                  </div>
                  <label>
                    名称
                    <input value={newSkillName} onChange={(event) => setNewSkillName(event.target.value)} required />
                  </label>
                  <label>
                    Short name
                    <input value={newSkillSlug} onChange={(event) => setNewSkillSlug(event.target.value)} placeholder="incident-response" />
                  </label>
                  <label>
                    描述
                    <input value={newSkillDescription} onChange={(event) => setNewSkillDescription(event.target.value)} />
                  </label>
                  <label>
                    技能内容
                    <textarea
                      className="skill-yaml-textarea"
                      placeholder={"schema_version: 1\nprompt: ..."}
                      value={newSkillMarkdown}
                      onChange={(event) => setNewSkillMarkdown(event.target.value)}
                    />
                  </label>
                  <div className="task-modal-actions">
                    <button className="secondary" onClick={closeSkillDialog} type="button">取消</button>
                    <button disabled={!newSkillName.trim() || createPrivateSkill.isPending} onClick={() => createPrivateSkill.mutate()} type="button">
                      创建
                    </button>
                  </div>
                </section>
              </div>
            )}
          </section>}
          {activeTab === "runs" && <div className="agent-runs-layout">
            {runs.error && <ErrorNotice error={runs.error} />}
            <AgentRunDetail
              events={runEvents.data ?? []}
              eventsError={runEvents.error}
              eventsLoading={runEvents.isLoading}
              log={runLog.data}
              logError={runLog.error}
              operations={runWorkspaceOperations.data ?? []}
              operationsError={runWorkspaceOperations.error}
              operationsLoading={runWorkspaceOperations.isLoading}
              run={selectedRun}
            />
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
