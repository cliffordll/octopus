import { jsonRequest, request } from "./client";
import type { ChatContextLink, ChatConversation, ChatMessage } from "./types";

export interface ChatListFilters {
  status?: ChatConversation["status"];
  q?: string;
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
  convertToIssue: (
    chatId: string,
    payload: { messageId?: string | null; proposal?: Record<string, unknown> | null },
  ): Promise<Record<string, unknown>> =>
    jsonRequest<Record<string, unknown>>(`/api/chats/${encodeURIComponent(chatId)}/convert-to-issue`, "POST", payload),
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
