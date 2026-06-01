import { cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { renderApp, respond, respondStream } from "./render-app";

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
    if (path === "/api/orgs/org-1/projects" && init?.method === "GET") {
      return respond([{ id: "project-1", orgId: "org-1", name: "平台项目", status: "active" }]);
    }
    if (path === "/api/agents/agent-1/skills" && init?.method === "GET") {
      return respond({ desiredSkills: ["review"], entries: [{ name: "deploy" }] });
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
    if (path === "/api/chats/chat-2/messages/stream" && init?.method === "POST") {
      return respondStream([
        { type: "ack", userMessage: { id: "message-1", role: "user", body: "请规划部署", status: "completed" } },
        { type: "assistant_delta", delta: "已收到部署请求" },
        {
          type: "final",
          messages: [
            { id: "message-1", role: "user", body: "请规划部署", status: "completed" },
            { id: "message-2", role: "assistant", body: "已收到部署请求", status: "completed" },
          ],
        },
      ]);
    }
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/chats");
  expect(await screen.findByRole("option", { name: "Builder (engineer)" })).toBeInTheDocument();
  expect(screen.queryByRole("navigation", { name: "组织导航" })).not.toBeInTheDocument();
  expect(screen.getByRole("navigation", { name: "消息导航" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /新建聊天/ })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "What do you want to work on?" })).toBeInTheDocument();
  expect(screen.queryByLabelText("标题（可选）")).not.toBeInTheDocument();
  expect(screen.getByLabelText("消息")).toBeInTheDocument();
  expect(screen.queryByText("对话智能体")).not.toBeInTheDocument();
  expect(within(screen.getByRole("navigation", { name: "消息导航" })).queryByRole("combobox")).not.toBeInTheDocument();
  expect(screen.getByLabelText("项目")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "发送并创建对话" })).toBeInTheDocument();

  expect(await screen.findByRole("option", { name: "平台项目" })).toBeInTheDocument();
  await userEvent.selectOptions(screen.getByLabelText("项目"), "project-1");
  await userEvent.selectOptions(screen.getByLabelText("对话智能体"), "agent-1");
  const skillSummary = screen.getByText("技能列表");
  const skillDropdown = skillSummary.closest("details");
  await userEvent.click(skillSummary);
  expect(skillDropdown).toHaveAttribute("open");
  expect(await screen.findByText("review")).toBeInTheDocument();
  expect(await screen.findByText("deploy")).toBeInTheDocument();
  await userEvent.click(screen.getByLabelText("消息"));
  expect(skillDropdown).not.toHaveAttribute("open");
  await userEvent.type(screen.getByLabelText("消息"), "请规划部署");
  await userEvent.click(screen.getByRole("button", { name: "发送并创建对话" }));

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/chats",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        title: "请规划部署",
        preferredAgentId: "agent-1",
        contextLinks: [{ entityType: "project", entityId: "project-1" }],
      }),
    }),
  );
  expect(await screen.findByRole("heading", { name: "请规划部署" })).toBeInTheDocument();
  expect(await screen.findByText("已收到部署请求")).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/chats/chat-2/messages/stream",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ body: "请规划部署" }),
    }),
  );
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
    if (path === "/api/chats/chat-2/messages/stream" && init?.method === "POST") {
      return respondStream([{ type: "final", messages: [] }]);
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

it("opens a new conversation with an error notice when no assistant reply is returned", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/chats" && init?.method === "GET") {
      return respond([]);
    }
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") {
      return respond([{ id: "agent-1", name: "Builder", role: "engineer", status: "idle", agentRuntimeType: "codex_local" }]);
    }
    if (path === "/api/orgs/org-1/projects" && init?.method === "GET") {
      return respond([{ id: "project-1", orgId: "org-1", name: "平台项目", status: "active" }]);
    }
    if (path === "/api/agents/agent-1/skills" && init?.method === "GET") {
      return respond({ desiredSkills: ["review"], entries: [{ name: "deploy" }] });
    }
    if (path === "/api/orgs/org-1/projects" && init?.method === "GET") {
      return respond([{ id: "project-1", orgId: "org-1", name: "平台项目", status: "active" }]);
    }
    if (path === "/api/agents/agent-1/skills" && init?.method === "GET") {
      return respond({ desiredSkills: ["review"], entries: [{ name: "deploy" }] });
    }
    if (path === "/api/orgs/org-1/projects" && init?.method === "GET") {
      return respond([{ id: "project-1", orgId: "org-1", name: "平台项目", status: "active" }]);
    }
    if (path === "/api/agents/agent-1/skills" && init?.method === "GET") {
      return respond({ desiredSkills: ["review"], entries: [{ name: "deploy" }] });
    }
    if (path === "/api/orgs/org-1/chats" && init?.method === "POST") {
      return respond({ id: "chat-2", title: "你好", status: "active", preferredAgentId: "agent-1" }, 201);
    }
    if (path === "/api/chats/chat-2/messages/stream" && init?.method === "POST") {
      return respondStream([
        { type: "ack", userMessage: { id: "message-1", role: "user", body: "你好", status: "completed" } },
        { type: "final", messages: [{ id: "message-1", role: "user", body: "你好", status: "completed" }] },
      ]);
    }
    if (path === "/api/chats/chat-2" && init?.method === "GET") {
      return respond({ id: "chat-2", title: "你好", status: "active", preferredAgentId: "agent-1" });
    }
    if (path === "/api/chats/chat-2/messages" && init?.method === "GET") {
      return respond([{ id: "message-1", role: "user", body: "你好", status: "completed" }]);
    }
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/chats");
  await screen.findByRole("option", { name: "Builder (engineer)" });
  await userEvent.selectOptions(screen.getByLabelText("对话智能体"), "agent-1");
  await userEvent.type(screen.getByLabelText("消息"), "你好{Enter}");

  expect(await screen.findByRole("heading", { name: "你好" })).toBeInTheDocument();
  expect(
    await screen.findByText("消息发送失败：智能体没有返回消息。请检查所选智能体运行配置后重试。"),
  ).toBeInTheDocument();
});

it("offers non-terminated runtime agents for a new conversation", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/chats" && init?.method === "GET") {
      return respond([]);
    }
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") {
      return respond([
        { id: "agent-1", name: "Runner", role: "engineer", status: "idle", agentRuntimeType: "process" },
        { id: "agent-2", name: "Builder", role: "engineer", status: "idle", agentRuntimeType: "codex_local" },
        { id: "agent-3", name: "Stopped", role: "qa", status: "terminated", agentRuntimeType: "claude_local" },
      ]);
    }
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/chats");
  expect(await screen.findByRole("option", { name: "Builder (engineer)" })).toBeInTheDocument();
  expect(screen.getByRole("option", { name: "Runner (engineer)" })).toBeInTheDocument();
  expect(screen.queryByRole("option", { name: "Stopped (qa)" })).not.toBeInTheDocument();
});

it("preselects the agent provided by an agent detail chat entry", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/chats" && init?.method === "GET") {
      return respond([]);
    }
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") {
      return respond([{ id: "agent-1", name: "Builder", role: "engineer", status: "idle", agentRuntimeType: "codex_local" }]);
    }
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/chats?agentId=agent-1");
  expect(await screen.findByRole("option", { name: "Builder (engineer)" })).toBeInTheDocument();
  expect(screen.getByLabelText("对话智能体")).toHaveValue("agent-1");
});

it("opens the conversation when the first reply request fails", async () => {
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
    if (path === "/api/chats/chat-2/messages/stream" && init?.method === "POST") {
      return respond({ detail: "Chat adapter returned no assistant reply" }, 502);
    }
    if (path === "/api/chats/chat-2" && init?.method === "GET") {
      return respond({ id: "chat-2", title: "请规划部署", status: "active", preferredAgentId: "agent-1" });
    }
    if (path === "/api/chats/chat-2/messages" && init?.method === "GET") return respond([]);
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/chats");
  await screen.findByRole("option", { name: "Builder (engineer)" });
  await userEvent.selectOptions(screen.getByLabelText("对话智能体"), "agent-1");
  await userEvent.type(screen.getByLabelText("消息"), "请规划部署");
  await userEvent.click(screen.getByRole("button", { name: "发送并创建对话" }));

  expect(await screen.findByRole("heading", { name: "请规划部署" })).toBeInTheDocument();
  expect(within(screen.getByTestId("chat-message-thread")).getByText("请规划部署")).toBeInTheDocument();
  expect(await screen.findByText("消息发送失败：Chat adapter returned no assistant reply")).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "打开已创建的对话" })).not.toBeInTheDocument();
  expect(screen.getByRole("navigation", { name: "消息导航" })).toHaveTextContent("请规划部署");
});

it("shows the first user message immediately after creating a conversation", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/chats" && init?.method === "GET") {
      return respond([]);
    }
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") {
      return respond([{ id: "agent-1", name: "Builder", role: "engineer", status: "idle", agentRuntimeType: "codex_local" }]);
    }
    if (path === "/api/orgs/org-1/projects" && init?.method === "GET") return respond([]);
    if (path === "/api/orgs/org-1/chats" && init?.method === "POST") {
      return respond({ id: "chat-2", title: "你好", status: "active", preferredAgentId: "agent-1" }, 201);
    }
    if (path === "/api/chats/chat-2/messages/stream" && init?.method === "POST") {
      return respondStream([
        { type: "ack", userMessage: { id: "message-1", role: "user", body: "你好", status: "completed" } },
        { type: "final", messages: [{ id: "message-1", role: "user", body: "你好", status: "completed" }] },
      ]);
    }
    if (path === "/api/chats/chat-2" && init?.method === "GET") {
      return respond({ id: "chat-2", title: "你好", status: "active", preferredAgentId: "agent-1" });
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
  await userEvent.type(screen.getByLabelText("消息"), "你好");
  await userEvent.click(screen.getByRole("button", { name: "发送并创建对话" }));

  expect(await screen.findByRole("heading", { name: "你好" })).toBeInTheDocument();
  expect(within(screen.getByTestId("chat-message-thread")).getAllByText("你好")).toHaveLength(1);
});

it("opens the cached created conversation when the first reply fails and detail reload errors", async () => {
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
    if (path === "/api/orgs/org-1/projects" && init?.method === "GET") return respond([]);
    if (path === "/api/agents/agent-1" && init?.method === "GET") {
      return respond({ id: "agent-1", name: "Builder", role: "engineer", status: "idle", agentRuntimeType: "codex_local" });
    }
    if (path === "/api/orgs/org-1/chats" && init?.method === "POST") {
      conversationCreated = true;
      return respond({ id: "chat-2", orgId: "org-1", title: "请规划部署", status: "active", preferredAgentId: "agent-1" }, 201);
    }
    if (path === "/api/chats/chat-2/messages/stream" && init?.method === "POST") {
      return respond({ detail: "Chat adapter returned no assistant reply" }, 502);
    }
    if (path === "/api/chats/chat-2" && init?.method === "GET") {
      return respond({ detail: "temporary reload failure" }, 500);
    }
    if (path === "/api/chats/chat-2/messages" && init?.method === "GET") return respond([]);
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/chats");
  await screen.findByRole("option", { name: "Builder (engineer)" });
  await userEvent.selectOptions(screen.getByLabelText("对话智能体"), "agent-1");
  await userEvent.type(screen.getByLabelText("消息"), "请规划部署");
  await userEvent.click(screen.getByRole("button", { name: "发送并创建对话" }));

  expect(await screen.findByRole("heading", { name: "请规划部署" })).toBeInTheDocument();
  expect(await screen.findByText(/已打开本地缓存的对话/)).toBeInTheDocument();
  expect(within(screen.getByTestId("chat-message-thread")).getByText("请规划部署")).toBeInTheDocument();
});

it("lists conversations without sidebar filters and identifies their selected agent", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/chats" && init?.method === "GET") {
      return respond([
        { id: "chat-1", title: "发布计划", status: "active", preferredAgentId: "agent-1", latestReplyPreview: "这是最近一条回答，会在会话列表里只显示一行", unreadCount: 99 },
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
  expect(within(messageNavigation).getByRole("heading", { name: "消息" })).toBeInTheDocument();
  expect(within(messageNavigation).getByRole("heading", { name: "对话" })).toBeInTheDocument();
  expect(within(messageNavigation).getByRole("link", { name: /新建聊天/ })).toHaveClass("context-action-entry");
  expect(within(messageNavigation).getByRole("link", { name: "审批管理" })).toHaveAttribute(
    "href",
    "/orgs/org-1/approvals",
  );
  expect(await within(messageNavigation).findByText("这是最近一条回答，会在会话列表里只显示一行")).toBeInTheDocument();
  expect(messageNavigation).toHaveTextContent("发布计划");
  expect(messageNavigation).toHaveTextContent("归档调研");
  expect(messageNavigation).toHaveTextContent("设计讨论");
  expect(messageNavigation).toHaveTextContent("Designer");
  expect(within(messageNavigation).queryByText("99 未读")).not.toBeInTheDocument();
  expect(messageNavigation.querySelector(".chat-conversation-list")).toBeInTheDocument();
  expect(screen.queryByLabelText("搜索对话")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("状态")).not.toBeInTheDocument();
  expect(within(messageNavigation).queryByLabelText("智能体")).not.toBeInTheDocument();
});

it("shows an empty sidebar state when no conversations exist", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/chats" && init?.method === "GET") return respond([]);
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") return respond([]);
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/chats");
  expect(await within(screen.getByRole("navigation", { name: "消息导航" })).findByText("暂无对话")).toBeInTheDocument();
});

it("manages a conversation from the sidebar action menu", async () => {
  let chats = [{ id: "chat-1", title: "支持会话", status: "active", preferredAgentId: "agent-1" }];
  const writeText = vi.fn();
  Object.assign(navigator, { clipboard: { writeText } });
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/chats" && init?.method === "GET") return respond(chats);
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") {
      return respond([{ id: "agent-1", name: "Builder", role: "engineer", status: "active" }]);
    }
    if (path === "/api/chats/chat-1" && init?.method === "GET") {
      return respond({ id: "chat-1", title: chats[0]?.title ?? "支持会话", status: "active", preferredAgentId: "agent-1" });
    }
    if (path === "/api/chats/chat-1/messages" && init?.method === "GET") return respond([]);
    if (path === "/api/chats/chat-1" && init?.method === "PATCH") {
      const body = JSON.parse(String(init.body)) as { title?: string; status?: string };
      if (body.title) {
        chats = [{ ...chats[0], title: body.title }];
        return respond({ id: "chat-1", title: body.title, status: "active", preferredAgentId: "agent-1" });
      }
      if (body.status === "archived") {
        chats = [];
        return respond({ id: "chat-1", title: "已重命名", status: "archived", preferredAgentId: "agent-1" });
      }
    }
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/chats/chat-1");
  expect(await screen.findByRole("heading", { name: "支持会话" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "支持会话 操作" }));
  await userEvent.click(screen.getByRole("button", { name: "重命名" }));
  await userEvent.clear(screen.getByLabelText("新会话名称"));
  await userEvent.type(screen.getByLabelText("新会话名称"), "已重命名");
  await userEvent.click(screen.getByRole("button", { name: "确认" }));

  expect(await screen.findByRole("link", { name: /已重命名/ })).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/chats/chat-1",
    expect.objectContaining({ method: "PATCH", body: JSON.stringify({ title: "已重命名" }) }),
  );

  await userEvent.click(screen.getByRole("button", { name: "已重命名 操作" }));
  await userEvent.click(screen.getByRole("button", { name: "复制聊天 ID" }));
  expect(writeText).toHaveBeenCalledWith("chat-1");

  await userEvent.click(screen.getByRole("button", { name: "已重命名 操作" }));
  await userEvent.click(screen.getByRole("button", { name: "归档" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/chats/chat-1",
    expect.objectContaining({ method: "PATCH", body: JSON.stringify({ status: "archived" }) }),
  );
  expect(screen.queryByRole("link", { name: /已重命名/ })).not.toBeInTheDocument();
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
    if (path === "/api/chats/chat-1/messages/stream" && init?.method === "POST") {
      return respondStream([
        { type: "ack", userMessage: { id: "message-2", role: "user", body: "现在状态？", status: "completed" } },
        { type: "assistant_delta", delta: "新" },
        { type: "assistant_delta", delta: "回复" },
        {
          type: "final",
          messages: [
            { id: "message-2", role: "user", body: "现在状态？", status: "completed" },
            { id: "message-3", role: "assistant", body: "新回复", status: "completed" },
          ],
        },
      ]);
    }
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/chats/chat-1");
  expect(await screen.findByRole("heading", { name: "支持会话" })).toBeInTheDocument();
  expect(await screen.findByText("已有回复")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /支持会话/ })).toHaveClass("active");
  expect(screen.getByLabelText("对话智能体")).toBeDisabled();
  expect(screen.getByLabelText("对话智能体")).toHaveValue("agent-1");
  expect(screen.getByRole("option", { name: "Builder (engineer)" })).toBeInTheDocument();
  expect(screen.queryByText("对话智能体")).not.toBeInTheDocument();
  expect(screen.getByLabelText("对话智能体").closest(".chat-context-controls")).toContainElement(
    screen.getByRole("button", { name: "发送" }),
  );
  const reply = screen.getByText("已有回复").closest("article");
  expect(reply).not.toBeNull();
  expect(within(reply!).getByText("Builder")).toBeInTheDocument();

  await userEvent.type(screen.getByLabelText("消息"), "现在状态？");
  await userEvent.click(screen.getByRole("button", { name: "发送" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/chats/chat-1/messages/stream",
    expect.objectContaining({ method: "POST", body: JSON.stringify({ body: "现在状态？" }) }),
  );
  expect(await screen.findByText("新回复")).toBeInTheDocument();
});

it("shows existing conversation context as readonly controls with a skill dropdown", async () => {
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
    if (path === "/api/chats/chat-1" && init?.method === "GET") {
      return respond({
        id: "chat-1",
        orgId: "org-1",
        title: "支持会话",
        status: "active",
        preferredAgentId: "agent-1",
        contextLinks: [{
          id: "link-1",
          orgId: "org-1",
          conversationId: "chat-1",
          entityType: "project",
          entityId: "project-1",
          metadata: null,
          entity: { type: "project", id: "project-1", label: "平台项目", subtitle: null, identifier: null, status: "active", href: "" },
        }],
      });
    }
    if (path === "/api/chats/chat-1/messages" && init?.method === "GET") {
      return respond([{ id: "message-1", role: "assistant", body: "已有回复", status: "completed" }]);
    }
    if (path === "/api/agents/agent-1/skills" && init?.method === "GET") {
      return respond({ desiredSkills: ["review"], entries: [{ name: "deploy" }] });
    }
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/chats/chat-1");
  await screen.findByText("已有回复");
  expect(screen.getByLabelText("项目")).toBeDisabled();
  expect(screen.getByLabelText("项目")).toHaveTextContent("平台项目");
  expect(screen.getByLabelText("对话智能体")).toBeDisabled();
  expect(screen.queryByRole("option", { name: "Reviewer (reviewer)" })).not.toBeInTheDocument();
  const skillSummary = screen.getByText("技能列表");
  const skillDropdown = skillSummary.closest("details");
  await userEvent.click(skillSummary);
  expect(skillDropdown).toHaveAttribute("open");
  expect(await screen.findByText("review")).toBeInTheDocument();
  expect(await screen.findByText("deploy")).toBeInTheDocument();
  await userEvent.click(screen.getByLabelText("消息"));
  expect(skillDropdown).not.toHaveAttribute("open");
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
    if (path === "/api/chats/chat-1/messages/stream" && init?.method === "POST") {
      return respondStream([{ type: "final", messages: [] }]);
    }
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/chats/chat-1");
  await screen.findByText("向 Builder 发送第一条消息开始对话。");
  await userEvent.type(screen.getByLabelText("消息"), "你好{Enter}");

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/chats/chat-1/messages/stream",
    expect.objectContaining({ method: "POST", body: JSON.stringify({ body: "你好" }) }),
  );
});

it("shows the user's message immediately after clicking send", async () => {
  let resolvePost: (response: Promise<Response>) => void = () => {};
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/chats" && init?.method === "GET") {
      return respond([{ id: "chat-1", title: "支持会话", status: "active", preferredAgentId: "agent-1" }]);
    }
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") {
      return respond([{ id: "agent-1", name: "Builder", role: "engineer", status: "active" }]);
    }
    if (path === "/api/chats/chat-1" && init?.method === "GET") {
      return respond({ id: "chat-1", title: "支持会话", status: "active", preferredAgentId: "agent-1" });
    }
    if (path === "/api/chats/chat-1/messages" && init?.method === "GET") {
      return respond([]);
    }
    if (path === "/api/chats/chat-1/messages/stream" && init?.method === "POST") {
      return new Promise<Response>((resolve) => {
        resolvePost = resolve;
      });
    }
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/chats/chat-1");
  await screen.findByText("No messages yet.");
  await userEvent.type(screen.getByLabelText("消息"), "你好");
  await userEvent.click(screen.getByRole("button", { name: "发送" }));

  expect(await screen.findByText("你好")).toBeInTheDocument();
  const messageThread = screen.getByTestId("chat-message-thread");
  expect(await within(messageThread).findByText("Thinking", { exact: false })).toBeInTheDocument();
  expect(within(messageThread).getByText("Builder")).toBeInTheDocument();
  expect(within(messageThread).queryByText("message")).not.toBeInTheDocument();
  expect(within(messageThread).queryByText("completed")).not.toBeInTheDocument();
  expect(screen.getByLabelText("消息")).toHaveValue("");

  resolvePost(respondStream([
    { type: "final", messages: [{ id: "message-1", role: "user", body: "你好", status: "completed" }] },
  ]));
  expect(
    await within(messageThread).findByText("消息发送失败：智能体没有返回消息。请检查所选智能体运行配置后重试。"),
  ).toBeInTheDocument();
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
  expect(await screen.findByText("No messages yet.")).toBeInTheDocument();
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
    if (path === "/api/chats/chat-1/messages/stream" && init?.method === "POST") {
      return respond({ detail: "Chat adapter returned no assistant reply" }, 502);
    }
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/chats/chat-1");
  await screen.findByText("向 Builder 发送第一条消息开始对话。");
  await userEvent.type(screen.getByLabelText("消息"), "你好");
  await userEvent.click(screen.getByRole("button", { name: "发送" }));

  const messageThread = screen.getByTestId("chat-message-thread");
  expect(await within(messageThread).findByText("消息发送失败：Chat adapter returned no assistant reply")).toBeInTheDocument();
  expect(screen.queryByText("Request failed (500)")).not.toBeInTheDocument();
  expect(screen.getByText("你好")).toBeInTheDocument();
  expect(screen.getByLabelText("消息")).toHaveValue("");
});

it("renders send errors in the message thread instead of expanding the composer", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/chats" && init?.method === "GET") {
      return respond([{ id: "chat-1", title: "排查问题", status: "active", preferredAgentId: "agent-1" }]);
    }
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") {
      return respond([{ id: "agent-1", name: "Builder", role: "engineer", status: "active" }]);
    }
    if (path === "/api/chats/chat-1" && init?.method === "GET") {
      return respond({ id: "chat-1", title: "排查问题", status: "active", preferredAgentId: "agent-1" });
    }
    if (path === "/api/chats/chat-1/messages" && init?.method === "GET") return respond([]);
    if (path === "/api/chats/chat-1/messages/stream" && init?.method === "POST") {
      return respond({ detail: "Request failed (500)" }, 500);
    }
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/chats/chat-1");
  await screen.findByText("No messages yet.");
  await userEvent.type(screen.getByLabelText("消息"), "你好");
  await userEvent.click(screen.getByRole("button", { name: "发送" }));

  const messageThread = screen.getByTestId("chat-message-thread");
  expect(await within(messageThread).findByText("消息发送失败：Request failed (500)")).toBeInTheDocument();
  expect(screen.getByRole("form", { name: "发送消息" })).not.toHaveTextContent("Request failed (500)");
});

it("does not send from a conversation bound to a terminated agent", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/chats" && init?.method === "GET") {
      return respond([{ id: "chat-1", title: "旧会话", status: "active", preferredAgentId: "agent-1" }]);
    }
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") {
      return respond([{ id: "agent-1", name: "Runner", role: "engineer", status: "terminated" }]);
    }
    if (path === "/api/agents/agent-1" && init?.method === "GET") {
      return respond({ id: "agent-1", name: "Runner", role: "engineer", status: "terminated", agentRuntimeType: "process" });
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
  expect(await screen.findByText("当前选择的智能体不能用于消息回复，请切换到可运行智能体。")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "发送" })).toBeDisabled();
});
