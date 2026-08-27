import { agentsApi } from "../api/agents";
import { runtimeProvidersApi } from "../api/runtimeProviders";
import type { AgentRuntimeType, RuntimeModel } from "../api/types";

export const MODEL_PROVIDER_RUNTIMES: AgentRuntimeType[] = [
  "opencode_local",
  "codex_local",
  "claude_local",
  "openclaw_local",
];

export function supportsRuntimeModels(runtime: AgentRuntimeType): boolean {
  return MODEL_PROVIDER_RUNTIMES.includes(runtime);
}

export async function listRuntimeModelOptions(orgId: string, runtime: AgentRuntimeType): Promise<RuntimeModel[]> {
  if (runtime === "codex_local") {
    const models = await agentsApi.adapterModels(orgId, runtime);
    return (Array.isArray(models) ? models : []).map((model) => ({
      providerId: "openai",
      modelId: model.id,
      displayName: model.label,
      runtimeType: runtime,
      enabled: true,
    }));
  }
  const providers = await runtimeProvidersApi.listProviders(orgId, runtime);
  const enabledProviders = providers.filter((provider) => provider.enabled !== false);
  const groups = await Promise.all(
    enabledProviders.map((provider) => runtimeProvidersApi.listModels(orgId, runtime, provider.providerId)),
  );
  return groups.flat().filter((model) => model.enabled !== false);
}

const RUNTIME_SPECIFIC_CONFIG_KEYS = [
  "args",
  "command",
  "dangerouslyBypassApprovalsAndSandbox",
  "env",
  "extraArgs",
  "model",
  "modelReasoningEffort",
  "probeArgs",
  "reasoningEffort",
  "search",
  "sessionId",
  "sessionIdBefore",
] as const;

export function runtimeConfigAfterSwitch(
  config: Record<string, unknown>,
  previousRuntime: AgentRuntimeType,
  nextRuntime: AgentRuntimeType,
): Record<string, unknown> {
  if (previousRuntime === nextRuntime) return config;
  const next = { ...config };
  for (const key of RUNTIME_SPECIFIC_CONFIG_KEYS) delete next[key];
  return next;
}

export function applyRuntimeModelConfig(
  config: Record<string, unknown>,
  runtime: AgentRuntimeType,
  model: string,
): Record<string, unknown> {
  if (!supportsRuntimeModels(runtime)) return config;
  const normalized = runtime === "codex_local" ? withoutOpenCodeArguments(config) : config;
  const trimmed = model.trim();
  if (runtime === "codex_local" && !trimmed) {
    const next = { ...normalized };
    delete next.model;
    return next;
  }
  return { ...normalized, model: validateModelReference(trimmed) };
}

function withoutOpenCodeArguments(config: Record<string, unknown>): Record<string, unknown> {
  const extraArgs = Array.isArray(config.extraArgs)
    ? config.extraArgs.filter((arg) => arg !== "--dangerously-skip-permissions")
    : [];
  const next = { ...config };
  if (extraArgs.length > 0) next.extraArgs = extraArgs;
  else delete next.extraArgs;
  return next;
}

export function validateModelReference(model: string): string {
  const trimmed = model.trim();
  const [provider, modelName] = trimmed.split("/", 2);
  if (!trimmed || !provider?.trim() || !modelName?.trim()) {
    throw new Error("模型必须使用 provider/model 格式，例如 openai/gpt-5。");
  }
  return trimmed;
}

export function runtimeModelReference(model: RuntimeModel): string {
  const providerId = model.providerId.trim();
  const modelId = model.modelId.trim();
  if (!providerId || !modelId) return modelId || providerId;
  if (modelId.includes("/")) return modelId;
  return `${providerId}/${modelId}`;
}

export function runtimeModelLabel(model: RuntimeModel): string {
  const reference = runtimeModelReference(model);
  return model.displayName ? `${model.displayName} (${reference})` : reference;
}
