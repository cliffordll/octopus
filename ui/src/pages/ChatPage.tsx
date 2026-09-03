import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { agentsApi } from "../api/agents";
import { approvalsApi } from "../api/approvals";
import { chatsApi } from "../api/chats";
import type { ChatConversation, ChatMessage } from "../api/types";
import { Badge } from "../components/Badge";
import { ChatComposerContextBar } from "../components/ChatComposerContextBar";
import { ChatsWorkspace } from "../components/ContextWorkspace";
import { ErrorNotice } from "../components/ErrorNotice";
import { TertiaryPageHeader, TertiaryPageShell, TertiaryPageViewport } from "../components/TertiaryPageShell";
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

function issueCreatedEventFromMessage(message: ChatMessage): { issueId: string; issueIdentifier: string | null; sourceMessageId: string | null } | null {
  if (message.kind !== "system_event" || message.structuredPayload?.eventType !== "issue_created") return null;
  const issueId = message.structuredPayload.issueId;
  if (typeof issueId !== "string" || !issueId) return null;
  const issueIdentifier = message.structuredPayload.issueIdentifier;
  const sourceMessageId = message.structuredPayload.sourceMessageId;
  return {
    issueId,
    issueIdentifier: typeof issueIdentifier === "string" && issueIdentifier ? issueIdentifier : null,
    sourceMessageId: typeof sourceMessageId === "string" && sourceMessageId ? sourceMessageId : null,
  };
}

function proposalText(value: unknown): string {
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

function issueProposalRequiresLabelSelection(proposal: Record<string, unknown>): boolean {
  if (proposal.requiresLabelSelection === true) return true;
  return Array.isArray(proposal.labelIds) && proposal.labelIds.length === 0;
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
type ChatLinkedIssueSummary = NonNullable<ChatConversation["primaryIssue"]> & {
  parentId?: string | null;
};

function chatApprovalStatusLabel(status: ChatApprovalPromptStatus): string {
  if (status === "revision_requested") return "已退回";
  if (status === "approved") return "已同意";
  if (status === "rejected") return "已拒绝";
  if (status === "cancelled") return "已取消";
  return "待审批";
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
  const [approvalPrompt, setApprovalPrompt] = useState<{
    approvalId: string;
    proposal: Record<string, unknown>;
    sourceMessageId: string;
    status: ChatApprovalPromptStatus;
  } | null>(null);
  const messageThreadRef = useRef<HTMLDivElement | null>(null);
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
  const createdIssueSourceMessageIds = useMemo(() => {
    const sourceMessageIds = new Set<string>();
    for (const message of visibleMessages) {
      const event = issueCreatedEventFromMessage(message);
      if (event?.sourceMessageId) sourceMessageIds.add(event.sourceMessageId);
    }
    return sourceMessageIds;
  }, [visibleMessages]);
  useEffect(() => {
    if (!orgId || !chatId || approvalPrompt) return;
    const proposalMessage = [...visibleMessages].reverse().find((message) =>
      Boolean(
        message.approvalId
        && issueProposalFromMessage(message),
      ),
    );
    if (!proposalMessage?.approvalId) return;
    const proposal = issueProposalFromMessage(proposalMessage);
    if (!proposal) return;
    setApprovalPrompt({
      approvalId: proposalMessage.approvalId,
      proposal,
      sourceMessageId: proposalMessage.id,
      status: "pending",
    });
  }, [approvalPrompt, chatId, orgId, visibleMessages]);
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
  const linkedIssues = useMemo(() => {
    const issueMap = new Map<string, ChatLinkedIssueSummary>();
    for (const link of chat.data?.contextLinks ?? []) {
      if (link.entityType !== "issue") continue;
      issueMap.set(link.entityId, {
        id: link.entityId,
        identifier: link.entity?.identifier ?? null,
        parentId: link.entity?.parentId ?? null,
        title: link.entity?.label ?? link.entityId,
        status: link.entity?.status ?? "open",
        priority: "",
      });
    }
    const primaryIssue = chat.data?.primaryIssue;
    if (primaryIssue) {
      issueMap.set(primaryIssue.id, {
        ...issueMap.get(primaryIssue.id),
        ...primaryIssue,
      });
    }
    return Array.from(issueMap.values());
  }, [chat.data?.contextLinks, chat.data?.primaryIssue]);
  const linkedIssueById = useMemo(() => new Map(linkedIssues.map((issue) => [issue.id, issue])), [linkedIssues]);
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
    onSuccess: ({ issue, systemMessage }) => {
      queryClient.setQueryData(["issue", issue.id], issue);
      queryClient.setQueryData<ChatMessage[]>(["chat-messages", chatId], (current = []) => {
        const next = new Map(current.map((message) => [message.id, message]));
        next.set(systemMessage.id, systemMessage);
        return Array.from(next.values());
      });
      void queryClient.invalidateQueries({ queryKey: ["chat", chatId] });
      void queryClient.invalidateQueries({ queryKey: ["chats", orgId] });
      void queryClient.invalidateQueries({ queryKey: ["issues", orgId] });
      void queryClient.invalidateQueries({ queryKey: ["issue", issue.id] });
    },
    onError: (error) => {
      setSendNotice(displayError(error));
    },
  });
  const updatePlanMode = useMutation({
    mutationFn: (planMode: boolean) => chatsApi.update(chatId, { planMode }),
    onSuccess: (updatedChat) => {
      queryClient.setQueryData(["chat", chatId], updatedChat);
      void queryClient.invalidateQueries({ queryKey: ["chats", orgId] });
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
        return { ...current, status: nextStatus };
      });
      void queryClient.invalidateQueries({ queryKey: ["approval", approval.id] });
      void queryClient.invalidateQueries({ queryKey: ["approval-issues", approval.id] });
      void queryClient.invalidateQueries({ queryKey: ["messenger-approvals", orgId] });
      void queryClient.invalidateQueries({ queryKey: ["approvals", orgId] });
      void queryClient.invalidateQueries({ queryKey: ["chat", chatId] });
      void queryClient.invalidateQueries({ queryKey: ["chat-messages", chatId] });
      void queryClient.invalidateQueries({ queryKey: ["chats", orgId] });
      void queryClient.invalidateQueries({ queryKey: ["issues", orgId] });
      void queryClient.invalidateQueries({ queryKey: ["issue"] });
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
        <TertiaryPageShell className="chat-thread-shell">
          <TertiaryPageHeader
            eyebrow="Conversation"
            supporting={<>
              <span>{boundChatAgentName ? `使用 ${boundChatAgentName}` : "选择智能体后发送消息"}</span>
              <Badge>{statusLabel(chat.data.status)}</Badge>
              {chat.data.isPinned && <Badge>已置顶</Badge>}
              {chat.data.unreadCount ? <Badge>{chat.data.unreadCount} 未读</Badge> : null}
            </>}
            title={chat.data.title}
          />
          <TertiaryPageViewport className="chat-thread-content tertiary-page-viewport-contained">
          {linkedIssues.length > 0 && (
            <div aria-label="关联任务" className="chat-linked-issues-strip">
              {linkedIssues.map((issue) => (
                <Link className="chat-linked-issue-card" key={issue.id} to={`/orgs/${orgId}/issues/${issue.id}`}>
                  <div>
                    <span>{issue.parentId ? "子任务" : "关联任务"}</span>
                    <strong>{issue.identifier ?? issue.id.slice(0, 8)} · {issue.title}</strong>
                  </div>
                  <Badge>{statusLabel(issue.status)}</Badge>
                </Link>
              ))}
            </div>
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
                <Fragment key={message.id}>
                <article className={`chat-message ${message.role}`}>
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
                    {typeof message.turnVariant === "number" && message.turnVariant > 0 && (
                      <div className="meta-line">
                        <Badge>变体 {message.turnVariant}</Badge>
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
                        linkedIssue={linkedIssueById.get(issueCreatedEvent.issueId) ?? null}
                        orgId={orgId}
                      />
                    )}
                    {message.structuredPayload && !issueCreatedEvent && (
                      <>
                        {issueProposal ? (
                          message.approvalId ? null : (
                            <IssueProposalCard
                              hasCreatedIssue={createdIssueSourceMessageIds.has(message.id)}
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
                {approvalPrompt?.sourceMessageId === message.id && (
                  <article className="chat-message system chat-approval-system-message">
                    <strong>系统</strong>
                    <ChatApprovalPrompt
                      approvalId={approvalPrompt.approvalId}
                      decisionNote={approvalPromptDetail.data?.decisionNote ?? null}
                      hasCreatedIssue={createdIssueSourceMessageIds.has(approvalPrompt.sourceMessageId)}
                      orgId={orgId}
                      onDecide={(approvalId, action) => decideIssueProposal.mutate({ approvalId, action })}
                      proposal={approvalPrompt.proposal}
                      status={approvalPromptStatus ?? approvalPrompt.status}
                      working={decideIssueProposal.isPending}
                    />
                  </article>
                )}
                </Fragment>
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
          {messages.error && <ErrorNotice error={messages.error} />}
          <form aria-label="发送消息" className="form chat-composer" onSubmit={submit}>
            <label className="chat-message-input">
              <textarea
                aria-label="消息输入"
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
            {updatePlanMode.error && <ErrorNotice error={updatePlanMode.error} />}
            <ChatComposerContextBar
              agentControl={(
                <select aria-label="对话智能体" disabled value={agentId}>
                  <option value={agentId}>{selectedAgentControlLabel}</option>
                </select>
              )}
              issueCreationModeControl={(
                <select aria-label="任务创建模式" disabled value={chat.data?.issueCreationMode ?? "manual_approval"}>
                  <option value={chat.data?.issueCreationMode ?? "manual_approval"}>
                    {chatIssueCreationModeLabel(chat.data?.issueCreationMode)}
                  </option>
                </select>
              )}
              locked
              planMode={{
                checked: Boolean(chat.data?.planMode),
                disabled: updatePlanMode.isPending,
                onChange: (checked) => updatePlanMode.mutate(checked),
              }}
              projectControl={(
                <select aria-label="项目" disabled value={projectContext?.entityId ?? ""}>
                  <option value={projectContext?.entityId ?? ""}>
                    {projectContext?.entity?.label ?? (projectContext ? projectContext.entityId : "未关联项目")}
                  </option>
                </select>
              )}
              skills={[
                ...desiredSkills.map((label) => ({ active: true, label })),
                ...skillEntries.map((entry) => ({ label: skillLabel(entry) })),
              ]}
              skillsEmptyText={agentId && selectedAgentSkills.isSuccess ? "暂无技能" : "未选择智能体"}
              submitDisabled={!agentId || selectedChatAgentUnavailable || send.isPending}
              submitLabel="发送"
            />
          </form>
          </TertiaryPageViewport>
        </TertiaryPageShell>
      )}
    </ChatsWorkspace>
  );
}

function IssueProposalCard({
  hasCreatedIssue,
  messageId,
  onCreate,
  pending,
  proposal,
}: {
  hasCreatedIssue: boolean;
  messageId: string;
  onCreate: (messageId: string) => void;
  pending: boolean;
  proposal: Record<string, unknown>;
}) {
  const title = proposalText(proposal.title) || "未命名任务";
  const description = proposalText(proposal.description);
  const priority = proposalText(proposal.priority) || "medium";
  const requiresLabelSelection = issueProposalRequiresLabelSelection(proposal);
  return (
    <div className="chat-issue-proposal-card">
      <div>
        <span>任务提案</span>
        <strong>{title}</strong>
        {description && <p>{description}</p>}
        <small>优先级：{priority}</small>
        {requiresLabelSelection && <small>需要人工选择标签，审批后创建任务。</small>}
      </div>
      <button disabled={hasCreatedIssue || pending} onClick={() => onCreate(messageId)} type="button">
        {hasCreatedIssue ? "任务已创建" : pending ? "创建中..." : "创建任务"}
      </button>
    </div>
  );
}

function IssueCreatedCard({
  issueId,
  issueIdentifier,
  linkedIssue,
  orgId,
}: {
  issueId: string;
  issueIdentifier: string | null;
  linkedIssue: ChatLinkedIssueSummary | null;
  orgId: string;
}) {
  const label = linkedIssue?.identifier ?? issueIdentifier ?? issueId.slice(0, 8);
  const title = linkedIssue?.title ?? "任务已创建";
  return (
    <ChatSystemEventCard
      actions={<span className="chat-system-event-detail-link">任务详情</span>}
      eyebrow="任务创建成功"
      status={<Badge>{linkedIssue ? statusLabel(linkedIssue.status) : "查看任务"}</Badge>}
      title={`${label} · ${title}`}
      to={`/orgs/${orgId}/issues/${issueId}`}
    />
  );
}

function ChatSystemEventCard({
  actions,
  detail,
  detailLabel,
  eyebrow,
  linkLabel,
  status,
  title,
  to,
}: {
  actions?: ReactNode;
  detail?: string;
  detailLabel?: string;
  eyebrow: string;
  linkLabel?: string;
  status: ReactNode;
  title: string;
  to?: string;
}) {
  const content = (
    <>
      <span className="chat-system-event-eyebrow">{eyebrow}</span>
      <div className="chat-system-event-status">{status}</div>
      <div className="chat-system-event-main">
        <strong>{title}</strong>
        {detail && (
          <span className="chat-system-event-detail">
            {detailLabel && <span>{detailLabel}</span>}
            <span title={detail}>{detail}</span>
          </span>
        )}
      </div>
      <div className="chat-system-event-actions">{actions}</div>
    </>
  );
  return to ? (
    <Link aria-label={linkLabel} className="chat-system-event-card" to={to}>{content}</Link>
  ) : (
    <div className="chat-system-event-card" role="status">{content}</div>
  );
}

function ChatApprovalPrompt({
  approvalId,
  decisionNote,
  hasCreatedIssue,
  onDecide,
  orgId,
  proposal,
  status,
  working,
}: {
  approvalId: string;
  decisionNote: string | null;
  hasCreatedIssue: boolean;
  onDecide: (approvalId: string, action: ChatApprovalPromptAction) => void;
  orgId: string;
  proposal: Record<string, unknown>;
  status: ChatApprovalPromptStatus;
  working: boolean;
}) {
  const title = proposalText(proposal.title) || "未命名任务";
  const pending = status === "pending";
  const approved = status === "approved";
  const resolved = !pending;
  const approvedSyncing = approved && !hasCreatedIssue;
  const statusBadge = <span className={`chat-approval-status ${status}`}>{chatApprovalStatusLabel(status)}</span>;
  const actions = pending ? (
    <div className="chat-approval-actions">
      <button disabled={working} onClick={() => onDecide(approvalId, "approve")} type="button">
        {working ? "处理中..." : "同意"}
      </button>
      <button className="danger" disabled={working} onClick={() => onDecide(approvalId, "reject")} type="button">
        拒绝
      </button>
      <button className="secondary" disabled={working} onClick={() => onDecide(approvalId, "requestRevision")} type="button">
        退回
      </button>
      <Link className="chat-system-event-detail-link" to={`/orgs/${orgId}/approvals/${approvalId}`}>
        审批详情
      </Link>
    </div>
  ) : (
    <span className="chat-system-event-detail-link">审批详情</span>
  );
  return (
    <ChatSystemEventCard
      actions={actions}
      detail={approvedSyncing
        ? "审批已同意，正在刷新任务创建结果。"
        : resolved
          ? decisionNote?.trim() || "审批人未填写审核意见。"
          : undefined}
      detailLabel={resolved && !approvedSyncing ? "审核意见" : undefined}
      eyebrow={approvedSyncing ? "任务创建结果同步中" : resolved ? "审批结果" : "任务创建待确认"}
      linkLabel={!pending ? `审批详情：${title}` : undefined}
      status={statusBadge}
      title={title}
      to={!pending ? `/orgs/${orgId}/approvals/${approvalId}` : undefined}
    />
  );
}
