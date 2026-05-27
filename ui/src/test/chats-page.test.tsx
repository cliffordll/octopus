import { cleanup, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { renderApp, respond } from "./render-app";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("shows a composer and sends a first message through a selected agent", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/chats" && init?.method === "GET") {
      return respond([]);
    }
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") {
      return respond([{ id: "agent-1", name: "Builder", role: "engineer" }]);
    }
    if (path === "/api/orgs" && init?.method === "GET") {
      return respond([{ id: "org-1", urlKey: "core", name: "核心团队", status: "active" }]);
    }
    if (path === "/api/chats/chat-2" && init?.method === "GET") {
      return respond({ id: "chat-2", title: "部署讨论", status: "active", preferredAgentId: "agent-1" });
    }
    if (path === "/api/chats/chat-2/messages" && init?.method === "GET") {
      return respond([]);
    }
    if (path === "/api/orgs/org-1/chats" && init?.method === "POST") {
      return respond({ id: "chat-2", title: "部署讨论", status: "active", preferredAgentId: "agent-1" }, 201);
    }
    return respond({ messages: [] }, 201);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/chats");
  expect(await screen.findByRole("option", { name: "Builder (engineer)" })).toBeInTheDocument();
  expect(screen.queryByRole("navigation", { name: "组织导航" })).not.toBeInTheDocument();
  expect(screen.getByRole("navigation", { name: "消息导航" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /新建对话/ })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "开始新的对话" })).toBeInTheDocument();
  expect(screen.getByLabelText("消息")).toBeInTheDocument();

  await userEvent.type(screen.getByLabelText("标题（可选）"), "部署讨论");
  await userEvent.selectOptions(screen.getByLabelText("对话智能体"), "agent-1");
  await userEvent.type(screen.getByLabelText("消息"), "请规划部署");
  await userEvent.click(screen.getByRole("button", { name: "发送并创建对话" }));

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/chats",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ title: "部署讨论", preferredAgentId: "agent-1" }),
    }),
  );
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/chats/chat-2/messages",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ body: "请规划部署" }),
    }),
  );
  expect(await screen.findByRole("heading", { name: "部署讨论" })).toBeInTheDocument();
});

it("filters conversations and identifies their selected agent", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/chats" && init?.method === "GET") {
      return respond([
        { id: "chat-1", title: "发布计划", status: "active", preferredAgentId: "agent-1" },
        { id: "chat-2", title: "归档调研", status: "archived", preferredAgentId: null },
      ]);
    }
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") {
      return respond([{ id: "agent-1", name: "Builder", role: "engineer" }]);
    }
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/chats");
  const messageNavigation = screen.getByRole("navigation", { name: "消息导航" });
  expect(await screen.findByText("Builder")).toBeInTheDocument();
  expect(messageNavigation).toHaveTextContent("归档调研");

  await userEvent.selectOptions(screen.getByLabelText("状态"), "active");
  expect(messageNavigation).not.toHaveTextContent("归档调研");

  await userEvent.type(screen.getByLabelText("搜索对话"), "没有");
  expect(screen.getByText("没有匹配的对话")).toBeInTheDocument();
});

it("creates a chat and sends messages to its selected agent", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/chats" && init?.method === "GET") {
      return respond([{ id: "chat-1", title: "支持会话", status: "active" }]);
    }
    if (path === "/api/chats/chat-1" && init?.method === "GET") {
      return respond({ id: "chat-1", orgId: "org-1", title: "支持会话", status: "active" });
    }
    if (path === "/api/chats/chat-1/messages" && init?.method === "GET") {
      return respond([{ id: "message-1", role: "assistant", body: "已有回复", status: "completed" }]);
    }
    return respond({ messages: [{ id: "message-2", body: "新回复" }] }, 201);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/chats/chat-1");
  expect(await screen.findByRole("heading", { name: "支持会话" })).toBeInTheDocument();
  expect(await screen.findByText("已有回复")).toBeInTheDocument();

  await userEvent.type(screen.getByLabelText("消息"), "现在状态？");
  await userEvent.click(screen.getByRole("button", { name: "发送" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/chats/chat-1/messages",
    expect.objectContaining({ method: "POST", body: JSON.stringify({ body: "现在状态？" }) }),
  );
});
