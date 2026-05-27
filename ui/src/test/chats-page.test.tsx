import { cleanup, screen, within } from "@testing-library/react";
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
      return respond([{ id: "agent-1", name: "Builder", role: "engineer", status: "idle", agentRuntimeType: "codex_local" }]);
    }
    if (path === "/api/orgs" && init?.method === "GET") {
      return respond([{ id: "org-1", urlKey: "core", name: "核心团队", status: "active" }]);
    }
    if (path === "/api/chats/chat-2" && init?.method === "GET") {
      return respond({ id: "chat-2", title: "请规划部署", status: "active", preferredAgentId: "agent-1" });
    }
    if (path === "/api/chats/chat-2/messages" && init?.method === "GET") {
      return respond([]);
    }
    if (path === "/api/orgs/org-1/chats" && init?.method === "POST") {
      return respond({ id: "chat-2", title: "请规划部署", status: "active", preferredAgentId: "agent-1" }, 201);
    }
    if (path === "/api/chats/chat-2/messages" && init?.method === "POST") {
      return respond({
        messages: [
          { id: "message-1", role: "user", body: "请规划部署", status: "completed" },
          { id: "message-2", role: "assistant", body: "已收到部署请求", status: "completed" },
        ],
      }, 201);
    }
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/chats");
  expect(await screen.findByRole("option", { name: "Builder (engineer)" })).toBeInTheDocument();
  expect(screen.queryByRole("navigation", { name: "组织导航" })).not.toBeInTheDocument();
  expect(screen.getByRole("navigation", { name: "消息导航" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /新建对话/ })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "开始新的对话" })).toBeInTheDocument();
  expect(screen.queryByLabelText("标题（可选）")).not.toBeInTheDocument();
  expect(screen.getByLabelText("消息")).toBeInTheDocument();
  expect(screen.queryByText("对话智能体")).not.toBeInTheDocument();
  expect(screen.getByLabelText("对话智能体").closest(".chat-compose-actions")).toContainElement(
    screen.getByRole("button", { name: "发送并创建对话" }),
  );

  await userEvent.selectOptions(screen.getByLabelText("对话智能体"), "agent-1");
  await userEvent.type(screen.getByLabelText("消息"), "请规划部署");
  await userEvent.click(screen.getByRole("button", { name: "发送并创建对话" }));

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/chats",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ title: "请规划部署", preferredAgentId: "agent-1" }),
    }),
  );
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/chats/chat-2/messages",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ body: "请规划部署" }),
    }),
  );
  expect(await screen.findByRole("heading", { name: "请规划部署" })).toBeInTheDocument();
  expect(await screen.findByText("已收到部署请求")).toBeInTheDocument();
});

it("creates a conversation by pressing Enter while Shift+Enter keeps a line break", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/chats" && init?.method === "GET") {
      return respond([]);
    }
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") {
      return respond([{ id: "agent-1", name: "Builder", role: "engineer", status: "idle", agentRuntimeType: "codex_local" }]);
    }
    if (path === "/api/orgs/org-1/chats" && init?.method === "POST") {
      return respond({ id: "chat-2", title: "第一行 第二行", status: "active", preferredAgentId: "agent-1" }, 201);
    }
    if (path === "/api/chats/chat-2/messages" && init?.method === "POST") {
      return respond({ messages: [] }, 201);
    }
    if (path === "/api/chats/chat-2" && init?.method === "GET") {
      return respond({ id: "chat-2", title: "第一行 第二行", status: "active", preferredAgentId: "agent-1" });
    }
    if (path === "/api/chats/chat-2/messages" && init?.method === "GET") {
      return respond([]);
    }
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/chats");
  await screen.findByRole("option", { name: "Builder (engineer)" });
  await userEvent.selectOptions(screen.getByLabelText("对话智能体"), "agent-1");
  await userEvent.type(screen.getByLabelText("消息"), "第一行{Shift>}{Enter}{/Shift}第二行");

  expect(screen.getByLabelText("消息")).toHaveValue("第一行\n第二行");
  expect(fetchMock).not.toHaveBeenCalledWith("/api/orgs/org-1/chats", expect.objectContaining({ method: "POST" }));

  await userEvent.keyboard("{Enter}");

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/chats",
    expect.objectContaining({ method: "POST", body: JSON.stringify({ title: "第一行\n第二行", preferredAgentId: "agent-1" }) }),
  );
});

it("only offers chat-capable agents for a new conversation", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/chats" && init?.method === "GET") {
      return respond([]);
    }
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") {
      return respond([
        { id: "agent-1", name: "Runner", role: "engineer", status: "idle", agentRuntimeType: "process" },
        { id: "agent-2", name: "Builder", role: "engineer", status: "idle", agentRuntimeType: "codex_local" },
      ]);
    }
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/chats");
  expect(await screen.findByRole("option", { name: "Builder (engineer)" })).toBeInTheDocument();
  expect(screen.queryByRole("option", { name: "Runner (engineer)" })).not.toBeInTheDocument();
});

it("keeps a link to the conversation when the first reply request fails", async () => {
  let conversationCreated = false;
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/chats" && init?.method === "GET") {
      return respond(conversationCreated
        ? [{ id: "chat-2", title: "请规划部署", status: "active", preferredAgentId: "agent-1" }]
        : []);
    }
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") {
      return respond([{ id: "agent-1", name: "Builder", role: "engineer", status: "idle", agentRuntimeType: "codex_local" }]);
    }
    if (path === "/api/orgs/org-1/chats" && init?.method === "POST") {
      conversationCreated = true;
      return respond({ id: "chat-2", title: "请规划部署", status: "active", preferredAgentId: "agent-1" }, 201);
    }
    if (path === "/api/chats/chat-2/messages" && init?.method === "POST") {
      return respond({ detail: "Chat adapter returned no assistant reply" }, 502);
    }
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/chats");
  await screen.findByRole("option", { name: "Builder (engineer)" });
  await userEvent.selectOptions(screen.getByLabelText("对话智能体"), "agent-1");
  await userEvent.type(screen.getByLabelText("消息"), "请规划部署");
  await userEvent.click(screen.getByRole("button", { name: "发送并创建对话" }));

  expect(await screen.findByText("对话已创建，但首条消息发送失败：Chat adapter returned no assistant reply")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "打开已创建的对话" })).toHaveAttribute("href", "/orgs/org-1/chats/chat-2");
  expect(screen.getByRole("navigation", { name: "消息导航" })).toHaveTextContent("请规划部署");
});

it("filters conversations and identifies their selected agent", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/chats" && init?.method === "GET") {
      return respond([
        { id: "chat-1", title: "发布计划", status: "active", preferredAgentId: "agent-1" },
        { id: "chat-2", title: "归档调研", status: "archived", preferredAgentId: null },
        { id: "chat-3", title: "设计讨论", status: "resolved", preferredAgentId: "agent-2" },
      ]);
    }
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") {
      return respond([
        { id: "agent-1", name: "Builder", role: "engineer" },
        { id: "agent-2", name: "Designer", role: "designer" },
      ]);
    }
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/chats");
  const messageNavigation = screen.getByRole("navigation", { name: "消息导航" });
  expect(await within(messageNavigation).findByText("Builder")).toBeInTheDocument();
  expect(messageNavigation).toHaveTextContent("归档调研");
  expect(screen.getByRole("option", { name: "进行中 (1)" })).toBeInTheDocument();
  expect(screen.getByRole("option", { name: "已归档 (1)" })).toBeInTheDocument();

  await userEvent.selectOptions(screen.getByLabelText("状态"), "active");
  expect(messageNavigation).not.toHaveTextContent("归档调研");

  await userEvent.selectOptions(screen.getByLabelText("状态"), "");
  await userEvent.selectOptions(screen.getByLabelText("智能体"), "agent-2");
  expect(messageNavigation).toHaveTextContent("设计讨论");
  expect(messageNavigation).not.toHaveTextContent("发布计划");

  await userEvent.type(screen.getByLabelText("搜索对话"), "没有");
  expect(screen.getByText("没有匹配的对话")).toBeInTheDocument();
});

it("shows the selected conversation and agent identity while sending messages", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/chats" && init?.method === "GET") {
      return respond([{ id: "chat-1", title: "支持会话", status: "active", preferredAgentId: "agent-1" }]);
    }
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") {
      return respond([{ id: "agent-1", name: "Builder", role: "engineer" }]);
    }
    if (path === "/api/agents/agent-1" && init?.method === "GET") {
      return respond({ id: "agent-1", name: "Builder", role: "engineer", status: "active", agentRuntimeType: "codex_local" });
    }
    if (path === "/api/chats/chat-1" && init?.method === "GET") {
      return respond({ id: "chat-1", orgId: "org-1", title: "支持会话", status: "active", preferredAgentId: "agent-1" });
    }
    if (path === "/api/chats/chat-1/messages" && init?.method === "GET") {
      return respond([{ id: "message-1", role: "assistant", body: "已有回复", status: "completed" }]);
    }
    return respond({
      messages: [
        { id: "message-2", role: "user", body: "现在状态？", status: "completed" },
        { id: "message-3", role: "assistant", body: "新回复", status: "completed" },
      ],
    }, 201);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/chats/chat-1");
  expect(await screen.findByRole("heading", { name: "支持会话" })).toBeInTheDocument();
  expect(await screen.findByText("已有回复")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /支持会话/ })).toHaveClass("active");
  expect(screen.getByLabelText("对话智能体")).toBeEnabled();
  expect(screen.getByLabelText("对话智能体")).toHaveValue("agent-1");
  expect(screen.queryByText("对话智能体")).not.toBeInTheDocument();
  expect(screen.getByLabelText("对话智能体").closest(".chat-compose-actions")).toContainElement(
    screen.getByRole("button", { name: "发送" }),
  );
  const reply = screen.getByText("已有回复").closest("article");
  expect(reply).not.toBeNull();
  expect(within(reply!).getByText("Builder")).toBeInTheDocument();

  await userEvent.type(screen.getByLabelText("消息"), "现在状态？");
  await userEvent.click(screen.getByRole("button", { name: "发送" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/chats/chat-1/messages",
    expect.objectContaining({ method: "POST", body: JSON.stringify({ body: "现在状态？" }) }),
  );
  expect(await screen.findByText("新回复")).toBeInTheDocument();
});

it("starts a new conversation when choosing another agent from an existing conversation", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/chats" && init?.method === "GET") {
      return respond([{ id: "chat-1", title: "支持会话", status: "active", preferredAgentId: "agent-1" }]);
    }
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") {
      return respond([
        { id: "agent-1", name: "Builder", role: "engineer", status: "active", agentRuntimeType: "codex_local" },
        { id: "agent-2", name: "Reviewer", role: "reviewer", status: "active", agentRuntimeType: "codex_local" },
      ]);
    }
    if (path === "/api/agents/agent-1" && init?.method === "GET") {
      return respond({ id: "agent-1", name: "Builder", role: "engineer", status: "active", agentRuntimeType: "codex_local" });
    }
    if (path === "/api/agents/agent-2" && init?.method === "GET") {
      return respond({ id: "agent-2", name: "Reviewer", role: "reviewer", status: "active", agentRuntimeType: "codex_local" });
    }
    if (path === "/api/chats/chat-1" && init?.method === "GET") {
      return respond({ id: "chat-1", orgId: "org-1", title: "支持会话", status: "active", preferredAgentId: "agent-1" });
    }
    if (path === "/api/chats/chat-1/messages" && init?.method === "GET") {
      return respond([{ id: "message-1", role: "assistant", body: "已有回复", status: "completed" }]);
    }
    if (path === "/api/orgs/org-1/chats" && init?.method === "POST") {
      return respond({ id: "chat-2", orgId: "org-1", title: "换个角度回答", status: "active", preferredAgentId: "agent-2" }, 201);
    }
    if (path === "/api/chats/chat-2/messages" && init?.method === "POST") {
      return respond({
        messages: [
          { id: "message-2", role: "user", body: "换个角度回答", status: "completed" },
          { id: "message-3", role: "assistant", body: "Reviewer 已回复", status: "completed" },
        ],
      }, 201);
    }
    if (path === "/api/chats/chat-2" && init?.method === "GET") {
      return respond({ id: "chat-2", orgId: "org-1", title: "换个角度回答", status: "active", preferredAgentId: "agent-2" });
    }
    if (path === "/api/chats/chat-2/messages" && init?.method === "GET") {
      return respond([]);
    }
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/chats/chat-1");
  await screen.findByText("已有回复");
  await screen.findByRole("option", { name: "Reviewer (reviewer)" });
  await userEvent.selectOptions(screen.getByLabelText("对话智能体"), "agent-2");
  await userEvent.type(screen.getByLabelText("消息"), "换个角度回答");
  await userEvent.click(screen.getByRole("button", { name: "发送" }));

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/chats",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ title: "换个角度回答", preferredAgentId: "agent-2" }),
    }),
  );
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/chats/chat-2/messages",
    expect.objectContaining({ method: "POST", body: JSON.stringify({ body: "换个角度回答" }) }),
  );
  expect(await screen.findByText("Reviewer 已回复")).toBeInTheDocument();
});

it("sends a message from an existing conversation by pressing Enter", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/chats" && init?.method === "GET") {
      return respond([{ id: "chat-1", title: "支持会话", status: "active", preferredAgentId: "agent-1" }]);
    }
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") {
      return respond([{ id: "agent-1", name: "Builder", role: "engineer" }]);
    }
    if (path === "/api/agents/agent-1" && init?.method === "GET") {
      return respond({ id: "agent-1", name: "Builder", role: "engineer", status: "active", agentRuntimeType: "codex_local" });
    }
    if (path === "/api/chats/chat-1" && init?.method === "GET") {
      return respond({ id: "chat-1", title: "支持会话", status: "active", preferredAgentId: "agent-1" });
    }
    if (path === "/api/chats/chat-1/messages" && init?.method === "GET") {
      return respond([]);
    }
    return respond({ messages: [] }, 201);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/chats/chat-1");
  await screen.findByText("向 Builder 发送第一条消息开始对话。");
  await userEvent.type(screen.getByLabelText("消息"), "你好{Enter}");

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/chats/chat-1/messages",
    expect.objectContaining({ method: "POST", body: JSON.stringify({ body: "你好" }) }),
  );
});

it("shows an empty thread prompt for a conversation without messages", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/chats" && init?.method === "GET") {
      return respond([{ id: "chat-1", title: "新会话", status: "active", preferredAgentId: "agent-1" }]);
    }
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") {
      return respond([{ id: "agent-1", name: "Builder", role: "engineer" }]);
    }
    if (path === "/api/agents/agent-1" && init?.method === "GET") {
      return respond({ id: "agent-1", name: "Builder", role: "engineer", status: "active", agentRuntimeType: "codex_local" });
    }
    if (path === "/api/chats/chat-1" && init?.method === "GET") {
      return respond({ id: "chat-1", title: "新会话", status: "active", preferredAgentId: "agent-1" });
    }
    if (path === "/api/chats/chat-1/messages" && init?.method === "GET") {
      return respond([]);
    }
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/chats/chat-1");
  expect(await screen.findByText("还没有消息")).toBeInTheDocument();
  expect(await screen.findByText("向 Builder 发送第一条消息开始对话。")).toBeInTheDocument();
});

it("explains a failed reply without discarding the message draft", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/chats" && init?.method === "GET") {
      return respond([{ id: "chat-1", title: "排查问题", status: "active", preferredAgentId: "agent-1" }]);
    }
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") {
      return respond([{ id: "agent-1", name: "Builder", role: "engineer" }]);
    }
    if (path === "/api/agents/agent-1" && init?.method === "GET") {
      return respond({ id: "agent-1", name: "Builder", role: "engineer", status: "active", agentRuntimeType: "codex_local" });
    }
    if (path === "/api/chats/chat-1" && init?.method === "GET") {
      return respond({ id: "chat-1", title: "排查问题", status: "active", preferredAgentId: "agent-1" });
    }
    if (path === "/api/chats/chat-1/messages" && init?.method === "GET") {
      return respond([]);
    }
    if (path === "/api/chats/chat-1/messages" && init?.method === "POST") {
      return respond({ detail: "Chat adapter returned no assistant reply" }, 502);
    }
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/chats/chat-1");
  await screen.findByText("向 Builder 发送第一条消息开始对话。");
  await userEvent.type(screen.getByLabelText("消息"), "你好");
  await userEvent.click(screen.getByRole("button", { name: "发送" }));

  expect(await screen.findByText("Chat adapter returned no assistant reply")).toBeInTheDocument();
  expect(screen.queryByText("Request failed (500)")).not.toBeInTheDocument();
  expect(screen.getByLabelText("消息")).toHaveValue("你好");
});

it("does not send from a conversation bound to a non-chat runtime", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/chats" && init?.method === "GET") {
      return respond([{ id: "chat-1", title: "旧会话", status: "active", preferredAgentId: "agent-1" }]);
    }
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") {
      return respond([{ id: "agent-1", name: "Runner", role: "engineer" }]);
    }
    if (path === "/api/agents/agent-1" && init?.method === "GET") {
      return respond({ id: "agent-1", name: "Runner", role: "engineer", status: "idle", agentRuntimeType: "process" });
    }
    if (path === "/api/chats/chat-1" && init?.method === "GET") {
      return respond({ id: "chat-1", title: "旧会话", status: "active", preferredAgentId: "agent-1" });
    }
    if (path === "/api/chats/chat-1/messages" && init?.method === "GET") {
      return respond([]);
    }
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/chats/chat-1");
  expect(await screen.findByText("当前对话绑定的智能体不能用于消息回复，请新建对话并选择 codex_local 智能体。")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "发送" })).toBeDisabled();
});
