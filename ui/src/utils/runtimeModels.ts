import { runtimeProvidersApi } from "../api/runtimeProviders";
import type { AgentRuntimeType, RuntimeModel } from "../api/types";

export const MODEL_PROVIDER_RUNTIMES: AgentRuntimeType[] = [
  "opencode_local",
  "codex_local",
  "claude_local",
  "openclaw_gateway",
];

export function supportsRuntimeModels(runtime: AgentRuntimeType): boolean {
  return MODEL_PROVIDER_RUNTIMES.includes(runtime);
}

export async function listRuntimeModelOptions(orgId: string, runtime: AgentRuntimeType): Promise<RuntimeModel[]> {
  const providers = await runtimeProvidersApi.listProviders(orgId, runtime);
  const enabledProviders = providers.filter((provider) => provider.enabled !== false);
  const groups = await Promise.all(
    enabledProviders.map((provider) => runtimeProvidersApi.listModels(orgId, runtime, provider.providerId)),
  );
  return groups.flat().filter((model) => model.enabled !== false);
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
