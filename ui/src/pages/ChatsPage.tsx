import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { agentsApi } from "../api/agents";
import { chatsApi } from "../api/chats";
import { ChatsWorkspace } from "../components/ContextWorkspace";
import { ErrorNotice } from "../components/ErrorNotice";

export function ChatsPage() {
  const { orgId = "" } = useParams();
  const [title, setTitle] = useState("");
  const [agentId, setAgentId] = useState("");
  const [body, setBody] = useState("");
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const agents = useQuery({ queryKey: ["agents", orgId], queryFn: () => agentsApi.list(orgId) });
  const agentList = Array.isArray(agents.data) ? agents.data : [];
  const create = useMutation({
    mutationFn: async () => {
      const chat = await chatsApi.create(orgId, {
        title: title.trim() || body.trim().slice(0, 40),
        preferredAgentId: agentId,
      });
      await chatsApi.addMessage(chat.id, { body: body.trim() });
      return chat;
    },
    onSuccess: (chat) => {
      void queryClient.invalidateQueries({ queryKey: ["chats", orgId] });
      navigate(`/orgs/${orgId}/chats/${chat.id}`);
    },
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    if (agentId && body.trim()) create.mutate();
  }
  return (
    <ChatsWorkspace orgId={orgId}>
      <header className="page-header">
        <div><p className="eyebrow">Messages</p><h1>新对话</h1></div>
      </header>
      <section className="panel chat-panel">
        <div className="chat-empty-state">
          <h2>开始新的对话</h2>
          <p className="muted">选择智能体并发送第一条消息。</p>
        </div>
        <form className="form chat-composer" onSubmit={submit}>
          <div className="chat-compose-context">
            <label>
              标题（可选）
              <input value={title} onChange={(event) => setTitle(event.target.value)} />
            </label>
            <label>
              对话智能体
              <select value={agentId} onChange={(event) => setAgentId(event.target.value)} required>
                <option value="">选择智能体</option>
                {agentList.map((agent) => (
                  <option key={agent.id} value={agent.id}>{agent.name} ({agent.role})</option>
                ))}
              </select>
            </label>
          </div>
          <label>消息<textarea value={body} onChange={(event) => setBody(event.target.value)} required /></label>
          {agents.error && <ErrorNotice error={agents.error} />}
          {create.error && <ErrorNotice error={create.error} />}
          <div className="chat-compose-actions">
            <button type="submit">发送并创建对话</button>
          </div>
        </form>
      </section>
    </ChatsWorkspace>
  );
}
