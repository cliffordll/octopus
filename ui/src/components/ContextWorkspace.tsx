import { useQuery } from "@tanstack/react-query";
import type { PropsWithChildren, ReactNode } from "react";
import { Link } from "react-router-dom";
import { agentsApi } from "../api/agents";
import { chatsApi } from "../api/chats";
import { issuesApi } from "../api/issues";
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
  const chatList = Array.isArray(chats.data) ? chats.data : [];
  return (
    <ContextWorkspace
      label="Messages"
      navigationLabel="消息导航"
      title="会话"
      sidebar={
        <>
          {chats.error && <ErrorNotice error={chats.error} />}
          {chatList.map((chat) => (
            <Link key={chat.id} to={`/orgs/${orgId}/chats/${chat.id}`}>
              <span>{chat.title}</span>
              <Badge>{chat.status}</Badge>
            </Link>
          ))}
          {chats.isSuccess && chatList.length === 0 && <p className="context-empty">暂无会话</p>}
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
          {agents.error && <ErrorNotice error={agents.error} />}
          {agentList.map((agent) => (
            <Link key={agent.id} to={`/orgs/${orgId}/agents/${agent.id}`}>
              <span>{agent.name}</span>
              <Badge>{agent.role}</Badge>
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
