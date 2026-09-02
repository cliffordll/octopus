import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { organizationsApi } from "../api/organizations";
import { initializeLocalePreference, LOCALE_CHANGE_EVENT } from "../utils/locale";
import { AgentCreateDialog } from "../pages/NewAgentPage";
import { ProjectCreateDialog } from "../pages/ProjectsPage";
import { OrganizationSettingsPanel, type SettingsSection } from "./OrganizationSettingsPanel";
import { SidebarAccountMenu } from "./SidebarAccountMenu";
import { SidebarNavItem } from "./SidebarNavItem";
import { SidebarIcon } from "./SidebarIcon";

const ORGANIZATION_AREA_SECTIONS = new Set([
  "structure",
  "members",
  "projects",
  "heartbeat-runs",
  "run-intelligence",
  "costs",
  "resources",
  "workspaces",
  "goals",
  "skills",
  "settings",
]);
const MESSAGE_AREA_SECTIONS = new Set(["chats", "messenger", "approvals"]);
const ORGANIZATION_SCOPED_SECTIONS = new Set([
  ...ORGANIZATION_AREA_SECTIONS,
  ...MESSAGE_AREA_SECTIONS,
  "issues",
  "agents",
]);

function currentOrganizationSection(pathname: string) {
  return pathname.match(/^\/orgs\/[^/]+\/([^/]+)/)?.[1];
}

function organizationTarget(pathname: string, orgId: string) {
  const section = currentOrganizationSection(pathname);
  return `/orgs/${orgId}/${section && ORGANIZATION_SCOPED_SECTIONS.has(section) ? section : "issues"}`;
}

export function AppShell() {
  const location = useLocation();
  const [organizationMenuOpen, setOrganizationMenuOpen] = useState(false);
  const [quickCreateOpen, setQuickCreateOpen] = useState(false);
  const [agentCreateOpen, setAgentCreateOpen] = useState(false);
  const [projectCreateOpen, setProjectCreateOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsSection, setSettingsSection] = useState<SettingsSection>("providers");
  const [locale, setLocale] = useState(() => initializeLocalePreference());
  const productMenuRef = useRef<HTMLDivElement>(null);
  const quickCreateRef = useRef<HTMLDivElement>(null);
  const isOrganizationWorkspace = location.pathname.startsWith("/orgs/");
  const activeSection = currentOrganizationSection(location.pathname) ?? "";
  const isMessagesArea = MESSAGE_AREA_SECTIONS.has(activeSection);
  const isOrganizationArea = ORGANIZATION_AREA_SECTIONS.has(activeSection);
  const activeOrganizationId = location.pathname.match(/^\/orgs\/([^/]+)/)?.[1];
  const organizations = useQuery({
    queryKey: ["organizations"],
    queryFn: organizationsApi.list,
  });
  const organizationList = Array.isArray(organizations.data) ? organizations.data : [];
  const selectedOrganization =
    organizationList.find((organization) => organization.id === activeOrganizationId) ?? organizationList[0];
  const selectedOrganizationId = activeOrganizationId ?? selectedOrganization?.id;
  const organizationMenuHint = selectedOrganization?.name
    ? `${selectedOrganization.name} · 切换组织`
    : "选择或创建组织";

  useEffect(() => {
    function rerenderOnLocaleChange() {
      setLocale(initializeLocalePreference());
    }
    window.addEventListener(LOCALE_CHANGE_EVENT, rerenderOnLocaleChange);
    return () => {
      window.removeEventListener(LOCALE_CHANGE_EVENT, rerenderOnLocaleChange);
    };
  }, []);

  useEffect(() => {
    function closeMenusOnOutsideInteraction(event: MouseEvent | FocusEvent) {
      const target = event.target;
      if (!(target instanceof Node)) {
        return;
      }
      if (productMenuRef.current && !productMenuRef.current.contains(target)) {
        setOrganizationMenuOpen(false);
      }
      if (quickCreateRef.current && !quickCreateRef.current.contains(target)) {
        setQuickCreateOpen(false);
      }
    }

    function closeMenusOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOrganizationMenuOpen(false);
        setQuickCreateOpen(false);
      }
    }

    document.addEventListener("mousedown", closeMenusOnOutsideInteraction);
    document.addEventListener("focusin", closeMenusOnOutsideInteraction);
    document.addEventListener("keydown", closeMenusOnEscape);
    return () => {
      document.removeEventListener("mousedown", closeMenusOnOutsideInteraction);
      document.removeEventListener("focusin", closeMenusOnOutsideInteraction);
      document.removeEventListener("keydown", closeMenusOnEscape);
    };
  }, []);

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="product-menu" ref={productMenuRef}>
          <button
            aria-expanded={organizationMenuOpen}
            aria-label="组织菜单"
            aria-description={organizationMenuHint}
            title={organizationMenuHint}
            className="product-mark product-menu-trigger"
            onClick={() => {
              setOrganizationMenuOpen((open) => !open);
              setQuickCreateOpen(false);
            }}
            type="button"
          >
            {(selectedOrganization?.name ?? activeOrganizationId ?? "O").slice(0, 1).toUpperCase()}
            <svg aria-hidden="true" focusable="false" className="product-menu-chevron" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="m3 4.5 3 3 3-3" />
            </svg>
          </button>
          {organizationMenuOpen && (
            <nav aria-label="组织切换菜单" className="organization-menu product-organization-menu">
              <p>切换组织</p>
              {organizationList.map((organization) => (
                <Link
                  className={organization.id === selectedOrganizationId ? "selected" : undefined}
                  key={organization.id}
                  onClick={() => setOrganizationMenuOpen(false)}
                  to={organizationTarget(location.pathname, organization.id)}
                >
                  <span className="organization-avatar">{organization.name.slice(0, 1).toUpperCase()}</span>
                  {organization.name}
                </Link>
              ))}
              {selectedOrganizationId && (
                <NavLink onClick={() => setOrganizationMenuOpen(false)} to={`/orgs/${selectedOrganizationId}/settings`}>
                  组织设置
                </NavLink>
              )}
              <NavLink onClick={() => setOrganizationMenuOpen(false)} to="/organizations">
                创建组织
              </NavLink>
            </nav>
          )}
        </div>
        <div className="product">Octopus</div>
        <nav className="global-nav" aria-label="主导航">
          {selectedOrganizationId ? (
            <>
              <div className="quick-create" ref={quickCreateRef}>
                <button
                  aria-expanded={quickCreateOpen}
                  aria-label="快速创建"
                  className="quick-create-trigger sidebar-icon-button"
                  title="创建"
                  onClick={() => {
                    setQuickCreateOpen((open) => !open);
                    setOrganizationMenuOpen(false);
                  }}
                  type="button"
                >
                  <SidebarIcon name="create" />
                </button>
                {quickCreateOpen && (
                  <nav aria-label="快速创建菜单" className="quick-create-menu">
                    <Link onClick={() => setQuickCreateOpen(false)} to={`/orgs/${selectedOrganizationId}/chats`}>
                      <SidebarIcon name="messages" />
                      创建新聊天
                    </Link>
                    <Link onClick={() => setQuickCreateOpen(false)} to={`/orgs/${selectedOrganizationId}/issues?create=1`}>
                      <SidebarIcon name="issues" />
                      创建新任务
                    </Link>
                    <button
                      onClick={() => {
                        setQuickCreateOpen(false);
                        setAgentCreateOpen(true);
                      }}
                      type="button"
                    >
                      <SidebarIcon name="agents" />
                      创建智能体
                    </button>
                    <button
                      onClick={() => {
                        setQuickCreateOpen(false);
                        setProjectCreateOpen(true);
                      }}
                      type="button"
                    >
                      <SidebarIcon name="projects" />
                      创建新项目
                    </button>
                  </nav>
                )}
              </div>
            </>
          ) : (
            <>
              <button aria-label="快速创建" className="quick-create-trigger sidebar-icon-button" disabled title="创建" type="button">
                <SidebarIcon name="create" />
              </button>
            </>
          )}
          <SidebarNavItem item="messages" active={isMessagesArea} to={selectedOrganizationId ? `/orgs/${selectedOrganizationId}/chats` : undefined} />
          <SidebarNavItem item="agents" to={selectedOrganizationId ? `/orgs/${selectedOrganizationId}/agents` : undefined} />
          <SidebarNavItem item="issues" to={selectedOrganizationId ? `/orgs/${selectedOrganizationId}/issues` : undefined} />
          <SidebarNavItem item="organization" active={isOrganizationArea} to={selectedOrganizationId ? `/orgs/${selectedOrganizationId}/structure` : undefined} />
        </nav>
        <div className="sidebar-footer">
          <button
            aria-label="设置"
            className="sidebar-settings-trigger sidebar-icon-button"
            title="设置"
            aria-haspopup="dialog"
            aria-expanded={settingsOpen}
            onClick={() => {
              setOrganizationMenuOpen(false);
              setQuickCreateOpen(false);
              setSettingsSection("providers");
              setSettingsOpen(true);
            }}
            type="button"
          >
            <SidebarIcon name="settings" />
          </button>
          <SidebarAccountMenu
            onOpenAccount={() => {
              setSettingsSection("account");
              setSettingsOpen(true);
            }}
          />
        </div>
      </aside>
      <main className={`workspace ${isOrganizationWorkspace ? "workspace-org" : "workspace-global"}`} key={locale}>
        <Outlet />
      </main>
      {agentCreateOpen && selectedOrganizationId && (
        <AgentCreateDialog onClose={() => setAgentCreateOpen(false)} orgId={selectedOrganizationId} />
      )}
      {projectCreateOpen && selectedOrganizationId && (
        <ProjectCreateDialog onClose={() => setProjectCreateOpen(false)} orgId={selectedOrganizationId} />
      )}
      {settingsOpen && (
        <div className="modal-backdrop" role="presentation">
          <div aria-label="设置" aria-modal="true" className="panel settings-dialog" role="dialog">
            <div className="modal-header">
              <div>
                <p className="eyebrow">Settings</p>
                <h2>设置</h2>
              </div>
              <button aria-label="关闭设置" className="ghost" onClick={() => setSettingsOpen(false)} type="button">
                关闭
              </button>
            </div>
            <OrganizationSettingsPanel initialSection={settingsSection} orgId={selectedOrganizationId} />
          </div>
        </div>
      )}
    </div>
  );
}
