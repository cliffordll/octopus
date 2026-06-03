import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { agentsApi } from "../api/agents";
import type { AgentRole, AgentRuntimeType, RuntimeModel } from "../api/types";
import { AgentsWorkspace } from "../components/ContextWorkspace";
import { ErrorNotice } from "../components/ErrorNotice";
import { listRuntimeModelOptions, runtimeModelLabel, runtimeModelReference, supportsRuntimeModels, validateModelReference } from "../utils/runtimeModels";

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
  if (!supportsRuntimeModels(runtime)) return config;
  const trimmed = model.trim() || (typeof config.model === "string" ? config.model.trim() : "");
  return { ...config, model: validateModelReference(trimmed) };
}

function parseCsv(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

export function AgentCreateForm({ onCreated, orgId }: { onCreated?: () => void; orgId: string }) {
  const [name, setName] = useState("");
  const [role, setRole] = useState<AgentRole>("engineer");
  const [runtime, setRuntime] = useState<AgentRuntimeType>("process");
  const [title, setTitle] = useState("");
  const [capabilities, setCapabilities] = useState("");
  const [budgetMonthlyCents, setBudgetMonthlyCents] = useState("");
  const [agentRuntimeConfig, setAgentRuntimeConfig] = useState("{}");
  const [runtimeModel, setRuntimeModel] = useState("");
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
  const runtimeModels = useQuery({
    queryKey: ["runtime-model-options", orgId, runtime],
    queryFn: () => listRuntimeModelOptions(orgId, runtime),
    enabled: supportsRuntimeModels(runtime) && Boolean(orgId),
  });
  const modelOptions: RuntimeModel[] = runtimeModels.data ?? [];
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
        agentRuntimeConfig: mergeModelConfig(readJsonObject(agentRuntimeConfig, "Agent runtime config"), runtime, runtimeModel),
        ...(budgetMonthlyCents.trim() ? { budgetMonthlyCents: Number(budgetMonthlyCents) } : {}),
        ...(metadata.trim() && metadata.trim() !== "{}" ? { metadata: readJsonObject(metadata, "Metadata") } : {}),
        ...(desiredSkills.trim() ? { desiredSkills: parseCsv(desiredSkills) } : {}),
      }),
    onSuccess: (agent) => {
      void queryClient.invalidateQueries({ queryKey: ["agents", orgId] });
      onCreated?.();
      navigate(`/orgs/${orgId}/agents/${agent.id}/configuration`);
    },
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    if (!name.trim()) return;
    try {
      setConfigurationError("");
      mergeModelConfig(readJsonObject(agentRuntimeConfig, "Agent runtime config"), runtime, runtimeModel);
      if (metadata.trim() && metadata.trim() !== "{}") readJsonObject(metadata, "Metadata");
      create.mutate();
    } catch (error) {
      setConfigurationError(error instanceof Error ? error.message : "配置格式无效");
    }
  }
  return (
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
        {supportsRuntimeModels(runtime) && (
          <label>
            模型配置
            {modelOptions.length > 0 ? (
              <select value={runtimeModel} onChange={(event) => setRuntimeModel(event.target.value)}>
                <option value="">选择模型</option>
                {modelOptions.map((model) => (
                  <option key={`${model.providerId}:${model.modelId}`} value={runtimeModelReference(model)}>
                    {runtimeModelLabel(model)}
                  </option>
                ))}
              </select>
            ) : (
              <input
                placeholder="provider/model"
                value={runtimeModel}
                onChange={(event) => setRuntimeModel(event.target.value)}
              />
            )}
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
  );
}

export function AgentCreateDialog({ onClose, orgId }: { onClose: () => void; orgId: string }) {
  return (
    <div
      aria-label="创建智能体"
      aria-modal="true"
      className="modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
      role="dialog"
    >
      <section className="panel task-modal task-create-modal agent-create-dialog">
        <div className="task-modal-header">
          <div>
            <p className="eyebrow">Agents</p>
            <h2>创建智能体</h2>
          </div>
          <button className="secondary small-button" onClick={onClose} type="button">关闭</button>
        </div>
        <AgentCreateForm onCreated={onClose} orgId={orgId} />
      </section>
    </div>
  );
}

export function NewAgentPage() {
  const { orgId = "" } = useParams();
  return (
    <AgentsWorkspace contentClassName="org-content-full" orgId={orgId}>
      <header className="page-header">
        <div>
          <Link className="back-link" to={`/orgs/${orgId}/agents`}>返回智能体列表</Link>
          <h1>新建智能体</h1>
        </div>
      </header>
      <AgentCreateForm orgId={orgId} />
    </AgentsWorkspace>
  );
}
