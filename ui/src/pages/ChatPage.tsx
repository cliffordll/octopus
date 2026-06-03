import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type FocusEvent as ReactFocusEvent, type FormEvent, type KeyboardEvent } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { agentsApi } from "../api/agents";
import { approvalsApi } from "../api/approvals";
import { chatsApi } from "../api/chats";
import type { ChatConversation, ChatMessage } from "../api/types";
import { Badge } from "../components/Badge";
import { ChatsWorkspace } from "../components/ContextWorkspace";
import { ErrorNotice } from "../components/ErrorNotice";
import { formatBytes, roleLabel, statusLabel } from "../utils/display";

interface ChatRouteState {
  sendError?: string;
  draft?: string;
  initialMessage?: string;
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

function isChatMessage(value: unknown): value is ChatMessage {
  return Boolean(value && typeof value === "object" && "id" in value && "role" in value && "body" in value);
}

function issueProposalFromMessage(message: ChatMessage): Record<string, unknown> | null {
  if (message.kind !== "issue_proposal" || !message.structuredPayload) return null;
  const proposal = message.structuredPayload.issueProposal;
  return proposal && typeof proposal === "object" && !Array.isArray(proposal)
    ? proposal as Record<string, unknown>
    : message.structuredPayload;
}

function issueCreatedEventFromMessage(message: ChatMessage): { issueId: string; issueIdentifier: string | null } | null {
  if (message.kind !== "system_event" || message.structuredPayload?.eventType !== "issue_created") return null;
  const issueId = message.structuredPayload.issueId;
  if (typeof issueId !== "string" || !issueId) return null;
  const issueIdentifier = message.structuredPayload.issueIdentifier;
  return {
    issueId,
    issueIdentifier: typeof issueIdentifier === "string" && issueIdentifier ? issueIdentifier : null,
  };
}

function proposalText(value: unknown): string {
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

const missingAssistantReplyMessage = "智能体没有返回消息。请检查所选智能体运行配置后重试。";

function skillLabel(entry: Record<string, unknown>) {
  const value = entry.selectionKey ?? entry.key ?? entry.runtimeName ?? entry.name ?? entry.slug ?? entry.id ?? entry.shortName;
  return typeof value === "string" && value.trim() ? value.trim() : "skill";
}

function agentOptionLabel(agent: { name?: string | null; role?: string | null } | null | undefined, fallback: string) {
  if (!agent?.name) return fallback;
  return agent.role ? `${agent.name} (${roleLabel(agent.role)})` : agent.name;
}

function chatIssueCreationModeLabel(mode: string | null | undefined): string {
  return mode === "auto_create" ? "自动创建" : "手动审批";
}

type ChatApprovalPromptStatus = "pending" | "revision_requested" | "approved" | "rejected" | "cancelled";
type ChatApprovalPromptAction = "approve" | "requestRevision" | "reject";

function chatApprovalStatusLabel(status: ChatApprovalPromptStatus): string {
  if (status === "revision_requested") return "需修改";
  if (status === "approved") return "已同意";
  if (status === "rejected") return "已拒绝";
  if (status === "cancelled") return "已取消";
  return "待审批";
}

function focusLeftElement(event: ReactFocusEvent<HTMLElement>) {
  return !(event.relatedTarget instanceof Node) || !event.currentTarget.contains(event.relatedTarget);
}

export function ChatPage() {
  const { orgId = "", chatId = "" } = useParams();
  const location = useLocation();
  const routeState = location.state as ChatRouteState | null;
  const [body, setBody] = useState("");
  const [agentId, setAgentId] = useState("");
  const [sendNotice, setSendNotice] = useState<string | null>(null);
  const [optimisticMessages, setOptimisticMessages] = useState<ChatMessage[]>([]);
  const [thinkingChatId, setThinkingChatId] = useState<string | null>(null);
  const [streamingReply, setStreamingReply] = useState("");
  const [initialMessageInFlight, setInitialMessageInFlight] = useState(Boolean(routeState?.initialMessage));
  const [skillDropdownOpen, setSkillDropdownOpen] = useState(false);
  const [approvalPrompt, setApprovalPrompt] = useState<{
    approvalId: string;
    proposal: Record<string, unknown>;
    status: ChatApprovalPromptStatus;
  } | null>(null);
  const [dismissedApprovalIds, setDismissedApprovalIds] = useState<Set<string>>(() => new Set());
  const messageThreadRef = useRef<HTMLDivElement | null>(null);
  const skillDropdownRef = useRef<HTMLDetailsElement | null>(null);
  const initialMessageStartedRef = useRef<string | null>(null);
  const queryClient = useQueryClient();
  const navigate = useNavigate();
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
    enabled: !initialMessageInFlight,
    staleTime: 1000,
  });
  const selectedAgentSkills = useQuery({
    queryKey: ["agent-skills", agentId],
    queryFn: () => agentsApi.skills(agentId),
    enabled: Boolean(agentId),
  });
  const approvalPromptDetail = useQuery({
    queryKey: ["approval", approvalPrompt?.approvalId],
    queryFn: () => approvalsApi.get(approvalPrompt?.approvalId ?? ""),
    enabled: Boolean(approvalPrompt?.approvalId),
  });
  const approvalPromptStatus = (
    approvalPromptDetail.data?.status as ChatApprovalPromptStatus | undefined
  ) ?? approvalPrompt?.status ?? null;
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
    if (!orgId || !chatId || approvalPrompt) return;
    const issueCreated = visibleMessages.some((message) => Boolean(issueCreatedEventFromMessage(message)));
    if (issueCreated) return;
    const proposalMessage = [...visibleMessages].reverse().find((message) =>
      Boolean(message.approvalId && !dismissedApprovalIds.has(message.approvalId) && issueProposalFromMessage(message)),
    );
    if (!proposalMessage?.approvalId) return;
    const proposal = issueProposalFromMessage(proposalMessage);
    if (!proposal) return;
    setApprovalPrompt({
      approvalId: proposalMessage.approvalId,
      proposal,
      status: "pending",
    });
  }, [approvalPrompt, chatId, dismissedApprovalIds, orgId, visibleMessages]);
  useEffect(() => {
    if (!approvalPrompt) return;
    const issueCreated = visibleMessages.some((message) => Boolean(issueCreatedEventFromMessage(message)));
    if (issueCreated) setApprovalPrompt(null);
  }, [approvalPrompt, visibleMessages]);
  useEffect(() => {
    if (!approvalPrompt || approvalPromptStatus !== "approved") return;
    void queryClient.invalidateQueries({ queryKey: ["chat", chatId] });
    void queryClient.invalidateQueries({ queryKey: ["chat-messages", chatId] });
    const timer = window.setTimeout(() => {
      setDismissedApprovalIds((current) => new Set(current).add(approvalPrompt.approvalId));
      setApprovalPrompt(null);
    }, 4000);
    return () => window.clearTimeout(timer);
  }, [approvalPrompt, approvalPromptStatus, chatId, queryClient]);
  useEffect(() => {
    if (!approvalPrompt) return;
    if (!approvalPromptStatus || approvalPromptStatus === "pending" || approvalPromptStatus === "approved") return;
    setDismissedApprovalIds((current) => new Set(current).add(approvalPrompt.approvalId));
    setApprovalPrompt(null);
  }, [approvalPrompt, approvalPromptStatus]);
  useEffect(() => {
    const messageThread = messageThreadRef.current;
    if (!messageThread) return;
    messageThread.scrollTop = messageThread.scrollHeight;
  }, [visibleMessages.length, thinkingChatId, streamingReply, sendNotice, approvalPrompt]);
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
  const convertIssue = useMutation({
    mutationFn: (messageId: string) => chatsApi.convertToIssue(chatId, { messageId }),
    onSuccess: ({ systemMessage }) => {
      queryClient.setQueryData<ChatMessage[]>(["chat-messages", chatId], (current = []) => {
        const next = new Map(current.map((message) => [message.id, message]));
        next.set(systemMessage.id, systemMessage);
        return Array.from(next.values());
      });
      void queryClient.invalidateQueries({ queryKey: ["chat", chatId] });
      void queryClient.invalidateQueries({ queryKey: ["chats", orgId] });
      void queryClient.invalidateQueries({ queryKey: ["issues", orgId] });
    },
    onError: (error) => {
      setSendNotice(displayError(error));
    },
  });
  const decideIssueProposal = useMutation({
    mutationFn: ({ action, approvalId }: { action: ChatApprovalPromptAction; approvalId: string }) => {
      if (action === "reject") return approvalsApi.reject(approvalId);
      if (action === "requestRevision") return approvalsApi.requestRevision(approvalId);
      return approvalsApi.approve(approvalId);
    },
    onSuccess: (approval) => {
      const nextStatus = approval.status as ChatApprovalPromptStatus;
      setApprovalPrompt((current) => {
        if (current?.approvalId !== approval.id) return current;
        return nextStatus === "pending" || nextStatus === "approved"
          ? { ...current, status: nextStatus }
          : null;
      });
      if (nextStatus !== "pending" && nextStatus !== "approved") {
        setDismissedApprovalIds((current) => new Set(current).add(approval.id));
      }
      void queryClient.invalidateQueries({ queryKey: ["approval", approval.id] });
      void queryClient.invalidateQueries({ queryKey: ["messenger-approvals", orgId] });
      void queryClient.invalidateQueries({ queryKey: ["approvals", orgId] });
      void queryClient.invalidateQueries({ queryKey: ["chat", chatId] });
      void queryClient.invalidateQueries({ queryKey: ["chat-messages", chatId] });
      void queryClient.invalidateQueries({ queryKey: ["chats", orgId] });
      void queryClient.invalidateQueries({ queryKey: ["issues", orgId] });
    },
    onError: (error) => {
      setSendNotice(displayError(error));
    },
  });
  const send = useMutation({
    mutationFn: async (draft: string) => {
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
      const cachedMessages = targetChatId
        ? queryClient.getQueryData<ChatMessage[]>(["chat-messages", targetChatId]) ?? []
        : [];
      const hasCachedUserMessage = cachedMessages.some((message) => message.role === "user" && message.body === draft);
      if (!hasCachedUserMessage) {
        setOptimisticMessages((current) => [...current, optimisticMessage]);
      }
      setThinkingChatId(targetChatId);
      setStreamingReply("");
      setBody("");
      setSendNotice(null);
      if (startsNewConversation) {
        const createdChat = await chatsApi.create(orgId, {
          title: draft.slice(0, 40) || "新对话",
          preferredAgentId: agentId,
        });
        queryClient.setQueryData(["chat", createdChat.id], createdChat);
        const created = await chatsApi.addMessageStream(createdChat.id, { body: draft }, (event) => {
          if (event.type === "assistant_delta" && typeof event.delta === "string") {
            setStreamingReply((current) => `${current}${event.delta}`);
          }
        });
        return { chat: createdChat, messages: created.messages };
      }
      const created = await chatsApi.addMessageStream(chatId, { body: draft }, (event) => {
        const acknowledgedMessage = event.type === "ack" && isChatMessage(event.userMessage) ? event.userMessage : null;
        if (acknowledgedMessage) {
          queryClient.setQueryData<ChatMessage[]>(["chat-messages", chatId], (current = []) => {
            const next = new Map(
              current
                .filter((message) => !(message.role === "user" && message.body === acknowledgedMessage.body))
                .map((message) => [message.id, message]),
            );
            next.set(acknowledgedMessage.id, acknowledgedMessage);
            return Array.from(next.values());
          });
        }
        if (event.type === "assistant_delta" && typeof event.delta === "string") {
          setStreamingReply((current) => `${current}${event.delta}`);
        }
      });
      return { chat: null, messages: created.messages };
    },
    onSuccess: (created) => {
      setThinkingChatId(null);
      setStreamingReply("");
      setInitialMessageInFlight(false);
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
        created.messages.forEach((message) => {
          if (message.role === "user") {
            Array.from(next.values()).forEach((existing) => {
              if (existing.role === "user" && existing.body === message.body) next.delete(existing.id);
            });
          }
          next.set(message.id, message);
        });
        return Array.from(next.values());
      });
      if (missingAssistantReply) setSendNotice(missingAssistantReplyMessage);
    },
    onError: (error) => {
      setThinkingChatId(null);
      setStreamingReply("");
      setInitialMessageInFlight(false);
      setSendNotice(displayError(error));
    },
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    const draft = body.trim();
    if (agentId && draft && !selectedChatAgentUnavailable) send.mutate(draft);
  }
  function handleMessageKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    event.currentTarget.form?.requestSubmit();
  }
  useEffect(() => {
    if (
      !routeState?.initialMessage
      || !chat.data
      || !agentId
      || selectedChatAgentUnavailable
      || send.isPending
      || initialMessageStartedRef.current === chatId
    ) {
      return;
    }
    initialMessageStartedRef.current = chatId;
    setInitialMessageInFlight(true);
    send.mutate(routeState.initialMessage);
    navigate(location.pathname, { replace: true, state: null });
  }, [agentId, chat.data, chatId, location.pathname, navigate, routeState?.initialMessage, selectedChatAgentUnavailable, send]);
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
              <Badge>{statusLabel(chat.data.status)}</Badge>
              {chat.data.isPinned && <Badge>已置顶</Badge>}
              {chat.data.unreadCount ? <Badge>{chat.data.unreadCount} 未读</Badge> : null}
            </div>
          </header>
          {chat.data.primaryIssue && (
            <Link className="chat-linked-issue-card" to={`/orgs/${orgId}/issues/${chat.data.primaryIssue.id}`}>
              <div>
                <span>关联任务</span>
                <strong>{chat.data.primaryIssue.identifier ?? chat.data.primaryIssue.id.slice(0, 8)} · {chat.data.primaryIssue.title}</strong>
              </div>
              <Badge>{statusLabel(chat.data.primaryIssue.status)}</Badge>
            </Link>
          )}
          {chat.error && (
            <div className="error-notice">
              已打开本地缓存的对话，详情刷新失败：{chat.error instanceof Error ? chat.error.message : "请求失败"}
            </div>
          )}
          <div className="chat-messages" data-testid="chat-message-thread" ref={messageThreadRef}>
            {messages.isSuccess && visibleMessages.length === 0 && (
              <div className="chat-empty-thread">
                <h2>暂无消息</h2>
                <p className="muted">
                  {boundChatAgentName ? `向 ${boundChatAgentName} 发送第一条消息开始对话。` : "发送第一条消息开始对话。"}
                </p>
              </div>
            )}
            {visibleMessages.map((message) => {
              const issueProposal = issueProposalFromMessage(message);
              const issueCreatedEvent = issueCreatedEventFromMessage(message);
              return (
                <article className={`chat-message ${message.role}`} key={message.id}>
                  {message.role === "assistant" && (
                    <span aria-hidden="true" className="chat-agent-avatar">
                      {agentAvatarLabel(message.replyingAgentId ? agentNameById.get(message.replyingAgentId) : boundChatAgentName)}
                    </span>
                  )}
                  <div className="chat-message-body">
                    {message.role !== "user" && (
                      <strong>
                        {message.role === "assistant"
                          ? (message.replyingAgentId ? agentNameById.get(message.replyingAgentId) : boundChatAgentName) ?? "智能体"
                          : "系统"}
                      </strong>
                    )}
                    {message.role === "assistant" && (
                      <span className="chat-message-source">智能体回复，不代表任务产物</span>
                    )}
                    {(message.approvalId || (typeof message.turnVariant === "number" && message.turnVariant > 0)) && (
                      <div className="meta-line">
                        {message.approvalId && <Badge>审批 {message.approvalId}</Badge>}
                        {typeof message.turnVariant === "number" && message.turnVariant > 0 && <Badge>变体 {message.turnVariant}</Badge>}
                      </div>
                    )}
                    {!issueCreatedEvent && <p>{message.body}</p>}
                    {message.attachments && message.attachments.length > 0 && (
                      <div className="chat-attachment-list">
                        {message.attachments.map((attachment) => (
                          attachment.contentPath ? (
                            <a className="chat-attachment-chip" href={attachment.contentPath} key={attachment.id}>
                              {attachment.originalFilename ?? attachment.id}
                              <span>{formatBytes(attachment.byteSize)}</span>
                            </a>
                          ) : (
                            <span className="chat-attachment-chip disabled" key={attachment.id}>
                              {attachment.originalFilename ?? attachment.id}
                              <span>不可下载 · {formatBytes(attachment.byteSize)}</span>
                            </span>
                          )
                        ))}
                      </div>
                    )}
                    {issueCreatedEvent && (
                      <IssueCreatedCard
                        issueId={issueCreatedEvent.issueId}
                        issueIdentifier={issueCreatedEvent.issueIdentifier}
                        orgId={orgId}
                        primaryIssue={chat.data.primaryIssue}
                      />
                    )}
                    {message.structuredPayload && !issueCreatedEvent && (
                      <>
                        {issueProposal ? (
                          message.approvalId ? null : (
                            <IssueProposalCard
                              hasLinkedIssue={Boolean(chat.data.primaryIssue)}
                              messageId={message.id}
                              onCreate={(messageId) => convertIssue.mutate(messageId)}
                              pending={convertIssue.isPending}
                              proposal={issueProposal}
                            />
                          )
                        ) : null}
                        <pre className="json-block">{JSON.stringify(message.structuredPayload, null, 2)}</pre>
                      </>
                    )}
                  </div>
                </article>
              );
            })}
            {send.isPending && thinkingChatId === chatId && (
              <article aria-live="polite" className="chat-message assistant thinking">
                <span aria-hidden="true" className="chat-agent-avatar">{agentAvatarLabel(selectedAgentName)}</span>
                <div className="chat-message-body">
                  <strong>{selectedAgentName}</strong>
                  {streamingReply
                    ? <p>{streamingReply}</p>
                    : (
                        <p className="chat-thinking-text">
                          Thinking<span aria-hidden="true" className="thinking-dots"><span>.</span><span>.</span><span>.</span></span>
                        </p>
                      )}
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
          {approvalPrompt && (
            <ChatApprovalPrompt
              approvalId={approvalPrompt.approvalId}
              orgId={orgId}
              onDecide={(approvalId, action) => decideIssueProposal.mutate({ approvalId, action })}
              proposal={approvalPrompt.proposal}
              status={approvalPromptStatus ?? approvalPrompt.status}
              working={decideIssueProposal.isPending}
            />
          )}
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
              <label aria-label="当前任务创建模式">
                <select aria-label="任务创建模式" disabled value={chat.data?.issueCreationMode ?? "manual_approval"}>
                  <option value={chat.data?.issueCreationMode ?? "manual_approval"}>
                    {chatIssueCreationModeLabel(chat.data?.issueCreationMode)}
                  </option>
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

function IssueProposalCard({
  hasLinkedIssue,
  messageId,
  onCreate,
  pending,
  proposal,
}: {
  hasLinkedIssue: boolean;
  messageId: string;
  onCreate: (messageId: string) => void;
  pending: boolean;
  proposal: Record<string, unknown>;
}) {
  const title = proposalText(proposal.title) || "未命名任务";
  const description = proposalText(proposal.description);
  const priority = proposalText(proposal.priority) || "medium";
  return (
    <div className="chat-issue-proposal-card">
      <div>
        <span>任务提案</span>
        <strong>{title}</strong>
        {description && <p>{description}</p>}
        <small>优先级：{priority}</small>
      </div>
      <button disabled={hasLinkedIssue || pending} onClick={() => onCreate(messageId)} type="button">
        {hasLinkedIssue ? "已有关联任务" : pending ? "创建中..." : "创建任务"}
      </button>
    </div>
  );
}

function IssueCreatedCard({
  issueId,
  issueIdentifier,
  orgId,
  primaryIssue,
}: {
  issueId: string;
  issueIdentifier: string | null;
  orgId: string;
  primaryIssue: ChatConversation["primaryIssue"];
}) {
  const linkedIssue = primaryIssue?.id === issueId ? primaryIssue : null;
  const label = linkedIssue?.identifier ?? issueIdentifier ?? issueId.slice(0, 8);
  const title = linkedIssue?.title ?? "任务已创建";
  return (
    <Link className="chat-issue-created-card" to={`/orgs/${orgId}/issues/${issueId}`}>
      <div>
        <span>任务创建成功</span>
        <strong>{label} · {title}</strong>
      </div>
      <Badge>{linkedIssue ? statusLabel(linkedIssue.status) : "查看任务"}</Badge>
    </Link>
  );
}

function ChatApprovalPrompt({
  approvalId,
  onDecide,
  orgId,
  proposal,
  status,
  working,
}: {
  approvalId: string;
  onDecide: (approvalId: string, action: ChatApprovalPromptAction) => void;
  orgId: string;
  proposal: Record<string, unknown>;
  status: ChatApprovalPromptStatus;
  working: boolean;
}) {
  const title = proposalText(proposal.title) || "未命名任务";
  const description = proposalText(proposal.description);
  const pending = status === "pending";
  const approved = status === "approved";
  return (
    <div className="chat-approval-prompt" role="status">
      <div>
        <span className="chat-approval-prompt-heading">
          <span>{approved ? "任务创建结果同步中" : "任务创建待确认"}</span>
          <span className={`chat-approval-status ${status}`}>{chatApprovalStatusLabel(status)}</span>
        </span>
        <strong>{title}</strong>
        {approved ? <p>审批已同意，正在刷新任务创建结果。</p> : description && <p>{description}</p>}
      </div>
      {pending && (
        <div className="chat-approval-actions">
          <button disabled={working} onClick={() => onDecide(approvalId, "approve")} type="button">
            {working ? "处理中..." : "同意"}
          </button>
          <button className="danger" disabled={working} onClick={() => onDecide(approvalId, "reject")} type="button">
            拒绝
          </button>
          <button className="secondary" disabled={working} onClick={() => onDecide(approvalId, "requestRevision")} type="button">
            需修改
          </button>
        </div>
      )}
      {!pending && !approved && (
        <Link className="button secondary small-button" to={`/orgs/${orgId}/approvals/${approvalId}`}>
          查看审批
        </Link>
      )}
    </div>
  );
}
