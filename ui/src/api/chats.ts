import { jsonRequest, request, rootCauseMessage } from "./client";
import type { ChatAttachment, ChatContextLink, ChatConversation, ChatMessage, IssueDetail } from "./types";

export interface ChatListFilters {
  status?: ChatConversation["status"];
  q?: string;
}

export type ChatStreamEvent =
  | { type: "ack"; userMessage: ChatMessage }
  | { type: "assistant_delta"; delta: string; messageId?: string | null }
  | { type: "final"; messages: ChatMessage[] }
  | { type: "error"; error: string; messageId?: string | null }
  | { type: string; [key: string]: unknown };

function isFinalStreamEvent(event: ChatStreamEvent): event is Extract<ChatStreamEvent, { type: "final" }> {
  return event.type === "final" && Array.isArray(event.messages);
}

function isErrorStreamEvent(event: ChatStreamEvent): event is Extract<ChatStreamEvent, { type: "error" }> {
  return event.type === "error" && typeof event.error === "string";
}

async function parseStreamError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return rootCauseMessage(body.detail);
  } catch {
    // Fall through to the HTTP status when a non-JSON error is returned.
  }
  return `Request failed (${response.status})`;
}

async function readChatMessageStream(
  response: Response,
  onEvent?: (event: ChatStreamEvent) => void,
): Promise<{ messages: ChatMessage[] }> {
  if (!response.body) {
    const text = await response.text();
    const events = text.split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line) as ChatStreamEvent);
    for (const event of events) onEvent?.(event);
    const final = events.find(isFinalStreamEvent);
    if (final) return { messages: final.messages };
    const error = events.find(isErrorStreamEvent);
    throw new Error(error?.error ?? "Chat stream ended without a final response");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalMessages: ChatMessage[] | null = null;
  let streamError: string | null = null;

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const lines = buffer.split(/\r?\n/);
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (!line.trim()) continue;
      const event = JSON.parse(line) as ChatStreamEvent;
      onEvent?.(event);
      if (isFinalStreamEvent(event)) finalMessages = event.messages;
      if (isErrorStreamEvent(event)) streamError = event.error;
    }
    if (done) break;
  }
  if (buffer.trim()) {
    const event = JSON.parse(buffer) as ChatStreamEvent;
    onEvent?.(event);
    if (isFinalStreamEvent(event)) finalMessages = event.messages;
    if (isErrorStreamEvent(event)) streamError = event.error;
  }
  if (streamError) throw new Error(rootCauseMessage(streamError));
  if (!finalMessages) throw new Error("Chat stream ended without a final response");
  return { messages: finalMessages };
}

export const chatsApi = {
  list: (orgId: string, filters: ChatListFilters = {}): Promise<ChatConversation[]> => {
    const params = new URLSearchParams();
    if (filters.status) params.set("status", filters.status);
    if (filters.q) params.set("q", filters.q);
    const query = params.toString();
    return request<ChatConversation[]>(
      `/api/orgs/${encodeURIComponent(orgId)}/chats${query ? `?${query}` : ""}`,
      { method: "GET" },
    );
  },
  get: (chatId: string): Promise<ChatConversation> =>
    request<ChatConversation>(`/api/chats/${encodeURIComponent(chatId)}`, { method: "GET" }),
  create: (
    orgId: string,
    payload: {
      title: string;
      summary?: string | null;
      preferredAgentId?: string | null;
      issueCreationMode?: "manual_approval" | "auto_create";
      planMode?: boolean;
      contextLinks?: Array<{ entityType: string; entityId: string; metadata?: Record<string, unknown> | null }>;
    },
  ): Promise<ChatConversation> =>
    jsonRequest<ChatConversation>(`/api/orgs/${encodeURIComponent(orgId)}/chats`, "POST", payload),
  update: (
    chatId: string,
    payload: Partial<Pick<ChatConversation, "title" | "summary" | "preferredAgentId" | "status" | "issueCreationMode" | "planMode" | "primaryIssueId">>,
  ): Promise<ChatConversation> =>
    jsonRequest<ChatConversation>(`/api/chats/${encodeURIComponent(chatId)}`, "PATCH", payload),
  updateUserState: (chatId: string, payload: { pinned?: boolean; unread?: boolean }): Promise<ChatConversation> =>
    jsonRequest<ChatConversation>(`/api/chats/${encodeURIComponent(chatId)}/user-state`, "PATCH", payload),
  addContextLink: (
    chatId: string,
    payload: { entityType: string; entityId: string; metadata?: Record<string, unknown> | null },
  ): Promise<ChatContextLink> =>
    jsonRequest<ChatContextLink>(`/api/chats/${encodeURIComponent(chatId)}/context-links`, "POST", payload),
  setProjectContext: (chatId: string, projectId: string | null): Promise<ChatConversation> =>
    jsonRequest<ChatConversation>(`/api/chats/${encodeURIComponent(chatId)}/project-context`, "POST", { projectId }),
  listMessages: (chatId: string): Promise<ChatMessage[]> =>
    request<ChatMessage[]>(`/api/chats/${encodeURIComponent(chatId)}/messages`, { method: "GET" }),
  addMessage: (chatId: string, payload: { body: string; editUserMessageId?: string | null }): Promise<{ messages: ChatMessage[] }> =>
    jsonRequest<{ messages: ChatMessage[] }>(
      `/api/chats/${encodeURIComponent(chatId)}/messages`,
      "POST",
      payload,
    ),
  addMessageStream: async (
    chatId: string,
    payload: { body: string; editUserMessageId?: string | null },
    onEvent?: (event: ChatStreamEvent) => void,
  ): Promise<{ messages: ChatMessage[] }> => {
    const response = await fetch(`/api/chats/${encodeURIComponent(chatId)}/messages/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) throw new Error(await parseStreamError(response));
    return readChatMessageStream(response, onEvent);
  },
  uploadAttachment: (
    orgId: string,
    chatId: string,
    payload: { file: File; messageId: string },
  ): Promise<ChatAttachment> => {
    const form = new FormData();
    form.set("messageId", payload.messageId);
    form.set("file", payload.file);
    return request<ChatAttachment>(
      `/api/orgs/${encodeURIComponent(orgId)}/chats/${encodeURIComponent(chatId)}/attachments`,
      { method: "POST", body: form },
    );
  },
  convertToIssue: (
    chatId: string,
    payload: { messageId?: string | null; proposal?: Record<string, unknown> | null },
  ): Promise<{ issue: IssueDetail; systemMessage: ChatMessage }> =>
    jsonRequest<{ issue: IssueDetail; systemMessage: ChatMessage }>(`/api/chats/${encodeURIComponent(chatId)}/convert-to-issue`, "POST", payload),
  resolveOperationProposal: (
    chatId: string,
    messageId: string,
    payload: { action: "approve" | "reject" | "requestRevision"; decisionNote?: string | null },
  ): Promise<Record<string, unknown>> =>
    jsonRequest<Record<string, unknown>>(
      `/api/chats/${encodeURIComponent(chatId)}/messages/${encodeURIComponent(messageId)}/operation-proposal/resolve`,
      "POST",
      payload,
    ),
  stopStream: (chatId: string): Promise<{ stopped: boolean }> =>
    jsonRequest<{ stopped: boolean }>(`/api/chats/${encodeURIComponent(chatId)}/messages/stream/stop`, "POST", {}),
};
