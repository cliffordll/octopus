import { jsonRequest, request } from "./client";
import type { MessengerChatThreadDetail, MessengerThreadBundle, MessengerThreadSummary } from "./types";

export const messengerApi = {
  threads: (orgId: string): Promise<MessengerThreadSummary[]> =>
    request<MessengerThreadSummary[]>(`/api/orgs/${encodeURIComponent(orgId)}/messenger/threads`, { method: "GET" }),
  chat: (orgId: string, conversationId: string): Promise<MessengerChatThreadDetail> =>
    request<MessengerChatThreadDetail>(
      `/api/orgs/${encodeURIComponent(orgId)}/messenger/chat/${encodeURIComponent(conversationId)}`,
      { method: "GET" },
    ),
  read: (orgId: string, threadKey: string, lastReadAt?: string): Promise<{ threadKey: string; lastReadAt: string }> =>
    jsonRequest<{ threadKey: string; lastReadAt: string }>(
      `/api/orgs/${encodeURIComponent(orgId)}/messenger/threads/${encodeURIComponent(threadKey)}/read`,
      "POST",
      lastReadAt ? { lastReadAt } : {},
    ),
  issues: (orgId: string): Promise<MessengerThreadBundle> =>
    request<MessengerThreadBundle>(`/api/orgs/${encodeURIComponent(orgId)}/messenger/issues`, { method: "GET" }),
  approvals: (orgId: string): Promise<MessengerThreadBundle> =>
    request<MessengerThreadBundle>(`/api/orgs/${encodeURIComponent(orgId)}/messenger/approvals`, { method: "GET" }),
  system: (orgId: string, threadKind: string): Promise<MessengerThreadBundle> =>
    request<MessengerThreadBundle>(
      `/api/orgs/${encodeURIComponent(orgId)}/messenger/system/${encodeURIComponent(threadKind)}`,
      { method: "GET" },
    ),
};
