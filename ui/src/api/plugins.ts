import { jsonRequest, request } from "./client";
import type {
  AvailablePluginItem,
  PluginCatalogResponse,
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
};
