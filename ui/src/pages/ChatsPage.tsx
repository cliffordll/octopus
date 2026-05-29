import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent, type KeyboardEvent } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { agentsApi } from "../api/agents";
import { chatsApi } from "../api/chats";
import { ApiError } from "../api/client";
import { ChatsWorkspace } from "../components/ContextWorkspace";
import { ErrorNotice } from "../components/ErrorNotice";

export function ChatsPage() {
  const { orgId = "" } = useParams();
  const [searchParams] = useSearchParams();
  const requestedAgentId = searchParams.get("agentId") ?? "";
  const [agentId, setAgentId] = useState("");
  const [body, setBody] = useState("");
  const [createdChatId, setCreatedChatId] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const agents = useQuery({ queryKey: ["agents", orgId], queryFn: () => agentsApi.list(orgId) });
  const agentList = Array.isArray(agents.data) ? agents.data : [];
  const chatAgentList = agentList.filter((agent) => agent.status !== "terminated");
  useEffect(() => {
    if (requestedAgentId && chatAgentList.some((agent) => agent.id === requestedAgentId)) {
      setAgentId(requestedAgentId);
    }
  }, [chatAgentList, requestedAgentId]);
  const create = useMutation({
    mutationFn: async () => {
      const chat = await chatsApi.create(orgId, {
        title: body.trim().slice(0, 40),
        preferredAgentId: agentId,
      });
      setCreatedChatId(chat.id);
      void queryClient.invalidateQueries({ queryKey: ["chats", orgId] });
      const created = await chatsApi.addMessage(chat.id, { body: body.trim() });
      return { chat, messages: created.messages };
    },
    onSuccess: ({ chat, messages }) => {
      queryClient.setQueryData(["chat", chat.id], chat);
      queryClient.setQueryData(["chat-messages", chat.id], messages);
      navigate(`/orgs/${orgId}/chats/${chat.id}`);
    },
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    if (agentId && body.trim()) {
      setCreatedChatId(null);
      create.mutate();
    }
  }
  function handleMessageKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    event.currentTarget.form?.requestSubmit();
  }
  const firstMessageError = create.error instanceof ApiError
    && create.error.message !== `Request failed (${create.error.status})`
    ? `对话已创建，但首条消息发送失败：${create.error.message}`
    : "对话已创建，但首条消息发送失败。请检查所选智能体运行配置后重试。";
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
          {agents.isSuccess && chatAgentList.length === 0 && (
            <p className="muted">暂无可用于对话的智能体，请先创建或恢复智能体。</p>
          )}
          <label className="chat-message-input">
            消息
            <textarea value={body} onChange={(event) => setBody(event.target.value)} onKeyDown={handleMessageKeyDown} required />
          </label>
          {agents.error && <ErrorNotice error={agents.error} />}
          {create.error && createdChatId ? (
            <div className="error-notice">
              {firstMessageError}
              <Link className="chat-error-link" to={`/orgs/${orgId}/chats/${createdChatId}`}>打开已创建的对话</Link>
            </div>
          ) : create.error ? <ErrorNotice error={create.error} /> : null}
          <div className="chat-compose-actions">
            <div className="chat-composer-toolbar">
              <select
                aria-label="对话智能体"
                value={agentId}
                onChange={(event) => setAgentId(event.target.value)}
                required
              >
                <option value="">选择智能体</option>
                {chatAgentList.map((agent) => (
                  <option key={agent.id} value={agent.id}>{agent.name} ({agent.role})</option>
                ))}
              </select>
            </div>
            <button disabled={chatAgentList.length === 0 || create.isPending} type="submit">发送并创建对话</button>
          </div>
        </form>
      </section>
    </ChatsWorkspace>
  );
}
