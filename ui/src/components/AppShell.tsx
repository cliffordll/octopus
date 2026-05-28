import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { organizationsApi } from "../api/organizations";

function organizationTarget(pathname: string, orgId: string) {
  const section = pathname.match(
    /^\/orgs\/[^/]+\/(chats|issues|agents|projects|approvals|structure|heartbeat-runs|settings)/,
  )?.[1];
  return `/orgs/${orgId}/${section ?? "issues"}`;
}

export function AppShell() {
  const location = useLocation();
  const [organizationMenuOpen, setOrganizationMenuOpen] = useState(false);
  const isOrganizationWorkspace = location.pathname.startsWith("/orgs/");
  const isOrganizationArea = /^\/orgs\/[^/]+\/(structure|projects|heartbeat-runs|settings)/.test(location.pathname);
  const activeOrganizationId = location.pathname.match(/^\/orgs\/([^/]+)/)?.[1];
  const organizations = useQuery({
    queryKey: ["organizations"],
    queryFn: organizationsApi.list,
  });
  const organizationList = Array.isArray(organizations.data) ? organizations.data : [];
  const selectedOrganization =
    organizationList.find((organization) => organization.id === activeOrganizationId) ?? organizationList[0];
  const selectedOrganizationId = activeOrganizationId ?? selectedOrganization?.id;

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="product-mark">O</div>
        <div className="product">Octopus</div>
        <div className="product-subtitle">Control plane</div>
        <nav className="global-nav" aria-label="主导航">
          {selectedOrganizationId ? (
            <>
              <NavLink to={`/orgs/${selectedOrganizationId}/chats`}>
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
        <div className="organization-switcher">
          <button
            aria-expanded={organizationMenuOpen}
            aria-label="切换组织"
            className="organization-trigger"
            onClick={() => setOrganizationMenuOpen((open) => !open)}
            type="button"
          >
            <span className="organization-avatar">
              {(selectedOrganization?.name ?? activeOrganizationId ?? "-").slice(0, 1).toUpperCase()}
            </span>
            <span className="organization-trigger-label">
              <small>Organization</small>
              {selectedOrganization?.name ?? activeOrganizationId ?? "选择组织"}
            </span>
          </button>
          {organizationMenuOpen && (
            <nav aria-label="组织切换菜单" className="organization-menu">
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
                管理组织
              </NavLink>
            </nav>
          )}
        </div>
      </aside>
      <main className={`workspace ${isOrganizationWorkspace ? "workspace-org" : "workspace-global"}`}>
        <Outlet />
      </main>
    </div>
  );
}
