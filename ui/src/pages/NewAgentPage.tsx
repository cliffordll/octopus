import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { agentsApi } from "../api/agents";
import type { AgentRole, AgentRuntimeType } from "../api/types";
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

function mergeModelConfig(config: Record<string, unknown>, runtime: AgentRuntimeType, model: string): Record<string, unknown> {
  if (runtime !== "opencode_local") return config;
  const trimmed = model.trim() || (typeof config.model === "string" ? config.model.trim() : "");
  const [provider, modelName] = trimmed.split("/", 2);
  if (!trimmed || !provider?.trim() || !modelName?.trim()) {
    throw new Error("OpenCode model 必须使用 provider/model 格式，例如 openai/gpt-5。");
  }
  return { ...config, model: trimmed };
}

function parseCsv(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

export function NewAgentPage() {
  const { orgId = "" } = useParams();
  const [name, setName] = useState("");
  const [role, setRole] = useState<AgentRole>("engineer");
  const [runtime, setRuntime] = useState<AgentRuntimeType>("process");
  const [title, setTitle] = useState("");
  const [capabilities, setCapabilities] = useState("");
  const [budgetMonthlyCents, setBudgetMonthlyCents] = useState("");
  const [agentRuntimeConfig, setAgentRuntimeConfig] = useState("{}");
  const [opencodeModel, setOpencodeModel] = useState("");
  const [metadata, setMetadata] = useState("{}");
  const [configurationError, setConfigurationError] = useState("");
  const [desiredSkills, setDesiredSkills] = useState("");
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const agents = useQuery({ queryKey: ["agents", orgId], queryFn: () => agentsApi.list(orgId) });
  const nameSuggestion = useQuery({
    queryKey: ["agent-name-suggestion", orgId],
    queryFn: () => agentsApi.nameSuggestion(orgId),
  });
  const isFirstAgent = agents.isSuccess && agents.data.length === 0;
  const effectiveRole: AgentRole = isFirstAgent ? "ceo" : role;
  const create = useMutation({
    mutationFn: () =>
      agentsApi.create(orgId, {
        name: name.trim(),
        role: effectiveRole,
        ...(title.trim() ? { title: title.trim() } : {}),
        ...(capabilities.trim() ? { capabilities: capabilities.trim() } : {}),
        agentRuntimeType: runtime,
        agentRuntimeConfig: mergeModelConfig(readJsonObject(agentRuntimeConfig, "Agent runtime config"), runtime, opencodeModel),
        ...(budgetMonthlyCents.trim() ? { budgetMonthlyCents: Number(budgetMonthlyCents) } : {}),
        ...(metadata.trim() && metadata.trim() !== "{}" ? { metadata: readJsonObject(metadata, "Metadata") } : {}),
        ...(desiredSkills.trim() ? { desiredSkills: parseCsv(desiredSkills) } : {}),
      }),
    onSuccess: (agent) => {
      void queryClient.invalidateQueries({ queryKey: ["agents", orgId] });
      navigate(`/orgs/${orgId}/agents/${agent.id}/configuration`);
    },
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    if (!name.trim()) return;
    try {
      setConfigurationError("");
      mergeModelConfig(readJsonObject(agentRuntimeConfig, "Agent runtime config"), runtime, opencodeModel);
      if (metadata.trim() && metadata.trim() !== "{}") readJsonObject(metadata, "Metadata");
      create.mutate();
    } catch (error) {
      setConfigurationError(error instanceof Error ? error.message : "配置格式无效");
    }
  }
  return (
    <AgentsWorkspace orgId={orgId}>
      <header className="page-header">
        <div>
          <Link className="back-link" to={`/orgs/${orgId}/agents`}>返回智能体列表</Link>
          <h1>{isFirstAgent ? "创建 CEO" : "新建智能体"}</h1>
        </div>
      </header>
      <form className="panel form agent-create-form" onSubmit={submit}>
        {isFirstAgent && <p className="muted">首个智能体将作为 CEO 创建</p>}
        <label>
          智能体名称
          <div className="inline-input-action">
            <input value={name} onChange={(event) => setName(event.target.value)} required />
            <button
              className="secondary small-button"
              disabled={!nameSuggestion.data?.name}
              onClick={() => setName(nameSuggestion.data?.name ?? "")}
              type="button"
            >
              使用名称建议
            </button>
          </div>
        </label>
        {nameSuggestion.error && <ErrorNotice error={nameSuggestion.error} />}
        <label>
          标题
          <input value={title} onChange={(event) => setTitle(event.target.value)} />
        </label>
        <label>
          角色
          <select disabled={isFirstAgent} value={effectiveRole} onChange={(event) => setRole(event.target.value as AgentRole)}>
            {ROLES.map((item) => <option key={item}>{item}</option>)}
          </select>
        </label>
        <label>
          能力说明
          <textarea value={capabilities} onChange={(event) => setCapabilities(event.target.value)} />
        </label>
        <label>
          Runtime
          <select value={runtime} onChange={(event) => setRuntime(event.target.value as AgentRuntimeType)}>
            {RUNTIMES.map((item) => <option key={item}>{item}</option>)}
          </select>
        </label>
        {runtime === "opencode_local" && (
          <label>
            OpenCode model
            <input
              placeholder="openai/gpt-5"
              value={opencodeModel}
              onChange={(event) => setOpencodeModel(event.target.value)}
            />
          </label>
        )}
        <label>
          月度预算（cents）
          <input min="0" type="number" value={budgetMonthlyCents} onChange={(event) => setBudgetMonthlyCents(event.target.value)} />
        </label>
        <label>
          Desired Skills
          <input value={desiredSkills} onChange={(event) => setDesiredSkills(event.target.value)} />
        </label>
        <label>
          Agent runtime config
          <textarea className="config-editor" value={agentRuntimeConfig} onChange={(event) => setAgentRuntimeConfig(event.target.value)} />
        </label>
        <label>
          Metadata
          <textarea className="config-editor" value={metadata} onChange={(event) => setMetadata(event.target.value)} />
        </label>
        {configurationError && <p className="error-notice">{configurationError}</p>}
        {create.error && <ErrorNotice error={create.error} />}
        <button disabled={!agents.isSuccess || create.isPending} type="submit">
          {isFirstAgent ? "创建 CEO" : "新建智能体"}
        </button>
      </form>
    </AgentsWorkspace>
  );
}
