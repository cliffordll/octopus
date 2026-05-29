import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent, type KeyboardEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { agentsApi } from "../api/agents";
import { chatsApi } from "../api/chats";
import { ApiError } from "../api/client";
import type { ChatMessage } from "../api/types";
import { Badge } from "../components/Badge";
import { ChatsWorkspace } from "../components/ContextWorkspace";
import { ErrorNotice } from "../components/ErrorNotice";

export function ChatPage() {
  const { orgId = "", chatId = "" } = useParams();
  const [body, setBody] = useState("");
  const [agentId, setAgentId] = useState("");
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const chat = useQuery({ queryKey: ["chat", chatId], queryFn: () => chatsApi.get(chatId) });
  const agents = useQuery({ queryKey: ["agents", orgId], queryFn: () => agentsApi.list(orgId) });
  const chatAgentList = (agents.data ?? []).filter((agent) => agent.status !== "terminated");
  const boundChatAgent = useQuery({
    queryKey: ["agent", chat.data?.preferredAgentId ?? ""],
    queryFn: () => agentsApi.get(chat.data!.preferredAgentId!),
    enabled: Boolean(chat.data?.preferredAgentId),
  });
  useEffect(() => {
    setAgentId(chat.data?.preferredAgentId ?? "");
  }, [chat.data?.id, chat.data?.preferredAgentId]);
  const selectedChatAgent = useQuery({
    queryKey: ["agent", agentId],
    queryFn: () => agentsApi.get(agentId),
    enabled: Boolean(agentId),
  });
  const messages = useQuery({
    queryKey: ["chat-messages", chatId],
    queryFn: () => chatsApi.listMessages(chatId),
    staleTime: 1000,
  });
  const boundChatAgentName = typeof boundChatAgent.data?.name === "string" ? boundChatAgent.data.name : null;
  const selectedChatAgentName = typeof selectedChatAgent.data?.name === "string" ? selectedChatAgent.data.name : null;
  const selectedChatAgentUnavailable = selectedChatAgent.isSuccess
    && selectedChatAgent.data.status === "terminated";
  const startsNewConversation = Boolean(chat.data && agentId && agentId !== chat.data.preferredAgentId);
  const send = useMutation({
    mutationFn: async () => {
      if (startsNewConversation) {
        const createdChat = await chatsApi.create(orgId, {
          title: body.trim().slice(0, 40),
          preferredAgentId: agentId,
        });
        const created = await chatsApi.addMessage(createdChat.id, { body: body.trim() });
        return { chat: createdChat, messages: created.messages };
      }
      const created = await chatsApi.addMessage(chatId, { body: body.trim() });
      return { chat: null, messages: created.messages };
    },
    onSuccess: (created) => {
      setBody("");
      if (created.chat) {
        queryClient.setQueryData(["chat", created.chat.id], created.chat);
        queryClient.setQueryData(["chat-messages", created.chat.id], created.messages);
        void queryClient.invalidateQueries({ queryKey: ["chats", orgId] });
        navigate(`/orgs/${orgId}/chats/${created.chat.id}`);
        return;
      }
      queryClient.setQueryData<ChatMessage[]>(["chat-messages", chatId], (current = []) => {
        const next = new Map(current.map((message) => [message.id, message]));
        created.messages.forEach((message) => next.set(message.id, message));
        return Array.from(next.values());
      });
    },
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    if (agentId && body.trim() && !selectedChatAgentUnavailable) send.mutate();
  }
  function handleMessageKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    event.currentTarget.form?.requestSubmit();
  }
  const sendError = send.error instanceof ApiError
    && send.error.status >= 500
    && send.error.message === `Request failed (${send.error.status})`
    ? new Error(`消息发送失败。请检查 ${selectedChatAgentName ?? "所选智能体"} 的运行配置后重试。`)
    : send.error;
  if (chat.error) return <ErrorNotice error={chat.error} />;
  return (
    <ChatsWorkspace orgId={orgId}>
      <header className="page-header">
        <div>
          <Link className="back-link" to={`/orgs/${orgId}/chats`}>返回 Chats</Link>
          <h1>{chat.data?.title ?? "载入中..."}</h1>
        </div>
      </header>
      {chat.data && (
        <section className="panel chat-panel">
          <div className="meta-line">
            <Badge>{chat.data.status}</Badge>
          </div>
          <div className="chat-messages">
            {messages.isSuccess && messages.data.length === 0 && (
              <div className="chat-empty-thread">
                <h2>还没有消息</h2>
                <p className="muted">
                  {boundChatAgentName ? `向 ${boundChatAgentName} 发送第一条消息开始对话。` : "发送第一条消息开始对话。"}
                </p>
              </div>
            )}
            {messages.data?.map((message) => (
              <article className={`chat-message ${message.role}`} key={message.id}>
                <strong>
                  {message.role === "user"
                    ? "你"
                    : message.role === "assistant"
                      ? boundChatAgentName ?? "智能体"
                      : "系统"}
                </strong>
                <p>{message.body}</p>
              </article>
            ))}
          </div>
          {messages.error && <ErrorNotice error={messages.error} />}
          <form className="form chat-composer" onSubmit={submit}>
            <label className="chat-message-input">
              消息
              <textarea value={body} onChange={(event) => setBody(event.target.value)} onKeyDown={handleMessageKeyDown} required />
            </label>
            {selectedChatAgentUnavailable && (
              <div className="error-notice">
                当前对话绑定的智能体不能用于消息回复，请新建对话并选择可运行智能体。
              </div>
            )}
            {sendError && <ErrorNotice error={sendError} />}
            <div className="chat-compose-actions">
              <div className="chat-composer-toolbar">
                <select aria-label="对话智能体" value={agentId} onChange={(event) => setAgentId(event.target.value)} required>
                  {chat.data.preferredAgentId && !chatAgentList.some((agent) => agent.id === chat.data.preferredAgentId) && (
                    <option value={chat.data.preferredAgentId}>{boundChatAgentName ?? "当前智能体"}</option>
                  )}
                  {chatAgentList.map((agent) => (
                    <option key={agent.id} value={agent.id}>{agent.name} ({agent.role})</option>
                  ))}
                </select>
              </div>
              <button disabled={!agentId || selectedChatAgentUnavailable || send.isPending} type="submit">发送</button>
            </div>
          </form>
        </section>
      )}
    </ChatsWorkspace>
  );
}
