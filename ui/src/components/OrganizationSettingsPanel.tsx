import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { healthApi } from "../api/health";
import type { ServerHealth, StorageHealthConfig } from "../api/types";
import { getLocalePreference, setLocalePreference, type AppLocale } from "../utils/locale";
import { PluginsPage } from "../pages/PluginsPage";
import { ErrorNotice } from "./ErrorNotice";
import { RuntimeProviderSettings } from "./RuntimeProviderSettings";
import { InstanceHeartbeatsPanel } from "../pages/InstanceHeartbeatsPage";

type SettingsSection = "general" | "providers" | "heartbeats" | "storage" | "plugins" | "about";

const SETTINGS_SECTIONS: Array<{ description: string; eyebrow: string; id: SettingsSection; label: string }> = [
  { id: "providers", eyebrow: "Runtime Providers", label: "供应商", description: "全局运行时 provider 和 model。" },
  { id: "heartbeats", eyebrow: "Timer Heartbeats", label: "心跳", description: "智能体定时心跳。" },
  { id: "storage", eyebrow: "Storage", label: "存储", description: "附件和产物存储配置。" },
  { id: "plugins", eyebrow: "Plugins", label: "插件", description: "安装、启用和检查插件。" },
  { id: "general", eyebrow: "General", label: "通用", description: "实例级界面偏好。" },
  { id: "about", eyebrow: "About", label: "关于", description: "组织和版本信息。" },
];

function storageConfigFromHealth(health?: ServerHealth): StorageHealthConfig | null {
  if (!health) return null;
  if (health.storage) return health.storage;
  if (health.storageProvider || health.storageBucket || health.storageEndpoint || health.storagePathStyle !== undefined) {
    return {
      bucket: health.storageBucket,
      endpoint: health.storageEndpoint,
      pathStyle: health.storagePathStyle,
      provider: health.storageProvider,
    };
  }
  return null;
}

function boolText(value: boolean | null | undefined): string {
  if (value === true) return "是";
  if (value === false) return "否";
  return "未公开";
}

function StorageSettingsSection({ current }: { current: (typeof SETTINGS_SECTIONS)[number] }) {
  const health = useQuery({ queryKey: ["server-health"], queryFn: () => healthApi.get() });
  const storage = storageConfigFromHealth(health.data);
  const pathStyle = storage?.pathStyle ?? storage?.forcePathStyle;
  return (
    <section className="settings-empty-section settings-storage-section" aria-label={current.label}>
      <div className="settings-section-heading-copy">
        <p className="eyebrow">{current.eyebrow}</p>
        <div className="runtime-provider-title-line">
          <h3>{current.label}</h3>
          <p className="muted">配置由 server 环境变量控制，UI 只展示只读状态，不显示 access key / secret。</p>
        </div>
      </div>
      {health.error && <ErrorNotice error={health.error} />}
      <div className="storage-settings-card">
        <dl className="detail-grid compact">
          <div><dt>server 状态</dt><dd>{health.data?.status ?? "加载中"}</dd></div>
          <div><dt>provider</dt><dd>{storage?.provider ?? "未公开"}</dd></div>
          <div><dt>bucket</dt><dd>{storage?.bucket ?? "未公开"}</dd></div>
          <div><dt>endpoint</dt><dd>{storage?.endpoint ?? "未公开"}</dd></div>
          <div><dt>path-style</dt><dd>{boolText(pathStyle)}</dd></div>
        </dl>
        {!storage && health.isSuccess && (
          <p className="muted">当前 server health API 尚未公开 storage 配置字段。</p>
        )}
      </div>
    </section>
  );
}

export function OrganizationSettingsPanel({ orgId }: { orgId?: string }) {
  const [activeSection, setActiveSection] = useState<SettingsSection>("providers");
  const [locale, setLocale] = useState<AppLocale>(() => getLocalePreference());
  const current = SETTINGS_SECTIONS.find((section) => section.id === activeSection) ?? SETTINGS_SECTIONS[0];

  function updateLocale(nextLocale: AppLocale) {
    setLocale(nextLocale);
    setLocalePreference(nextLocale);
  }

  return (
    <section className="organization-settings-panel">
      <aside className="settings-section-nav" aria-label="设置分类">
        {SETTINGS_SECTIONS.map((section) => (
          <button
            className={activeSection === section.id ? "active" : ""}
            key={section.id}
            onClick={() => setActiveSection(section.id)}
            type="button"
          >
            <strong>{section.label}</strong>
            <span>{section.description}</span>
          </button>
        ))}
      </aside>
      <div className="settings-section-content">
        {activeSection === "providers" ? (
          <RuntimeProviderSettings orgId={orgId} />
        ) : activeSection === "heartbeats" ? (
          <InstanceHeartbeatsPanel />
        ) : activeSection === "storage" ? (
          <StorageSettingsSection current={current} />
        ) : activeSection === "plugins" ? (
          <PluginsPage embedded />
        ) : activeSection === "general" ? (
          <section className="settings-empty-section settings-general-section" aria-label={current.label}>
            <div className="settings-section-heading-copy">
              <p className="eyebrow">{current.eyebrow}</p>
              <div className="runtime-provider-title-line">
                <h3>{current.label}</h3>
                <p className="muted">{current.description}</p>
              </div>
            </div>
            <div className="settings-preference-list">
              <div className="settings-preference-row">
                <span>
                  <strong>界面语言</strong>
                  <small>Language</small>
                </span>
                <div aria-label="界面语言" className="settings-locale-tabs" role="group">
                  <button
                    className={locale === "zh-CN" ? "active" : ""}
                    onClick={() => updateLocale("zh-CN")}
                    type="button"
                  >
                    简体中文
                  </button>
                  <button
                    className={locale === "en-US" ? "active" : ""}
                    onClick={() => updateLocale("en-US")}
                    type="button"
                  >
                    English
                  </button>
                </div>
              </div>
            </div>
          </section>
        ) : (
          <section className="settings-empty-section" aria-label={current.label}>
            <div className="settings-section-heading-copy">
              <p className="eyebrow">{current.eyebrow}</p>
              <div className="runtime-provider-title-line">
                <h3>{current.label}</h3>
                <p className="muted">{current.description}</p>
              </div>
            </div>
          </section>
        )}
      </div>
    </section>
  );
}
