import { jsonRequest, request } from "./client";
import type {
  AgentRuntimeType,
  CreateRuntimeModelPayload,
  CreateRuntimeProviderPayload,
  RuntimeModel,
  RuntimeProvider,
  UpdateRuntimeModelPayload,
  UpdateRuntimeProviderPayload,
} from "./types";

function root(orgId: string) {
  return `/api/orgs/${encodeURIComponent(orgId)}/runtime-providers`;
}

function runtimeQuery(runtimeType: AgentRuntimeType) {
  return `runtimeType=${encodeURIComponent(runtimeType)}`;
}

function providerRoot(orgId: string, runtimeType: AgentRuntimeType, providerId: string) {
  return `${root(orgId)}/${encodeURIComponent(providerId)}?${runtimeQuery(runtimeType)}`;
}

function modelRoot(orgId: string, runtimeType: AgentRuntimeType, providerId: string) {
  return `${root(orgId)}/${encodeURIComponent(providerId)}/models?${runtimeQuery(runtimeType)}`;
}

function modelDetailRoot(orgId: string, runtimeType: AgentRuntimeType, providerId: string, modelId: string) {
  return `${root(orgId)}/${encodeURIComponent(providerId)}/models/${encodeURIComponent(modelId)}?${runtimeQuery(runtimeType)}`;
}

export const runtimeProvidersApi = {
  listProviders: (orgId: string, runtimeType: AgentRuntimeType): Promise<RuntimeProvider[]> =>
    request<RuntimeProvider[]>(`${root(orgId)}?${runtimeQuery(runtimeType)}`, { method: "GET" }),
  createProvider: (orgId: string, payload: CreateRuntimeProviderPayload): Promise<RuntimeProvider> =>
    jsonRequest<RuntimeProvider>(root(orgId), "POST", payload),
  updateProvider: (
    orgId: string,
    runtimeType: AgentRuntimeType,
    providerId: string,
    payload: UpdateRuntimeProviderPayload,
  ): Promise<RuntimeProvider> => jsonRequest<RuntimeProvider>(providerRoot(orgId, runtimeType, providerId), "PATCH", payload),
  deleteProvider: (orgId: string, runtimeType: AgentRuntimeType, providerId: string): Promise<RuntimeProvider> =>
    request<RuntimeProvider>(providerRoot(orgId, runtimeType, providerId), { method: "DELETE" }),
  listModels: (orgId: string, runtimeType: AgentRuntimeType, providerId: string): Promise<RuntimeModel[]> =>
    request<RuntimeModel[]>(modelRoot(orgId, runtimeType, providerId), { method: "GET" }),
  createModel: (
    orgId: string,
    runtimeType: AgentRuntimeType,
    providerId: string,
    payload: CreateRuntimeModelPayload,
  ): Promise<RuntimeModel> => jsonRequest<RuntimeModel>(modelRoot(orgId, runtimeType, providerId), "POST", payload),
  updateModel: (
    orgId: string,
    runtimeType: AgentRuntimeType,
    providerId: string,
    modelId: string,
    payload: UpdateRuntimeModelPayload,
  ): Promise<RuntimeModel> => jsonRequest<RuntimeModel>(modelDetailRoot(orgId, runtimeType, providerId, modelId), "PATCH", payload),
  deleteModel: (orgId: string, runtimeType: AgentRuntimeType, providerId: string, modelId: string): Promise<RuntimeModel> =>
    request<RuntimeModel>(modelDetailRoot(orgId, runtimeType, providerId, modelId), { method: "DELETE" }),
};
