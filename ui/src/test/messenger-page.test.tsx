import { cleanup, screen, within } from "@testing-library/react";
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
      return respond({
        summary: { threadKey: "issues", kind: "issues", lastReadAt: null, unreadCount: 1, needsAttention: true },
        detail: {
          description: "任务消息",
          items: [{
            id: "issue-1",
            title: "修复部署脚本",
            preview: "处理部署失败问题",
            href: "/issues/OCT-1",
            latestActivityAt: "2026-05-29T01:00:00",
          }],
        },
      });
    }
    if (path === "/api/orgs/org-1/messenger/approvals" && init?.method === "GET") {
      return respond({
        summary: { threadKey: "approvals", kind: "approvals", lastReadAt: null, unreadCount: 1, needsAttention: true },
        detail: {
          description: "审批消息",
          items: [{
            id: "approval-1",
            title: "审批发布计划",
            preview: "等待确认发布窗口",
            latestActivityAt: "2026-05-29T02:00:00",
            approval: { id: "approval-1" },
          }],
        },
      });
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
  const pageHeader = screen.getByRole("heading", { name: "消息中心" }).closest("header")!;
  expect(within(pageHeader).getByText("集中处理对话、任务、审批和系统提醒。")).toHaveClass("tertiary-page-supporting");
  expect(await screen.findByText("部署讨论")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "部署讨论" })).toHaveAttribute("href", "/orgs/org-1/chats/chat-1");
  expect(screen.getByRole("link", { name: "修复部署脚本" })).toHaveAttribute("href", "/orgs/org-1/issues/OCT-1");
  expect(screen.getByRole("link", { name: "审批发布计划" })).toHaveAttribute("href", "/orgs/org-1/approvals/approval-1");
  expect(screen.queryByRole("heading", { name: "线程" })).not.toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "聚合线程" })).not.toBeInTheDocument();

  const filters = screen.getByRole("group", { name: "消息筛选" });
  await userEvent.click(within(filters).getByRole("button", { name: /审批/ }));
  expect(screen.getByRole("link", { name: "审批发布计划" })).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "部署讨论" })).not.toBeInTheDocument();
  await userEvent.click(within(filters).getByRole("button", { name: "全部" }));

  const chatRow = screen.getByRole("link", { name: "部署讨论" }).closest("article")!;
  expect(within(chatRow).getByText("对话")).toHaveAttribute("data-kind", "chat");
  await userEvent.click(within(chatRow).getByRole("button", { name: "标记已读" }));

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/messenger/threads/chat%3Achat-1/read",
    expect.objectContaining({ method: "POST", body: JSON.stringify({}) }),
  );
});
