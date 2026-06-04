import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { organizationsApi } from "../api/organizations";
import { initializeLocalePreference, LOCALE_CHANGE_EVENT } from "../utils/locale";
import { AgentCreateDialog } from "../pages/NewAgentPage";
import { ProjectCreateDialog } from "../pages/ProjectsPage";
import { OrganizationSettingsPanel } from "./OrganizationSettingsPanel";

function organizationTarget(pathname: string, orgId: string) {
  const section = pathname.match(
    /^\/orgs\/[^/]+\/(chats|messenger|issues|agents|projects|approvals|structure|heartbeat-runs|run-intelligence|settings)/,
  )?.[1];
  return `/orgs/${orgId}/${section ?? "issues"}`;
}

export function AppShell() {
  const location = useLocation();
  const [organizationMenuOpen, setOrganizationMenuOpen] = useState(false);
  const [quickCreateOpen, setQuickCreateOpen] = useState(false);
  const [agentCreateOpen, setAgentCreateOpen] = useState(false);
  const [projectCreateOpen, setProjectCreateOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [locale, setLocale] = useState(() => initializeLocalePreference());
  const productMenuRef = useRef<HTMLDivElement>(null);
  const quickCreateRef = useRef<HTMLDivElement>(null);
  const isOrganizationWorkspace = location.pathname.startsWith("/orgs/");
  const isMessagesArea = /^\/orgs\/[^/]+\/(chats|messenger|approvals)/.test(location.pathname);
  const isOrganizationArea = /^\/orgs\/[^/]+\/(structure|projects|heartbeat-runs|run-intelligence|resources|workspaces|goals|skills|settings)/.test(location.pathname);
  const activeOrganizationId = location.pathname.match(/^\/orgs\/([^/]+)/)?.[1];
  const organizations = useQuery({
    queryKey: ["organizations"],
    queryFn: organizationsApi.list,
  });
  const organizationList = Array.isArray(organizations.data) ? organizations.data : [];
  const selectedOrganization =
    organizationList.find((organization) => organization.id === activeOrganizationId) ?? organizationList[0];
  const selectedOrganizationId = activeOrganizationId ?? selectedOrganization?.id;

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
            className="product-mark product-menu-trigger"
            onClick={() => {
              setOrganizationMenuOpen((open) => !open);
              setQuickCreateOpen(false);
            }}
            type="button"
          >
            {(selectedOrganization?.name ?? activeOrganizationId ?? "O").slice(0, 1).toUpperCase()}
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
        <div className="product-subtitle">Control plane</div>
        <nav className="global-nav" aria-label="主导航">
          {selectedOrganizationId ? (
            <>
              <div className="quick-create" ref={quickCreateRef}>
                <button
                  aria-expanded={quickCreateOpen}
                  aria-label="快速创建"
                  className="quick-create-trigger"
                  onClick={() => {
                    setQuickCreateOpen((open) => !open);
                    setOrganizationMenuOpen(false);
                  }}
                  type="button"
                >
                  <span aria-hidden="true" className="nav-icon">+</span>
                  <span>创建</span>
                </button>
                {quickCreateOpen && (
                  <nav aria-label="快速创建菜单" className="quick-create-menu">
                    <Link onClick={() => setQuickCreateOpen(false)} to={`/orgs/${selectedOrganizationId}/chats`}>
                      <span aria-hidden="true" className="context-entry-icon">M</span>
                      创建新聊天
                    </Link>
                    <Link onClick={() => setQuickCreateOpen(false)} to={`/orgs/${selectedOrganizationId}/issues?create=1`}>
                      <span aria-hidden="true" className="context-entry-icon">T</span>
                      创建新任务
                    </Link>
                    <button
                      onClick={() => {
                        setQuickCreateOpen(false);
                        setAgentCreateOpen(true);
                      }}
                      type="button"
                    >
                      <span aria-hidden="true" className="context-entry-icon">A</span>
                      创建智能体
                    </button>
                    <button
                      onClick={() => {
                        setQuickCreateOpen(false);
                        setProjectCreateOpen(true);
                      }}
                      type="button"
                    >
                      <span aria-hidden="true" className="context-entry-icon">P</span>
                      创建新项目
                    </button>
                  </nav>
                )}
              </div>
              <NavLink className={isMessagesArea ? "active" : undefined} to={`/orgs/${selectedOrganizationId}/chats`}>
                <span aria-hidden="true" className="nav-icon">M</span>
                <span>消息</span>
              </NavLink>
              <NavLink to={`/orgs/${selectedOrganizationId}/agents`}>
                <span aria-hidden="true" className="nav-icon">A</span>
                <span>智能体</span>
              </NavLink>
              <NavLink to={`/orgs/${selectedOrganizationId}/issues`}>
                <span aria-hidden="true" className="nav-icon">T</span>
                <span>任务</span>
              </NavLink>
            </>
          ) : (
            <>
              <span className="nav-disabled"><span aria-hidden="true" className="nav-icon">+</span>创建</span>
              <span className="nav-disabled"><span aria-hidden="true" className="nav-icon">M</span>消息</span>
              <span className="nav-disabled"><span aria-hidden="true" className="nav-icon">A</span>智能体</span>
              <span className="nav-disabled"><span aria-hidden="true" className="nav-icon">T</span>任务</span>
            </>
          )}
          {selectedOrganizationId ? (
            <NavLink className={isOrganizationArea ? "active" : undefined} to={`/orgs/${selectedOrganizationId}/structure`}>
              <span aria-hidden="true" className="nav-icon">O</span>
              <span>组织</span>
            </NavLink>
          ) : (
            <span className="nav-disabled"><span aria-hidden="true" className="nav-icon">O</span>组织</span>
          )}
        </nav>
        <div className="sidebar-settings">
          <button
            aria-label="设置"
            onClick={() => {
              setOrganizationMenuOpen(false);
              setQuickCreateOpen(false);
              setSettingsOpen(true);
            }}
            type="button"
          >
            <span aria-hidden="true" className="nav-icon">S</span>
            <span>设置</span>
          </button>
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
            {selectedOrganizationId ? (
              <OrganizationSettingsPanel orgId={selectedOrganizationId} />
            ) : (
              <p className="muted">请选择组织后再配置模型供应商。</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
