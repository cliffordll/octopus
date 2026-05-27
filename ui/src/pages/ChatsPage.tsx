import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { agentsApi } from "../api/agents";
import { chatsApi } from "../api/chats";
import { Badge } from "../components/Badge";
import { ChatsWorkspace } from "../components/ContextWorkspace";
import { ErrorNotice } from "../components/ErrorNotice";

export function ChatsPage() {
  const { orgId = "" } = useParams();
  const [title, setTitle] = useState("");
  const [agentId, setAgentId] = useState("");
  const queryClient = useQueryClient();
  const chats = useQuery({ queryKey: ["chats", orgId], queryFn: () => chatsApi.list(orgId) });
  const agents = useQuery({ queryKey: ["agents", orgId], queryFn: () => agentsApi.list(orgId) });
  const create = useMutation({
    mutationFn: () => chatsApi.create(orgId, { title: title.trim(), preferredAgentId: agentId.trim() || null }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["chats", orgId] }),
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    if (title.trim()) create.mutate();
  }
  return (
    <ChatsWorkspace orgId={orgId}>
      <header className="page-header">
        <div><p className="eyebrow">Chats</p><h1>对话</h1></div>
      </header>
      <div className="grid-two">
        <section className="panel">
          <h2>会话列表</h2>
          {chats.error && <ErrorNotice error={chats.error} />}
          <div className="list">
            {chats.data?.map((chat) => (
              <article className="row" key={chat.id}>
                <Link to={`/orgs/${orgId}/chats/${chat.id}`}>{chat.title}</Link>
                <Badge>{chat.status}</Badge>
              </article>
            ))}
          </div>
        </section>
        <form className="panel form" onSubmit={submit}>
          <h2>创建对话</h2>
          <label>标题<input value={title} onChange={(event) => setTitle(event.target.value)} required /></label>
          <label>
            对话智能体
            <select value={agentId} onChange={(event) => setAgentId(event.target.value)}>
              <option value="">自动选择</option>
              {agents.data?.map((agent) => (
                <option key={agent.id} value={agent.id}>{agent.name} ({agent.role})</option>
              ))}
            </select>
          </label>
          {agents.error && <ErrorNotice error={agents.error} />}
          {create.error && <ErrorNotice error={create.error} />}
          <button type="submit">新建对话</button>
        </form>
      </div>
    </ChatsWorkspace>
  );
}
