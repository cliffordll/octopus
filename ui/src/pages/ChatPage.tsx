import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type FocusEvent as ReactFocusEvent, type FormEvent, type KeyboardEvent } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { agentsApi } from "../api/agents";
import { chatsApi } from "../api/chats";
import type { ChatConversation, ChatMessage } from "../api/types";
import { Badge } from "../components/Badge";
import { ChatsWorkspace } from "../components/ContextWorkspace";
import { ErrorNotice } from "../components/ErrorNotice";

interface ChatRouteState {
  sendError?: string;
  draft?: string;
}

function displayError(error: unknown) {
  return error instanceof Error ? error.message : "请求失败";
}

function sendNoticeMessage(value: string) {
  return value.startsWith("首条消息发送失败：") ? value : `消息发送失败：${value}`;
}

function agentAvatarLabel(name: string | null | undefined) {
  return (name?.trim() || "智能体").slice(0, 1).toUpperCase();
}

function hasAssistantReply(messages: ChatMessage[]) {
  return messages.some((message) => message.role === "assistant");
}

const missingAssistantReplyMessage = "智能体没有返回消息。请检查所选智能体运行配置后重试。";

function skillLabel(entry: Record<string, unknown>) {
  const value = entry.selectionKey ?? entry.key ?? entry.runtimeName ?? entry.name ?? entry.slug ?? entry.id ?? entry.shortName;
  return typeof value === "string" && value.trim() ? value.trim() : "skill";
}

function agentOptionLabel(agent: { name?: string | null; role?: string | null } | null | undefined, fallback: string) {
  if (!agent?.name) return fallback;
  return agent.role ? `${agent.name} (${agent.role})` : agent.name;
}

function focusLeftElement(event: ReactFocusEvent<HTMLElement>) {
  return !(event.relatedTarget instanceof Node) || !event.currentTarget.contains(event.relatedTarget);
}

export function ChatPage() {
  const { orgId = "", chatId = "" } = useParams();
  const [body, setBody] = useState("");
  const [agentId, setAgentId] = useState("");
  const [sendNotice, setSendNotice] = useState<string | null>(null);
  const [optimisticMessages, setOptimisticMessages] = useState<ChatMessage[]>([]);
  const [thinkingChatId, setThinkingChatId] = useState<string | null>(null);
  const [skillDropdownOpen, setSkillDropdownOpen] = useState(false);
  const messageThreadRef = useRef<HTMLDivElement | null>(null);
  const skillDropdownRef = useRef<HTMLDetailsElement | null>(null);
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();
  const routeState = location.state as ChatRouteState | null;
  const cachedChat = queryClient.getQueryData<ChatConversation>(["chat", chatId])
    ?? queryClient.getQueryData<ChatConversation[]>(["chats", orgId])?.find((item) => item.id === chatId);
  const chat = useQuery({
    queryKey: ["chat", chatId],
    queryFn: () => chatsApi.get(chatId),
    initialData: cachedChat,
    retry: cachedChat ? false : 3,
  });
  const agents = useQuery({ queryKey: ["agents", orgId], queryFn: () => agentsApi.list(orgId) });
  const agentList = Array.isArray(agents.data) ? agents.data : [];
  useEffect(() => {
    setAgentId(chat.data?.preferredAgentId ?? "");
  }, [chat.data?.id, chat.data?.preferredAgentId]);
  useEffect(() => {
    if (routeState?.draft) setBody(routeState.draft);
    if (routeState?.sendError) setSendNotice(routeState.sendError);
  }, [routeState?.draft, routeState?.sendError]);
  const messages = useQuery({
    queryKey: ["chat-messages", chatId],
    queryFn: () => chatsApi.listMessages(chatId),
    staleTime: 1000,
  });
  const selectedAgentSkills = useQuery({
    queryKey: ["agent-skills", agentId],
    queryFn: () => agentsApi.skills(agentId),
    enabled: Boolean(agentId),
  });
  useEffect(() => {
    if (!skillDropdownOpen) return;
    function closeWhenOutside(event: Event) {
      if (event.target instanceof Node && !skillDropdownRef.current?.contains(event.target)) {
        setSkillDropdownOpen(false);
      }
    }
    document.addEventListener("pointerdown", closeWhenOutside);
    document.addEventListener("focusin", closeWhenOutside);
    return () => {
      document.removeEventListener("pointerdown", closeWhenOutside);
      document.removeEventListener("focusin", closeWhenOutside);
    };
  }, [skillDropdownOpen]);
  const visibleMessages = useMemo(() => {
    const persisted = messages.data ?? [];
    const persistedUserBodies = new Set(
      persisted
        .filter((message) => message.role === "user")
        .map((message) => message.body),
    );
    const merged = new Map<string, ChatMessage>();
    for (const message of persisted) merged.set(message.id, message);
    for (const message of optimisticMessages) {
      if (message.role === "user" && persistedUserBodies.has(message.body)) continue;
      if (!merged.has(message.id)) merged.set(message.id, message);
    }
    return Array.from(merged.values());
  }, [messages.data, optimisticMessages]);
  useEffect(() => {
    const messageThread = messageThreadRef.current;
    if (!messageThread) return;
    messageThread.scrollTop = messageThread.scrollHeight;
  }, [visibleMessages.length, thinkingChatId, sendNotice]);
  const agentNameById = useMemo(() => new Map(agentList.map((agent) => [agent.id, agent.name])), [agentList]);
  const boundChatAgentName = chat.data?.preferredAgentId ? agentNameById.get(chat.data.preferredAgentId) ?? null : null;
  const selectedAgent = agentList.find((agent) => agent.id === agentId);
  const selectedAgentName = selectedAgent?.name ?? boundChatAgentName ?? "智能体";
  const selectedAgentControlLabel = agentOptionLabel(selectedAgent, selectedAgentName);
  const projectContext = chat.data?.contextLinks?.find((link) => link.entityType === "project");
  const skillEntries = selectedAgentSkills.data && !Array.isArray(selectedAgentSkills.data) && Array.isArray(selectedAgentSkills.data.entries)
    ? selectedAgentSkills.data.entries
    : [];
  const desiredSkills = selectedAgentSkills.data && !Array.isArray(selectedAgentSkills.data) && Array.isArray(selectedAgentSkills.data.desiredSkills)
    ? selectedAgentSkills.data.desiredSkills
    : [];
  const selectedChatAgentUnavailable = selectedAgent?.status === "terminated";
  const startsNewConversation = Boolean(chat.data && agentId && agentId !== chat.data.preferredAgentId);
  const send = useMutation({
    mutationFn: async () => {
      const draft = body.trim();
      const targetChatId = startsNewConversation ? null : chatId;
      const optimisticMessage: ChatMessage = {
        id: `pending-${Date.now()}`,
        orgId,
        conversationId: targetChatId ?? undefined,
        role: "user",
        kind: "message",
        body: draft,
        status: "completed",
        createdAt: new Date().toISOString(),
      };
      setOptimisticMessages((current) => [...current, optimisticMessage]);
      setThinkingChatId(targetChatId);
      setBody("");
      setSendNotice(null);
      if (startsNewConversation) {
        const createdChat = await chatsApi.create(orgId, {
          title: draft.slice(0, 40) || "新对话",
          preferredAgentId: agentId,
        });
        queryClient.setQueryData(["chat", createdChat.id], createdChat);
        const created = await chatsApi.addMessage(createdChat.id, { body: draft });
        return { chat: createdChat, messages: created.messages };
      }
      const created = await chatsApi.addMessage(chatId, { body: draft });
      return { chat: null, messages: created.messages };
    },
    onSuccess: (created) => {
      setThinkingChatId(null);
      setSendNotice(null);
      const missingAssistantReply = !hasAssistantReply(created.messages);
      if (created.chat) {
        queryClient.setQueryData(["chat", created.chat.id], created.chat);
        queryClient.setQueryData(["chat-messages", created.chat.id], created.messages);
        void queryClient.invalidateQueries({ queryKey: ["chats", orgId] });
        navigate(`/orgs/${orgId}/chats/${created.chat.id}`, {
          state: missingAssistantReply ? { sendError: `首条消息发送失败：${missingAssistantReplyMessage}` } : undefined,
        });
        return;
      }
      queryClient.setQueryData<ChatMessage[]>(["chat-messages", chatId], (current = []) => {
        const next = new Map(current.map((message) => [message.id, message]));
        created.messages.forEach((message) => next.set(message.id, message));
        return Array.from(next.values());
      });
      if (missingAssistantReply) setSendNotice(missingAssistantReplyMessage);
    },
    onError: (error) => {
      setThinkingChatId(null);
      setSendNotice(displayError(error));
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
  if (chat.error && !chat.data) return <ErrorNotice error={chat.error} />;
  return (
    <ChatsWorkspace contentClassName="org-content-full" orgId={orgId}>
      {chat.data && (
        <section className="chat-thread-shell">
          <header className="chat-thread-header">
            <div>
              <h1>{chat.data.title}</h1>
              <p>{boundChatAgentName ? `使用 ${boundChatAgentName}` : "选择智能体后发送消息"}</p>
            </div>
            <div className="meta-line">
              <Badge>{chat.data.status}</Badge>
              {chat.data.isPinned && <Badge>已置顶</Badge>}
              {chat.data.unreadCount ? <Badge>{chat.data.unreadCount} 未读</Badge> : null}
            </div>
          </header>
          {chat.error && (
            <div className="error-notice">
              已打开本地缓存的对话，详情刷新失败：{chat.error instanceof Error ? chat.error.message : "请求失败"}
            </div>
          )}
          <div className="chat-messages" data-testid="chat-message-thread" ref={messageThreadRef}>
            {messages.isSuccess && visibleMessages.length === 0 && (
              <div className="chat-empty-thread">
                <h2>No messages yet.</h2>
                <p className="muted">
                  {boundChatAgentName ? `向 ${boundChatAgentName} 发送第一条消息开始对话。` : "发送第一条消息开始对话。"}
                </p>
              </div>
            )}
            {visibleMessages.map((message) => (
              <article className={`chat-message ${message.role}`} key={message.id}>
                {message.role === "assistant" && (
                  <span aria-hidden="true" className="chat-agent-avatar">
                    {agentAvatarLabel(message.replyingAgentId ? agentNameById.get(message.replyingAgentId) : boundChatAgentName)}
                  </span>
                )}
                <div className="chat-message-body">
                  <strong>
                    {message.role === "user"
                      ? "你"
                      : message.role === "assistant"
                        ? (message.replyingAgentId ? agentNameById.get(message.replyingAgentId) : boundChatAgentName) ?? "智能体"
                        : "系统"}
                  </strong>
                  <div className="meta-line">
                    <Badge>{message.kind ?? "message"}</Badge>
                    <Badge>{message.status}</Badge>
                    {message.approvalId && <Badge>审批 {message.approvalId}</Badge>}
                    {typeof message.turnVariant === "number" && message.turnVariant > 0 && <Badge>变体 {message.turnVariant}</Badge>}
                  </div>
                  <p>{message.body}</p>
                  {message.attachments && message.attachments.length > 0 && (
                    <div className="chat-attachment-list">
                      {message.attachments.map((attachment) => (
                        <a className="chat-attachment-chip" href={attachment.contentPath} key={attachment.id}>
                          {attachment.originalFilename ?? attachment.id}
                          <span>{attachment.byteSize} bytes</span>
                        </a>
                      ))}
                    </div>
                  )}
                  {message.structuredPayload && (
                    <pre className="json-block">{JSON.stringify(message.structuredPayload, null, 2)}</pre>
                  )}
                </div>
              </article>
            ))}
            {send.isPending && thinkingChatId === chatId && (
              <article aria-live="polite" className="chat-message assistant thinking">
                <span aria-hidden="true" className="chat-agent-avatar">{agentAvatarLabel(selectedAgentName)}</span>
                <div className="chat-message-body">
                  <strong>{selectedAgentName}</strong>
                  <p className="chat-thinking-text">
                    Thinking<span aria-hidden="true" className="thinking-dots"><span>.</span><span>.</span><span>.</span></span>
                  </p>
                </div>
              </article>
            )}
            {sendNotice && (
              <article className="chat-message system">
                <strong>系统</strong>
                <p>{sendNoticeMessage(sendNotice)}</p>
              </article>
            )}
          </div>
          {messages.error && <ErrorNotice error={messages.error} />}
          <form aria-label="发送消息" className="form chat-composer" onSubmit={submit}>
            <label className="chat-message-input">
              消息
              <textarea
                placeholder="输入消息，Enter 发送，Shift+Enter 换行"
                value={body}
                onChange={(event) => setBody(event.target.value)}
                onKeyDown={handleMessageKeyDown}
                required
              />
            </label>
            {selectedChatAgentUnavailable && (
              <div className="error-notice">
                当前选择的智能体不能用于消息回复，请切换到可运行智能体。
              </div>
            )}
            {selectedAgentSkills.error && <ErrorNotice error={selectedAgentSkills.error} />}
            <div className="chat-context-controls chat-context-controls-readonly" aria-label="当前对话上下文">
              <label aria-label="当前项目">
                <select aria-label="项目" disabled value={projectContext?.entityId ?? ""}>
                  <option value={projectContext?.entityId ?? ""}>
                    {projectContext?.entity?.label ?? (projectContext ? projectContext.entityId : "未关联项目")}
                  </option>
                </select>
              </label>
              <label aria-label="当前智能体" className="chat-agent-readonly-field">
                <select aria-label="对话智能体" disabled value={agentId}>
                  <option value={agentId}>{selectedAgentControlLabel}</option>
                </select>
              </label>
              <details
                className="chat-skill-dropdown"
                onBlur={(event) => {
                  if (focusLeftElement(event)) setSkillDropdownOpen(false);
                }}
                onToggle={(event) => setSkillDropdownOpen(event.currentTarget.open)}
                open={skillDropdownOpen}
                ref={skillDropdownRef}
              >
                <summary>技能列表</summary>
                <div className="chat-skill-list">
                  {desiredSkills.map((skill) => (
                    <span className="chat-skill-chip active" key={`desired-${skill}`}>{skill}</span>
                  ))}
                  {skillEntries.map((entry) => (
                    <span className="chat-skill-chip" key={skillLabel(entry)}>{skillLabel(entry)}</span>
                  ))}
                  {agentId && selectedAgentSkills.isSuccess && desiredSkills.length === 0 && skillEntries.length === 0 && (
                    <span className="muted">暂无技能</span>
                  )}
                  {!agentId && <span className="muted">未选择智能体</span>}
                </div>
              </details>
              <button className="chat-create-submit" disabled={!agentId || selectedChatAgentUnavailable || send.isPending} type="submit">
                发送
              </button>
            </div>
          </form>
        </section>
      )}
    </ChatsWorkspace>
  );
}
