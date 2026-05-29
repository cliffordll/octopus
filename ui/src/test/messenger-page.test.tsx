import { cleanup, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { renderApp, respond } from "./render-app";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("shows messenger threads and marks a chat thread read", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs" && init?.method === "GET") {
      return respond([{ id: "org-1", urlKey: "core", name: "核心团队", status: "active" }]);
    }
    if (path === "/api/orgs/org-1/chats" && init?.method === "GET") return respond([]);
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") return respond([]);
    if (path === "/api/orgs/org-1/messenger/threads" && init?.method === "GET") {
      return respond([
        {
          threadKey: "chat:chat-1",
          kind: "chat",
          title: "部署讨论",
          subtitle: "Builder",
          preview: "需要确认窗口",
          latestActivityAt: "2026-05-29T00:00:00",
          lastReadAt: null,
          unreadCount: 2,
          needsAttention: true,
          isPinned: false,
          href: "/OCT/messenger/chats/chat-1",
        },
      ]);
    }
    if (path === "/api/orgs/org-1/messenger/issues" && init?.method === "GET") {
      return respond({ summary: { unreadCount: 0, needsAttention: false, preview: null }, detail: { description: "任务消息", items: [] } });
    }
    if (path === "/api/orgs/org-1/messenger/approvals" && init?.method === "GET") {
      return respond({ summary: { unreadCount: 1, needsAttention: true, preview: "审批待处理" }, detail: { description: "审批消息", items: [] } });
    }
    if (path.startsWith("/api/orgs/org-1/messenger/system/") && init?.method === "GET") {
      return respond({ summary: { unreadCount: 0, needsAttention: false, preview: null }, detail: { description: "系统消息", items: [] } });
    }
    if (path === "/api/orgs/org-1/messenger/threads/chat%3Achat-1/read" && init?.method === "POST") {
      return respond({ threadKey: "chat:chat-1", lastReadAt: "2026-05-29T00:00:00" });
    }
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/messenger");
  expect(await screen.findByRole("heading", { name: "消息中心" })).toBeInTheDocument();
  expect(await screen.findByText("部署讨论")).toBeInTheDocument();
  expect(screen.getByText("2 未读")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "打开对话" })).toHaveAttribute("href", "/orgs/org-1/chats/chat-1");

  await userEvent.click(screen.getByRole("button", { name: "标记已读" }));

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/messenger/threads/chat%3Achat-1/read",
    expect.objectContaining({ method: "POST", body: JSON.stringify({}) }),
  );
});
