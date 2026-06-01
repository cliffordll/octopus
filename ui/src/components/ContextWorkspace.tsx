import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent, type PropsWithChildren, type ReactNode } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { agentsApi } from "../api/agents";
import { chatsApi } from "../api/chats";
import { projectsApi } from "../api/projects";
import { readRecentIssues, RECENT_ISSUES_EVENT } from "../utils/recentIssues";
import { Badge } from "./Badge";
import { ErrorNotice } from "./ErrorNotice";

function ContextWorkspace({
  contentClassName = "",
  label,
  title,
  navigationLabel,
  sidebar,
  children,
}: PropsWithChildren<{
  contentClassName?: string;
  label: string;
  title: string;
  navigationLabel: string;
  sidebar: ReactNode;
}>) {
  const isFullBleed = contentClassName.split(" ").includes("org-content-full");
  return (
    <div className="org-workspace context-workspace">
      <aside className="org-sidebar context-sidebar">
        <p className="org-sidebar-label">{label}</p>
        <h2>{title}</h2>
        <nav aria-label={navigationLabel} className="context-nav">
          {sidebar}
        </nav>
      </aside>
      <div className={`org-content ${contentClassName}`}>
        {isFullBleed ? children : <div className="tertiary-detail-frame">{children}</div>}
      </div>
    </div>
  );
}

export function ChatsWorkspace({ contentClassName = "", orgId, children }: PropsWithChildren<{ contentClassName?: string; orgId: string }>) {
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const chats = useQuery({ queryKey: ["chats", orgId], queryFn: () => chatsApi.list(orgId) });
  const agents = useQuery({ queryKey: ["agents", orgId], queryFn: () => agentsApi.list(orgId) });
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [renamingChatId, setRenamingChatId] = useState<string | null>(null);
  const [renameTitle, setRenameTitle] = useState("");
  const [chatActionNotice, setChatActionNotice] = useState<string | null>(null);
  const agentList = Array.isArray(agents.data) ? agents.data : [];
  const agentNameById = new Map(agentList.map((agent) => [agent.id, agent.name]));
  const conversations = Array.isArray(chats.data) ? chats.data : [];
  const updateChat = useMutation({
    mutationFn: ({ chatId, title, status }: { chatId: string; title?: string; status?: "archived" }) =>
      chatsApi.update(chatId, { ...(title !== undefined ? { title } : {}), ...(status ? { status } : {}) }),
    onSuccess: (updated, variables) => {
      queryClient.setQueryData(["chat", updated.id], updated);
      queryClient.setQueryData<typeof conversations>(["chats", orgId], (current) => {
        if (!Array.isArray(current)) return current;
        if (variables.status === "archived") return current.filter((chat) => chat.id !== updated.id);
        return current.map((chat) => (chat.id === updated.id ? { ...chat, ...updated } : chat));
      });
      if (variables.status === "archived" && location.pathname.endsWith(`/chats/${updated.id}`)) {
        navigate(`/orgs/${orgId}/chats`);
      }
      setOpenMenuId(null);
      setRenamingChatId(null);
      setRenameTitle("");
      setChatActionNotice(null);
    },
    onError: (error) => {
      setChatActionNotice(error instanceof Error ? error.message : "操作失败");
    },
  });
  function submitRename(event: FormEvent, chatId: string) {
    event.preventDefault();
    const title = renameTitle.trim();
    if (!title) return;
    updateChat.mutate({ chatId, title });
  }
  function copyChatId(chatId: string) {
    void navigator.clipboard?.writeText(chatId);
    setChatActionNotice("聊天 ID 已复制");
    setOpenMenuId(null);
  }
  return (
    <ContextWorkspace
      contentClassName={contentClassName}
      label="Messages"
      navigationLabel="消息导航"
      title="会话"
      sidebar={
        <>
          <section className="context-nav-section">
            <h3>消息</h3>
            <NavLink className="context-action-entry new-chat-entry" end to={`/orgs/${orgId}/chats`}>
              <span aria-hidden="true" className="context-entry-icon">+</span>
              <span>新建聊天</span>
            </NavLink>
            <NavLink className="context-action-entry" to={`/orgs/${orgId}/approvals`}>
              <span aria-hidden="true" className="context-entry-icon">T</span>
              <span>审批管理</span>
            </NavLink>
            <NavLink className="context-action-entry" to={`/orgs/${orgId}/messenger`}>
              <span aria-hidden="true" className="context-entry-icon">M</span>
              <span>消息中心</span>
            </NavLink>
          </section>
          <section className="context-nav-section chat-conversation-section">
            <h3>对话</h3>
            {chats.error && <ErrorNotice error={chats.error} />}
            {chatActionNotice && <p className="context-action-notice">{chatActionNotice}</p>}
            <div className="chat-conversation-list">
              {conversations.map((chat) => {
                const menuOpen = openMenuId === chat.id;
                const renaming = renamingChatId === chat.id;
                return (
                  <div className="chat-conversation-row" key={chat.id}>
                    <NavLink to={`/orgs/${orgId}/chats/${chat.id}`}>
                      <span aria-hidden="true" className="context-entry-icon">C</span>
                      <span className="context-item-copy">
                        <strong title={chat.title}>{chat.title}</strong>
                        <small title={chat.latestReplyPreview ?? undefined}>
                          {chat.latestReplyPreview
                            ?? (chat.preferredAgentId ? agentNameById.get(chat.preferredAgentId) ?? "未知智能体" : "未选择智能体")}
                        </small>
                      </span>
                    </NavLink>
                    <button
                      aria-expanded={menuOpen}
                      aria-label={`${chat.title} 操作`}
                      className="chat-conversation-menu-trigger"
                      onClick={() => {
                        setOpenMenuId(menuOpen ? null : chat.id);
                        setRenamingChatId(null);
                        setRenameTitle(chat.title);
                        setChatActionNotice(null);
                      }}
                      type="button"
                    >
                      ...
                    </button>
                    {menuOpen && (
                      <div className="chat-conversation-menu">
                        {renaming ? (
                          <form onSubmit={(event) => submitRename(event, chat.id)}>
                            <input
                              aria-label="新会话名称"
                              autoFocus
                              onChange={(event) => setRenameTitle(event.target.value)}
                              value={renameTitle}
                            />
                            <div className="chat-conversation-menu-actions">
                              <button disabled={updateChat.isPending} type="submit">确认</button>
                              <button
                                onClick={() => {
                                  setRenamingChatId(null);
                                  setRenameTitle(chat.title);
                                }}
                                type="button"
                              >
                                取消
                              </button>
                            </div>
                          </form>
                        ) : (
                          <>
                            <button
                              onClick={() => {
                                setRenamingChatId(chat.id);
                                setRenameTitle(chat.title);
                              }}
                              type="button"
                            >
                              重命名
                            </button>
                            <button onClick={() => copyChatId(chat.id)} type="button">复制聊天 ID</button>
                            <button
                              disabled={updateChat.isPending}
                              onClick={() => updateChat.mutate({ chatId: chat.id, status: "archived" })}
                              type="button"
                            >
                              归档
                            </button>
                          </>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
            {chats.isSuccess && conversations.length === 0 && <p className="context-empty">暂无对话</p>}
          </section>
        </>
      }
    >
      {children}
    </ContextWorkspace>
  );
}

export function IssuesWorkspace({ contentClassName = "", orgId, children }: PropsWithChildren<{ contentClassName?: string; orgId: string }>) {
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
      contentClassName={contentClassName}
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
              <span aria-hidden="true" className="context-entry-icon">A</span>
              <span>全部任务</span>
            </NavLink>
            <NavLink
              className={() => location.pathname === issuesRootPath && currentStatus === "backlog" ? "active" : ""}
              to={`${issuesRootPath}?status=backlog`}
            >
              <span aria-hidden="true" className="context-entry-icon">T</span>
              <span>草稿任务</span>
            </NavLink>
            <NavLink
              className={() => location.pathname === issuesRootPath && currentView === "following" ? "active" : ""}
              to={`${issuesRootPath}?view=following`}
            >
              <span aria-hidden="true" className="context-entry-icon">T</span>
              <span>关注中</span>
            </NavLink>
          </section>
          <section className="context-nav-section">
            <h3>最近查看</h3>
            {visibleRecentIssues.map((issue) => (
              <NavLink key={issue.id} to={`/orgs/${orgId}/issues/${issue.id}`}>
                <span aria-hidden="true" className="context-entry-icon">R</span>
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
                <span
                  aria-hidden="true"
                  className="context-entry-icon project-entry-icon"
                  style={{ background: project.color ?? undefined }}
                >
                  P
                </span>
                <span>{project.name}</span>
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

export function AgentsWorkspace({ contentClassName = "", orgId, children }: PropsWithChildren<{ contentClassName?: string; orgId: string }>) {
  const agents = useQuery({ queryKey: ["agents", orgId], queryFn: () => agentsApi.list(orgId) });
  const agentList = Array.isArray(agents.data) ? agents.data : [];
  return (
    <ContextWorkspace
      contentClassName={contentClassName}
      label="Agents"
      navigationLabel="智能体导航"
      title="团队"
      sidebar={
        <>
          <section className="context-nav-section">
            <h3>团队</h3>
            {agents.error && <ErrorNotice error={agents.error} />}
            {agentList.map((agent) => (
              <NavLink key={agent.id} to={`/orgs/${orgId}/agents/${agent.id}`}>
                <span aria-hidden="true" className="context-entry-icon">A</span>
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
