import type { RuntimeModel } from "../api/types";

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
