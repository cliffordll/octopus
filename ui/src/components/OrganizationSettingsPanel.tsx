import { useState } from "react";
import { RuntimeProviderSettings } from "./RuntimeProviderSettings";

type SettingsSection = "general" | "providers" | "about";

const SETTINGS_SECTIONS: Array<{ description: string; eyebrow: string; id: SettingsSection; label: string }> = [
  { id: "providers", eyebrow: "Runtime Providers", label: "供应商", description: "运行时 provider 和 model。" },
  { id: "general", eyebrow: "General", label: "通用", description: "组织级基础设置。" },
  { id: "about", eyebrow: "About", label: "关于", description: "组织和版本信息。" },
];

export function OrganizationSettingsPanel({ orgId }: { orgId: string }) {
  const [activeSection, setActiveSection] = useState<SettingsSection>("providers");
  const current = SETTINGS_SECTIONS.find((section) => section.id === activeSection) ?? SETTINGS_SECTIONS[0];

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
