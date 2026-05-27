import { useQuery } from "@tanstack/react-query";
import { useState, type PropsWithChildren, type ReactNode } from "react";
import { Link, NavLink } from "react-router-dom";
import { agentsApi } from "../api/agents";
import { chatsApi } from "../api/chats";
import { issuesApi } from "../api/issues";
import type { ChatConversation } from "../api/types";
import { Badge } from "./Badge";
import { ErrorNotice } from "./ErrorNotice";

function ContextWorkspace({
  label,
  title,
  navigationLabel,
  headerControls,
  sidebar,
  children,
}: PropsWithChildren<{
  label: string;
  title: string;
  navigationLabel: string;
  headerControls?: ReactNode;
  sidebar: ReactNode;
}>) {
  return (
    <div className="org-workspace context-workspace">
      <aside className="org-sidebar context-sidebar">
        <p className="org-sidebar-label">{label}</p>
        <h2>{title}</h2>
        {headerControls}
        <nav aria-label={navigationLabel} className="context-nav">
          {sidebar}
        </nav>
      </aside>
      <div className="org-content">{children}</div>
    </div>
  );
}

export function ChatsWorkspace({ orgId, children }: PropsWithChildren<{ orgId: string }>) {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<ChatConversation["status"] | "">("");
  const chats = useQuery({ queryKey: ["chats", orgId], queryFn: () => chatsApi.list(orgId) });
  const agents = useQuery({ queryKey: ["agents", orgId], queryFn: () => agentsApi.list(orgId) });
  const agentList = Array.isArray(agents.data) ? agents.data : [];
  const agentNameById = new Map(agentList.map((agent) => [agent.id, agent.name]));
  const chatList = (Array.isArray(chats.data) ? chats.data : []).filter((chat) => {
    const matchesSearch = chat.title.toLowerCase().includes(search.trim().toLowerCase());
    return matchesSearch && (!status || chat.status === status);
  });
  return (
    <ContextWorkspace
      label="Messages"
      navigationLabel="消息导航"
      title="会话"
      headerControls={
        <div className="context-filters">
          <label>
            搜索对话
            <input value={search} onChange={(event) => setSearch(event.target.value)} />
          </label>
          <label>
            状态
            <select value={status} onChange={(event) => setStatus(event.target.value as ChatConversation["status"] | "")}>
              <option value="">全部</option>
              <option value="active">active</option>
              <option value="resolved">resolved</option>
              <option value="archived">archived</option>
            </select>
          </label>
        </div>
      }
      sidebar={
        <>
          <NavLink className="new-chat-entry" end to={`/orgs/${orgId}/chats`}>+ 新建对话</NavLink>
          {chats.error && <ErrorNotice error={chats.error} />}
          {chatList.map((chat) => (
            <Link key={chat.id} to={`/orgs/${orgId}/chats/${chat.id}`}>
              <span className="context-item-copy">
                <strong>{chat.title}</strong>
                <small>
                  {chat.preferredAgentId ? agentNameById.get(chat.preferredAgentId) ?? "未知智能体" : "未选择智能体"}
                </small>
              </span>
              <Badge>{chat.status}</Badge>
            </Link>
          ))}
          {chats.isSuccess && chatList.length === 0 && <p className="context-empty">没有匹配的对话</p>}
        </>
      }
    >
      {children}
    </ContextWorkspace>
  );
}

export function IssuesWorkspace({ orgId, children }: PropsWithChildren<{ orgId: string }>) {
  const issues = useQuery({ queryKey: ["issues", orgId, ""], queryFn: () => issuesApi.list(orgId, {}) });
  const issueList = Array.isArray(issues.data) ? issues.data : [];
  return (
    <ContextWorkspace
      label="Tasks"
      navigationLabel="任务导航"
      title="任务"
      sidebar={
        <>
          <Link className="context-all-link" to={`/orgs/${orgId}/issues`}>全部任务</Link>
          {issues.error && <ErrorNotice error={issues.error} />}
          {issueList.map((issue) => (
            <Link key={issue.id} to={`/orgs/${orgId}/issues/${issue.id}`}>
              <span>{issue.title}</span>
              <Badge>{issue.status}</Badge>
            </Link>
          ))}
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
          <NavLink className="new-context-entry" to={`/orgs/${orgId}/agents/new`}>+ 新建智能体</NavLink>
          {agents.error && <ErrorNotice error={agents.error} />}
          {agentList.map((agent) => (
            <Link key={agent.id} to={`/orgs/${orgId}/agents/${agent.id}`}>
              <span className="context-item-copy">
                <strong>{agent.name}</strong>
                <small>{agent.role}</small>
              </span>
              <Badge>{agent.status}</Badge>
            </Link>
          ))}
          {agents.isSuccess && agentList.length === 0 && <p className="context-empty">暂无智能体</p>}
        </>
      }
    >
      {children}
    </ContextWorkspace>
  );
}
