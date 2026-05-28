import { jsonRequest, request } from "./client";
import type { ChatConversation, ChatMessage } from "./types";

export const chatsApi = {
  list: (orgId: string): Promise<ChatConversation[]> =>
    request<ChatConversation[]>(`/api/orgs/${encodeURIComponent(orgId)}/chats`, { method: "GET" }),
  get: (chatId: string): Promise<ChatConversation> =>
    request<ChatConversation>(`/api/chats/${encodeURIComponent(chatId)}`, { method: "GET" }),
  create: (
    orgId: string,
    payload: { title: string; preferredAgentId?: string | null },
  ): Promise<ChatConversation> =>
    jsonRequest<ChatConversation>(`/api/orgs/${encodeURIComponent(orgId)}/chats`, "POST", payload),
  listMessages: (chatId: string): Promise<ChatMessage[]> =>
    request<ChatMessage[]>(`/api/chats/${encodeURIComponent(chatId)}/messages`, { method: "GET" }),
  addMessage: (chatId: string, payload: { body: string }): Promise<{ messages: ChatMessage[] }> =>
    jsonRequest<{ messages: ChatMessage[] }>(
      `/api/chats/${encodeURIComponent(chatId)}/messages`,
      "POST",
      payload,
    ),
};
