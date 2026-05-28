import { useQuery } from "@tanstack/react-query";
import { useEffect, useState, type PropsWithChildren, type ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { agentsApi } from "../api/agents";
import { chatsApi } from "../api/chats";
import { projectsApi } from "../api/projects";
import { readRecentIssues, RECENT_ISSUES_EVENT } from "../utils/recentIssues";
import { Badge } from "./Badge";
import { ErrorNotice } from "./ErrorNotice";

function ContextWorkspace({
  label,
  title,
  navigationLabel,
  sidebar,
  children,
}: PropsWithChildren<{
  label: string;
  title: string;
  navigationLabel: string;
  sidebar: ReactNode;
}>) {
  return (
    <div className="org-workspace context-workspace">
      <aside className="org-sidebar context-sidebar">
        <p className="org-sidebar-label">{label}</p>
        <h2>{title}</h2>
        <nav aria-label={navigationLabel} className="context-nav">
          {sidebar}
        </nav>
      </aside>
      <div className="org-content">{children}</div>
    </div>
  );
}

export function ChatsWorkspace({ orgId, children }: PropsWithChildren<{ orgId: string }>) {
  const chats = useQuery({ queryKey: ["chats", orgId], queryFn: () => chatsApi.list(orgId) });
  const agents = useQuery({ queryKey: ["agents", orgId], queryFn: () => agentsApi.list(orgId) });
  const agentList = Array.isArray(agents.data) ? agents.data : [];
  const agentNameById = new Map(agentList.map((agent) => [agent.id, agent.name]));
  const conversations = Array.isArray(chats.data) ? chats.data : [];
  return (
    <ContextWorkspace
      label="Messages"
      navigationLabel="消息导航"
      title="会话"
      sidebar={
        <>
          <section className="context-nav-section">
            <h3>消息</h3>
            <NavLink className="context-action-entry new-chat-entry" end to={`/orgs/${orgId}/chats`}>+ 新建对话</NavLink>
          </section>
          <section className="context-nav-section">
            <h3>对话</h3>
            {chats.error && <ErrorNotice error={chats.error} />}
            {conversations.map((chat) => (
              <NavLink key={chat.id} to={`/orgs/${orgId}/chats/${chat.id}`}>
                <span className="context-item-copy">
                  <strong>{chat.title}</strong>
                  <small>
                    {chat.preferredAgentId ? agentNameById.get(chat.preferredAgentId) ?? "未知智能体" : "未选择智能体"}
                  </small>
                </span>
                <Badge>{chat.status}</Badge>
              </NavLink>
            ))}
            {chats.isSuccess && conversations.length === 0 && <p className="context-empty">暂无对话</p>}
          </section>
        </>
      }
    >
      {children}
    </ContextWorkspace>
  );
}

export function IssuesWorkspace({ orgId, children }: PropsWithChildren<{ orgId: string }>) {
  const location = useLocation();
  const projects = useQuery({ queryKey: ["projects", orgId], queryFn: () => projectsApi.list(orgId) });
  const projectList = Array.isArray(projects.data) ? projects.data : [];
  const [recentIssues, setRecentIssues] = useState(() => readRecentIssues(orgId));
  const [recentExpanded, setRecentExpanded] = useState(false);
  const currentSearch = new URLSearchParams(location.search);
  const currentProjectId = currentSearch.get("projectId") ?? "";
  const currentStatus = currentSearch.get("status") ?? "";
  const currentView = currentSearch.get("view") ?? "";
  const issuesRootPath = `/orgs/${orgId}/issues`;

  useEffect(() => {
    setRecentIssues(readRecentIssues(orgId));
    setRecentExpanded(false);
  }, [orgId]);

  useEffect(() => {
    function refreshRecentIssues(event: Event) {
      if (event instanceof CustomEvent && event.detail?.orgId !== orgId) return;
      setRecentIssues(readRecentIssues(orgId));
    }
    window.addEventListener(RECENT_ISSUES_EVENT, refreshRecentIssues);
    return () => window.removeEventListener(RECENT_ISSUES_EVENT, refreshRecentIssues);
  }, [orgId]);

  const visibleRecentIssues = recentExpanded ? recentIssues : recentIssues.slice(0, 5);

  return (
    <ContextWorkspace
      label="Tasks"
      navigationLabel="任务导航"
      title="任务"
      sidebar={
        <>
          <section className="context-nav-section">
            <h3>任务</h3>
            <NavLink
              className={() => location.pathname === issuesRootPath && !location.search ? "active" : ""}
              end
              to={issuesRootPath}
            >
              全部任务
            </NavLink>
            <NavLink
              className={() => location.pathname === issuesRootPath && currentStatus === "backlog" ? "active" : ""}
              to={`${issuesRootPath}?status=backlog`}
            >
              草稿任务
            </NavLink>
            <NavLink
              className={() => location.pathname === issuesRootPath && currentView === "following" ? "active" : ""}
              to={`${issuesRootPath}?view=following`}
            >
              关注中
            </NavLink>
          </section>
          <section className="context-nav-section">
            <h3>最近查看</h3>
            {visibleRecentIssues.map((issue) => (
              <NavLink key={issue.id} to={`/orgs/${orgId}/issues/${issue.id}`}>
                <span className="context-item-copy">
                  <strong>{issue.title}</strong>
                  <small>{issue.identifier ?? "未编号"}</small>
                </span>
                <Badge>{issue.status}</Badge>
              </NavLink>
            ))}
            {recentIssues.length > 5 && (
              <button className="context-nav-toggle" onClick={() => setRecentExpanded((value) => !value)} type="button">
                {recentExpanded ? "收起" : `展开全部 ${recentIssues.length}`}
              </button>
            )}
          </section>
          <section className="context-nav-section">
            <h3>项目</h3>
            {projects.error && <ErrorNotice error={projects.error} />}
            {projectList.map((project) => (
              <NavLink
                className={() => currentProjectId === project.id ? "context-project-name active" : "context-project-name"}
                key={project.id}
                to={`${issuesRootPath}?projectId=${project.id}`}
              >
                {project.name}
              </NavLink>
            ))}
          </section>
        </>
      }
    >
      {children}
    </ContextWorkspace>
  );
}

export function AgentsWorkspace({ orgId, children }: PropsWithChildren<{ orgId: string }>) {
  const agents = useQuery({ queryKey: ["agents", orgId], queryFn: () => agentsApi.list(orgId) });
  const agentList = Array.isArray(agents.data) ? agents.data : [];
  return (
    <ContextWorkspace
      label="Agents"
      navigationLabel="智能体导航"
      title="团队"
      sidebar={
        <>
          <section className="context-nav-section">
            <h3>智能体</h3>
            <NavLink className="context-action-entry new-context-entry" to={`/orgs/${orgId}/agents/new`}>+ 新建智能体</NavLink>
          </section>
          <section className="context-nav-section">
            <h3>团队</h3>
            {agents.error && <ErrorNotice error={agents.error} />}
            {agentList.map((agent) => (
              <NavLink key={agent.id} to={`/orgs/${orgId}/agents/${agent.id}`}>
                <span className="context-item-copy">
                  <strong>{agent.name}</strong>
                  <small>{agent.role}</small>
                </span>
                <Badge>{agent.status}</Badge>
              </NavLink>
            ))}
            {agents.isSuccess && agentList.length === 0 && <p className="context-empty">暂无智能体</p>}
          </section>
        </>
      }
    >
      {children}
    </ContextWorkspace>
  );
}
