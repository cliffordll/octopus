import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { agentsApi } from "../api/agents";
import { chatsApi } from "../api/chats";
import { Badge } from "../components/Badge";
import { ChatsWorkspace } from "../components/ContextWorkspace";
import { ErrorNotice } from "../components/ErrorNotice";

export function ChatPage() {
  const { orgId = "", chatId = "" } = useParams();
  const [body, setBody] = useState("");
  const queryClient = useQueryClient();
  const chat = useQuery({ queryKey: ["chat", chatId], queryFn: () => chatsApi.get(chatId) });
  const chatAgent = useQuery({
    queryKey: ["agent", chat.data?.preferredAgentId ?? ""],
    queryFn: () => agentsApi.get(chat.data!.preferredAgentId!),
    enabled: Boolean(chat.data?.preferredAgentId),
  });
  const messages = useQuery({ queryKey: ["chat-messages", chatId], queryFn: () => chatsApi.listMessages(chatId) });
  const send = useMutation({
    mutationFn: () => chatsApi.addMessage(chatId, { body: body.trim() }),
    onSuccess: () => {
      setBody("");
      void queryClient.invalidateQueries({ queryKey: ["chat-messages", chatId] });
    },
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    if (body.trim()) send.mutate();
  }
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
            <Badge>{chat.data.preferredAgentId ? chatAgent.data?.name ?? "载入智能体..." : "未选择智能体"}</Badge>
          </div>
          <div className="chat-messages">
            {messages.data?.map((message) => (
              <article className={`chat-message ${message.role}`} key={message.id}>
                <strong>{message.role}</strong>
                <p>{message.body}</p>
              </article>
            ))}
          </div>
          {messages.error && <ErrorNotice error={messages.error} />}
          <form className="form chat-composer" onSubmit={submit}>
            <label>消息<textarea value={body} onChange={(event) => setBody(event.target.value)} required /></label>
            {send.error && <ErrorNotice error={send.error} />}
            <div className="chat-compose-actions">
              <button type="submit">发送</button>
            </div>
          </form>
        </section>
      )}
    </ChatsWorkspace>
  );
}
