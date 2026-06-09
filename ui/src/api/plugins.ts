import { jsonRequest, request } from "./client";
import type {
  AvailablePluginItem,
  PluginCatalogResponse,
  PluginConfig,
  PluginConfigTestResult,
  PluginDashboard,
  PluginHealth,
  PluginJob,
  PluginLog,
  PluginSummary,
} from "./types";

export const pluginsApi = {
  list: (): Promise<PluginSummary[]> => request<PluginSummary[]>("/api/plugins", { method: "GET" }),
  available: (): Promise<PluginCatalogResponse> =>
    request<PluginCatalogResponse>("/api/plugins/available", { method: "GET" }),
  install: (plugin: AvailablePluginItem): Promise<PluginSummary> =>
    jsonRequest<PluginSummary>("/api/plugins/install", "POST", {
      manifest: plugin.manifest,
      sourceType: "bundled",
      sourceLocator: plugin.sourcePath,
    }),
  enable: (pluginId: string): Promise<PluginSummary> =>
    jsonRequest<PluginSummary>(`/api/plugins/${encodeURIComponent(pluginId)}/enable`, "POST", {}),
  disable: (pluginId: string): Promise<PluginSummary> =>
    jsonRequest<PluginSummary>(`/api/plugins/${encodeURIComponent(pluginId)}/disable`, "POST", {}),
  jobs: (pluginId: string): Promise<PluginJob[]> =>
    request<PluginJob[]>(`/api/plugins/${encodeURIComponent(pluginId)}/jobs`, { method: "GET" }),
  logs: (pluginId: string): Promise<PluginLog[]> =>
    request<PluginLog[]>(`/api/plugins/${encodeURIComponent(pluginId)}/logs`, { method: "GET" }),
  config: (pluginId: string): Promise<PluginConfig> =>
    request<PluginConfig>(`/api/plugins/${encodeURIComponent(pluginId)}/config`, { method: "GET" }),
  saveConfig: (pluginId: string, configJson: Record<string, unknown>): Promise<PluginConfig> =>
    jsonRequest<PluginConfig>(`/api/plugins/${encodeURIComponent(pluginId)}/config`, "POST", { configJson }),
  testConfig: (pluginId: string, configJson: Record<string, unknown>): Promise<PluginConfigTestResult> =>
    jsonRequest<PluginConfigTestResult>(`/api/plugins/${encodeURIComponent(pluginId)}/config/test`, "POST", {
      configJson,
    }),
  health: (pluginId: string): Promise<PluginHealth> =>
    request<PluginHealth>(`/api/plugins/${encodeURIComponent(pluginId)}/health`, { method: "GET" }),
  dashboard: (pluginId: string): Promise<PluginDashboard> =>
    request<PluginDashboard>(`/api/plugins/${encodeURIComponent(pluginId)}/dashboard`, { method: "GET" }),
};
