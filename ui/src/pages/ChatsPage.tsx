import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent, type KeyboardEvent } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { agentsApi } from "../api/agents";
import { chatsApi } from "../api/chats";
import { ChatsWorkspace } from "../components/ContextWorkspace";
import { ErrorNotice } from "../components/ErrorNotice";

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "请求失败";
}

export function ChatsPage() {
  const { orgId = "" } = useParams();
  const [searchParams] = useSearchParams();
  const requestedAgentId = searchParams.get("agentId") ?? "";
  const [agentId, setAgentId] = useState("");
  const [body, setBody] = useState("");
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
      const draft = body.trim();
      const chat = await chatsApi.create(orgId, {
        title: draft.slice(0, 40) || "新对话",
        preferredAgentId: agentId,
      });
      queryClient.setQueryData(["chat", chat.id], chat);
      void queryClient.invalidateQueries({ queryKey: ["chats", orgId] });
      try {
        const created = await chatsApi.addMessage(chat.id, { body: draft });
        return { chat, messages: created.messages, draft, firstMessageError: null };
      } catch (error) {
        queryClient.setQueryData(["chat-messages", chat.id], []);
        return { chat, messages: null, draft, firstMessageError: errorMessage(error) };
      }
    },
    onSuccess: ({ chat, messages, draft, firstMessageError }) => {
      queryClient.setQueryData(["chat", chat.id], chat);
      if (messages) {
        queryClient.setQueryData(["chat-messages", chat.id], messages);
        setBody("");
      }
      navigate(`/orgs/${orgId}/chats/${chat.id}`, {
        state: firstMessageError ? { sendError: `首条消息发送失败：${firstMessageError}`, draft } : undefined,
      });
    },
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    if (agentId && body.trim()) {
      create.mutate();
    }
  }
  function handleMessageKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    event.currentTarget.form?.requestSubmit();
  }
  return (
    <ChatsWorkspace orgId={orgId}>
      <header className="page-header">
        <div><p className="eyebrow">Messages</p><h1>新对话</h1></div>
      </header>
      <section className="panel chat-panel">
        <div className="chat-empty-state">
          <h2>What do you want to work on?</h2>
          <p className="muted">选择智能体并发送第一条消息。</p>
        </div>
        <form className="form chat-composer" onSubmit={submit}>
          {agents.isSuccess && chatAgentList.length === 0 && (
            <p className="muted">暂无可用于对话的智能体，请先创建或恢复智能体。</p>
          )}
          <label className="chat-message-input">
            消息
            <textarea
              autoFocus
              placeholder="输入消息，Enter 发送，Shift+Enter 换行"
              value={body}
              onChange={(event) => setBody(event.target.value)}
              onKeyDown={handleMessageKeyDown}
              required
            />
          </label>
          {agents.error && <ErrorNotice error={agents.error} />}
          {create.error ? <ErrorNotice error={create.error} /> : null}
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
