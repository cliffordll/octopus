import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { pluginsApi } from "../api/plugins";
import type { AvailablePluginItem, PluginSummary } from "../api/types";
import { Badge } from "../components/Badge";
import { ErrorNotice } from "../components/ErrorNotice";

function statusText(status?: string): string {
  switch (status) {
    case "ready":
      return "已启用";
    case "disabled":
      return "已停用";
    case "installed":
      return "已安装";
    case "error":
      return "错误";
    case "upgrade_pending":
      return "待升级";
    case "uninstalled":
      return "已卸载";
    default:
      return "未安装";
  }
}

function capabilitySummary(plugin: AvailablePluginItem | PluginSummary): string {
  const capabilities = "manifest" in plugin ? plugin.manifest.capabilities : [];
  if (capabilities.length === 0) return "无声明能力";
  return capabilities.slice(0, 4).join(", ") + (capabilities.length > 4 ? ` +${capabilities.length - 4}` : "");
}

function sortPlugins(items: AvailablePluginItem[]): AvailablePluginItem[] {
  return [...items].sort((left, right) => left.displayName.localeCompare(right.displayName));
}

export function PluginsPage({ embedded = false }: { embedded?: boolean } = {}) {
  const queryClient = useQueryClient();
  const [selectedPluginId, setSelectedPluginId] = useState<string | null>(null);
  const available = useQuery({ queryKey: ["plugins", "available"], queryFn: pluginsApi.available });
  const installed = useQuery({ queryKey: ["plugins", "installed"], queryFn: pluginsApi.list });
  const installedByKey = useMemo(() => {
    const map = new Map<string, PluginSummary>();
    for (const plugin of installed.data ?? []) {
      map.set(plugin.pluginKey, plugin);
    }
    return map;
  }, [installed.data]);
  const selectedInstalled = (installed.data ?? []).find((plugin) => plugin.id === selectedPluginId) ?? null;
  const jobs = useQuery({
    enabled: selectedInstalled !== null,
    queryKey: ["plugins", selectedPluginId, "jobs"],
    queryFn: () => pluginsApi.jobs(selectedInstalled!.id),
  });
  const logs = useQuery({
    enabled: selectedInstalled !== null,
    queryKey: ["plugins", selectedPluginId, "logs"],
    queryFn: () => pluginsApi.logs(selectedInstalled!.id),
  });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["plugins"] });
  };
  const install = useMutation({ mutationFn: pluginsApi.install, onSuccess: refresh });
  const enable = useMutation({ mutationFn: pluginsApi.enable, onSuccess: refresh });
  const disable = useMutation({ mutationFn: pluginsApi.disable, onSuccess: refresh });
  const plugins = sortPlugins(available.data?.items ?? []);

  const listPanelClass = embedded ? "plugins-list-panel" : "panel plugins-list-panel";
  const detailPanelClass = embedded ? "plugins-detail-panel" : "panel plugins-detail-panel";
  const content = (
    <>
      {(available.error || installed.error || install.error || enable.error || disable.error) && (
        <ErrorNotice error={available.error ?? installed.error ?? install.error ?? enable.error ?? disable.error} />
      )}
      <div className="plugins-layout">
        <section className={listPanelClass}>
          <div className="plugins-panel-heading">
            <div>
              <h2>可用插件</h2>
              <p className="muted">从 bundled catalog 安装并管理插件生命周期。</p>
            </div>
            <Badge>{plugins.length}</Badge>
          </div>
          {available.isLoading && <p className="muted">载入中...</p>}
          <div className="plugins-list">
            {plugins.map((plugin) => {
              const installedPlugin = installedByKey.get(plugin.id);
              const isSelected = installedPlugin?.id === selectedPluginId;
              return (
                <article className={`plugin-row ${isSelected ? "selected" : ""}`} key={plugin.id}>
                  <button
                    className="plugin-row-main"
                    disabled={!installedPlugin}
                    onClick={() => installedPlugin && setSelectedPluginId(installedPlugin.id)}
                    type="button"
                  >
                    <span>
                      <strong>{plugin.displayName}</strong>
                      <small>{plugin.id}</small>
                    </span>
                    <Badge>{statusText(installedPlugin?.status)}</Badge>
                  </button>
                  <p className="muted">{plugin.manifest.description ?? capabilitySummary(plugin)}</p>
                  <div className="plugin-row-meta">
                    <span>{capabilitySummary(plugin)}</span>
                    <span>{plugin.version}</span>
                  </div>
                  <div className="plugin-row-actions">
                    {!installedPlugin && (
                      <button disabled={install.isPending} onClick={() => install.mutate(plugin)} type="button">
                        安装
                      </button>
                    )}
                    {installedPlugin && installedPlugin.status !== "ready" && installedPlugin.status !== "uninstalled" && (
                      <button disabled={enable.isPending} onClick={() => enable.mutate(installedPlugin.id)} type="button">
                        启用
                      </button>
                    )}
                    {installedPlugin?.status === "ready" && (
                      <button
                        className="secondary"
                        disabled={disable.isPending}
                        onClick={() => disable.mutate(installedPlugin.id)}
                        type="button"
                      >
                        停用
                      </button>
                    )}
                  </div>
                </article>
              );
            })}
          </div>
        </section>
        <section className={detailPanelClass}>
          <div className="plugins-panel-heading">
            <div>
              <h2>运行详情</h2>
              <p className="muted">查看已安装插件的 jobs 和日志。</p>
            </div>
          </div>
          {!selectedInstalled && <p className="muted">选择一个已安装插件查看详情。</p>}
          {selectedInstalled && (
            <div className="plugin-detail">
              <div className="plugin-detail-header">
                <div>
                  <h3>{selectedInstalled.displayName}</h3>
                  <p className="muted">{selectedInstalled.pluginKey}</p>
                </div>
                <Badge>{statusText(selectedInstalled.status)}</Badge>
              </div>
              <section>
                <h3>Jobs</h3>
                {jobs.isLoading && <p className="muted">载入中...</p>}
                {jobs.error && <ErrorNotice error={jobs.error} />}
                <div className="plugin-detail-list">
                  {(jobs.data ?? []).map((job) => (
                    <div className="plugin-detail-row" key={job.id}>
                      <strong>{job.displayName}</strong>
                      <span>{job.schedule ?? "手动触发"}</span>
                    </div>
                  ))}
                </div>
              </section>
              <section>
                <h3>Logs</h3>
                {logs.isLoading && <p className="muted">载入中...</p>}
                {logs.error && <ErrorNotice error={logs.error} />}
                <div className="plugin-detail-list">
                  {(logs.data ?? []).slice(0, 8).map((log) => (
                    <div className="plugin-detail-row" key={log.id}>
                      <strong>{log.message}</strong>
                      <span>{log.level}</span>
                    </div>
                  ))}
                </div>
              </section>
            </div>
          )}
        </section>
      </div>
    </>
  );
  if (embedded) {
    return (
      <section aria-label="插件" className="settings-empty-section plugin-settings-section">
        <div className="plugins-settings-header">
          <div>
            <p className="eyebrow">Plugins</p>
            <h3>插件</h3>
          </div>
          <button className="secondary" onClick={refresh} type="button">
            刷新
          </button>
        </div>
        {content}
      </section>
    );
  }
  return (
    <>
      <header className="page-header">
        <div>
          <p className="eyebrow">Plugins</p>
          <h1>插件</h1>
        </div>
        <button className="secondary" onClick={refresh} type="button">
          刷新
        </button>
      </header>
      {content}
    </>
  );
}
