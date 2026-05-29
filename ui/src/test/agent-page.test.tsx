import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { renderApp, respond } from "./render-app";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("controls an agent from its overview and shows runtime status", async () => {
  const agent = {
    id: "agent-1",
    orgId: "org-1",
    name: "Builder",
    title: "Build owner",
    role: "engineer",
    status: "idle",
    agentRuntimeType: "codex_local",
    agentRuntimeConfig: {
      model: "gpt-5",
      cwd: "D:/work/app",
      instructionsRootPath: "D:/work/app/.agent",
      instructionsFilePath: "D:/work/app/.agent/SOUL.md",
      agentsMdPath: "D:/work/app/AGENTS.md",
      promptTemplate: "Ship product changes",
      skillsRootPath: "D:/work/app/.agent/skills",
      managedInstructionFiles: [
        { name: "TOOLS.md", path: "D:/work/app/.agent/TOOLS.md", content: "Tool policy" },
        { name: "MEMORY.md", path: "D:/work/app/.agent/MEMORY.md", content: "Memory policy" },
        { name: "NOTES.md", path: "D:/work/app/.agent/NOTES.md", content: "Project notes" },
      ],
    },
    runtimeConfig: { memory: "Keep deployment context" },
    budgetMonthlyCents: 0,
    capabilities: "Ship product changes",
    desiredSkills: ["review"],
    reportsTo: "lead-1",
  };
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/agents/agent-1" && init?.method === "GET") return respond(agent);
    if (path === "/api/agents/agent-1/runtime-state" && init?.method === "GET") {
      return respond({ lastRunStatus: "succeeded", sessionDisplayId: "session-1", totalInputTokens: 10, totalOutputTokens: 5, totalCostCents: 1 });
    }
    return respond({ ...agent, status: "paused" });
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/agents/agent-1");
  const heading = await screen.findByRole("heading", { name: "Builder" });
  const header = heading.closest("header");
  expect(header).not.toBeNull();
  expect(within(header!).getByText("idle")).toBeInTheDocument();
  expect(within(header!).getByRole("button", { name: "分配任务" })).toBeInTheDocument();
  expect(within(header!).getByRole("link", { name: "聊天" })).toHaveAttribute(
    "href",
    "/orgs/org-1/chats?agentId=agent-1",
  );
  expect(within(header!).getByRole("button", { name: "暂停" })).toBeInTheDocument();
  expect(within(header!).getByRole("button", { name: "恢复" })).toBeInTheDocument();
  expect(within(header!).getByRole("button", { name: "终止" })).toBeInTheDocument();
  expect(within(header!).getByRole("button", { name: "唤醒" })).toBeInTheDocument();
  expect(within(header!).getByRole("button", { name: "运行心跳" })).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "暂停" })).toHaveLength(1);
  const tabs = screen.getByRole("navigation", { name: "智能体详情导航" });
  expect(within(tabs).getByRole("link", { name: "说明" })).toHaveAttribute(
    "href",
    "/orgs/org-1/agents/agent-1/profile",
  );
  expect(within(tabs).getByRole("link", { name: "技能" })).toHaveAttribute(
    "href",
    "/orgs/org-1/agents/agent-1/skills",
  );
  await userEvent.click(within(tabs).getByRole("link", { name: "说明" }));
  const instructionsPanel = screen.getByRole("region", { name: "Managed Instructions" });
  expect(await within(instructionsPanel).findByRole("heading", { name: "Files" })).toBeInTheDocument();
  expect(within(instructionsPanel).getByRole("button", { name: "SOUL.md" }).closest("li")).toHaveClass("selected");
  expect(within(instructionsPanel).getByRole("button", { name: "AGENTS.md" })).toBeInTheDocument();
  expect(within(instructionsPanel).getByRole("button", { name: "TOOLS.md" })).toBeInTheDocument();
  expect(within(instructionsPanel).getByRole("button", { name: "MEMORY.md" })).toBeInTheDocument();
  expect(within(instructionsPanel).getByRole("button", { name: "NOTES.md" })).toBeInTheDocument();
  expect(within(screen.getByRole("complementary", { name: "Instruction files" })).queryByText("managedInstructionFiles")).not.toBeInTheDocument();
  const instructionContent = screen.getByRole("article", { name: "Instruction content" });
  expect(within(instructionsPanel).getByText(/Ship product changes/)).toBeInTheDocument();
  await userEvent.click(within(instructionsPanel).getByRole("button", { name: "AGENTS.md" }));
  expect(within(instructionContent).queryByText("暂无内容")).not.toBeInTheDocument();
  await userEvent.click(within(instructionsPanel).getByRole("button", { name: "TOOLS.md" }));
  expect(within(instructionContent).getByText(/Tool policy/)).toBeInTheDocument();
  const instructionFiles = screen.getByRole("complementary", { name: "Instruction files" });
  await userEvent.click(within(instructionFiles).getByRole("button", { name: "新增文件" }));
  expect(within(instructionFiles).getByLabelText("文件名")).toHaveValue("NEW.md");
  expect(within(instructionFiles).queryByLabelText("路径")).not.toBeInTheDocument();
  expect(within(instructionFiles).queryByLabelText("内容")).not.toBeInTheDocument();
  await userEvent.clear(within(instructionFiles).getByLabelText("文件名"));
  await userEvent.type(within(instructionFiles).getByLabelText("文件名"), "RUNBOOK.md");
  expect(within(instructionFiles).getByRole("button", { name: "取消" })).toBeInTheDocument();
  await userEvent.click(within(instructionFiles).getByRole("button", { name: "确认" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/agents/agent-1",
    expect.objectContaining({
      method: "PATCH",
      body: expect.stringContaining("RUNBOOK.md"),
    }),
  );
  await userEvent.click(within(tabs).getByRole("link", { name: "概览" }));
  expect(await screen.findByText("succeeded")).toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: "暂停" }));
  await userEvent.click(screen.getByRole("button", { name: "唤醒" }));
  await userEvent.click(screen.getByRole("button", { name: "运行心跳" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/agents/agent-1/pause",
    expect.objectContaining({ method: "POST" }),
  );
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/agents/agent-1/wakeup",
    expect.objectContaining({ method: "POST" }),
  );
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/agents/agent-1/heartbeat/invoke",
    expect.objectContaining({ method: "POST" }),
  );
});

it("assigns a task to the current agent from a modal", async () => {
  const agent = { id: "agent-1", orgId: "org-1", name: "Builder", role: "engineer", status: "idle", agentRuntimeType: "codex_local", agentRuntimeConfig: {}, runtimeConfig: {}, budgetMonthlyCents: 0 };
  const createdIssue = {
    id: "issue-1",
    orgId: "org-1",
    identifier: "CORE-1",
    title: "排查部署",
    status: "todo",
    priority: "medium",
    description: null,
    projectId: null,
    goalId: null,
    assigneeAgentId: "agent-1",
    assigneeUserId: null,
    originKind: "manual",
    originId: null,
    reviewerAgentId: null,
    reviewerUserId: null,
    parentId: null,
    issueNumber: 1,
    requestDepth: 0,
    startedAt: null,
    completedAt: null,
    createdAt: "2026-05-27T00:00:00Z",
    updatedAt: "2026-05-27T00:00:00Z",
  };
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/agents/agent-1" && init?.method === "GET") return respond(agent);
    if (path === "/api/agents/agent-1/runtime-state" && init?.method === "GET") {
      return respond({ lastRunStatus: null, sessionDisplayId: null, totalInputTokens: 0, totalOutputTokens: 0, totalCostCents: 0 });
    }
    if (path === "/api/orgs/org-1/issues" && init?.method === "POST") return respond(createdIssue, 201);
    if (path === "/api/issues/issue-1" && init?.method === "GET") return respond(createdIssue);
    if (path === "/api/issues/issue-1/comments" && init?.method === "GET") return respond([]);
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/agents/agent-1");
  await userEvent.click(await screen.findByRole("button", { name: "分配任务" }));
  const dialog = screen.getByRole("dialog", { name: "分配任务" });
  expect(dialog).toHaveTextContent("负责人：Builder");
  await userEvent.type(within(dialog).getByLabelText("任务标题"), "排查部署");
  await userEvent.click(within(dialog).getByRole("button", { name: "创建任务" }));

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/issues",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ title: "排查部署", assigneeAgentId: "agent-1" }),
    }),
  );
  expect(await screen.findByRole("heading", { name: "排查部署" })).toBeInTheDocument();
});

it("saves supported agent configuration and shows heartbeat runs tab", async () => {
  const agent = { id: "agent-1", orgId: "org-1", name: "Builder", role: "engineer", status: "idle", agentRuntimeType: "process", agentRuntimeConfig: {}, runtimeConfig: {}, budgetMonthlyCents: 0, capabilities: null, reportsTo: null };
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/agents/agent-1" && init?.method === "GET") return respond(agent);
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") return respond([agent]);
    if (path.includes("heartbeat-runs") && init?.method === "GET") {
      if (path === "/api/heartbeat-runs/run-1/events") {
        return respond([
          { id: 1, runId: "run-1", agentId: "agent-1", seq: 1, eventType: "runtime.stderr", stream: "stderr", level: "error", message: "model missing", payload: { phase: "adapter" }, createdAt: "2026-05-29T01:00:01Z" },
        ]);
      }
      return respond([{
        id: "run-1",
        status: "failed",
        invocationSource: "on_demand",
        error: "Runtime failed",
        errorCode: "runtime_error",
        stdoutExcerpt: "boot ok",
        stderrExcerpt: "model missing",
        usageJson: { inputTokens: 12 },
        resultJson: { summary: "failed summary" },
        contextSnapshot: { workspace: { executionWorkspaceId: "workspace-1" } },
      }]);
    }
    return respond({ ...agent, name: "Builder 2" });
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/agents/agent-1/configuration");
  expect(await screen.findByRole("heading", { name: "身份" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "智能体运行时" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "运行策略" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "权限" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "API 密钥" })).toBeInTheDocument();
  await userEvent.clear(await screen.findByLabelText("智能体名称"));
  await userEvent.type(screen.getByLabelText("智能体名称"), "Builder 2");
  await userEvent.selectOptions(screen.getByLabelText("Runtime"), "codex_local");
  await userEvent.clear(screen.getByLabelText("月度预算（cents）"));
  await userEvent.type(screen.getByLabelText("月度预算（cents）"), "1000");
  fireEvent.change(screen.getByLabelText("Agent runtime config"), { target: { value: '{"model":"gpt"}' } });
  await userEvent.click(screen.getByRole("button", { name: "保存配置" }));

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/agents/agent-1",
    expect.objectContaining({
      method: "PATCH",
      body: expect.stringContaining('"agentRuntimeType":"codex_local"'),
    }),
  );

  await userEvent.click(screen.getByRole("link", { name: "运行" }));
  const detail = screen.getByTestId("agent-runs-detail-pane");
  expect(await within(detail).findByText("failed")).toBeInTheDocument();
  expect(within(detail).getByText("runtime_error")).toBeInTheDocument();
  expect(within(detail).getByText("boot ok")).toBeInTheDocument();
  expect(within(detail).getAllByText("model missing").length).toBeGreaterThanOrEqual(1);
  expect(within(detail).getByText(/executionWorkspaceId/)).toBeInTheDocument();
  expect(within(detail).getByText("runtime.stderr")).toBeInTheDocument();
  expect(screen.getByTestId("agent-runs-list-pane")).toBeInTheDocument();
});

it("validates opencode local model before saving agent configuration", async () => {
  const agent = { id: "agent-1", orgId: "org-1", name: "Builder", role: "engineer", status: "idle", agentRuntimeType: "process", agentRuntimeConfig: {}, runtimeConfig: {}, budgetMonthlyCents: 0, capabilities: null, reportsTo: null };
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/agents/agent-1" && init?.method === "GET") return respond(agent);
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") return respond([agent]);
    return respond({ ...agent, agentRuntimeType: "opencode_local" });
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/agents/agent-1/configuration");
  await userEvent.selectOptions(await screen.findByLabelText("Runtime"), "opencode_local");
  fireEvent.change(screen.getByLabelText("Agent runtime config"), { target: { value: "{}" } });
  await userEvent.click(screen.getByRole("button", { name: "保存配置" }));
  expect(screen.getByText("OpenCode model 必须使用 provider/model 格式，例如 openai/gpt-5。")).toBeInTheDocument();
  expect(fetchMock).not.toHaveBeenCalledWith(
    "/api/agents/agent-1",
    expect.objectContaining({ method: "PATCH" }),
  );

  fireEvent.change(screen.getByLabelText("Agent runtime config"), { target: { value: '{"model":"openai/gpt-5"}' } });
  await userEvent.click(screen.getByRole("button", { name: "保存配置" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/agents/agent-1",
    expect.objectContaining({
      method: "PATCH",
      body: expect.stringContaining('"model":"openai/gpt-5"'),
    }),
  );
});

it("shows configuration revisions, rolls back, and resets runtime session", async () => {
  const agent = { id: "agent-1", orgId: "org-1", name: "Builder", role: "engineer", status: "idle", agentRuntimeType: "process", agentRuntimeConfig: {}, runtimeConfig: {}, budgetMonthlyCents: 0, capabilities: null, reportsTo: null };
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/agents/agent-1" && init?.method === "GET") return respond(agent);
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") return respond([agent]);
    if (path === "/api/agents/agent-1/runtime-state" && init?.method === "GET") {
      return respond({ agentId: "agent-1", sessionDisplayId: "session-1", lastRunStatus: null, totalInputTokens: 0, totalOutputTokens: 0, totalCostCents: 0, lastError: null });
    }
    if (path === "/api/agents/agent-1/configuration" && init?.method === "GET") {
      return respond({ ...agent, updatedAt: "2026-05-28T08:00:00Z" });
    }
    if (path === "/api/agents/agent-1/task-sessions" && init?.method === "GET") {
      return respond([{ id: "session-row-1", agentId: "agent-1", taskKey: "issue-1", sessionDisplayId: "session-1", status: "active", createdAt: "", updatedAt: "2026-05-28T09:00:00Z" }]);
    }
    if (path === "/api/agents/agent-1/config-revisions" && init?.method === "GET") {
      return respond([{ id: "revision-1", agentId: "agent-1", createdAt: "2026-05-28T00:00:00Z", runtimeConfig: {} }]);
    }
    return respond({ id: "agent-1" });
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/agents/agent-1/configuration");
  expect(await screen.findByRole("heading", { name: "配置快照" })).toBeInTheDocument();
  expect(await screen.findByText("2026-05-28T08:00:00Z")).toBeInTheDocument();
  expect(await screen.findByText("issue-1")).toBeInTheDocument();
  expect(await screen.findByText("Config Revisions")).toBeInTheDocument();
  expect(await screen.findByText("revision-1")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "回滚" }));
  await userEvent.click(screen.getByRole("button", { name: "重置会话" }));

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/agents/agent-1/config-revisions/revision-1/rollback",
    expect.objectContaining({ method: "POST" }),
  );
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/agents/agent-1/runtime-state/reset-session",
    expect.objectContaining({ method: "POST", body: JSON.stringify({}) }),
  );
});

it("shows an empty skill list without placeholder skills", async () => {
  const agent = {
    id: "agent-1",
    orgId: "org-1",
    name: "Builder",
    role: "engineer",
    status: "idle",
    agentRuntimeType: "codex_local",
    agentRuntimeConfig: {},
    runtimeConfig: {},
    budgetMonthlyCents: 0,
    desiredSkills: [],
  };
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/agents/agent-1" && init?.method === "GET") return respond(agent);
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") return respond([agent]);
    if (path === "/api/agents/agent-1/runtime-state" && init?.method === "GET") return respond({});
    if (path === "/api/agents/agent-1/skills" && init?.method === "GET") {
      return respond({ agentRuntimeType: "codex_local", supported: true, mode: "persistent", desiredSkills: [], entries: [], warnings: [] });
    }
    if (path === "/api/agents/agent-1/skills/analytics?windowDays=30" && init?.method === "GET") {
      return respond({ agentId: "agent-1", windowDays: 30, totalCount: 0, totalRunsWithSkills: 0, skills: [] });
    }
    return respond({});
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/agents/agent-1/skills");

  expect(await screen.findByRole("heading", { name: "技能管理" })).toBeInTheDocument();
  expect(await screen.findByRole("heading", { name: "使用分析" })).toBeInTheDocument();
  expect(screen.queryByText("No skills.")).not.toBeInTheDocument();
  expect(screen.getByText("组织技能")).toBeInTheDocument();
  expect(screen.getByText("外部技能")).toBeInTheDocument();
  expect(screen.queryByText("Review")).not.toBeInTheDocument();
  expect(screen.queryByText("Debug")).not.toBeInTheDocument();
  expect(screen.queryByText("Deploy")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Show" })).not.toBeInTheDocument();
});

it("manages runtime adapter probes and skills from configuration", async () => {
  const agent = {
    id: "agent-1",
    orgId: "org-1",
    name: "Builder",
    role: "engineer",
    status: "idle",
    agentRuntimeType: "codex_local",
    agentRuntimeConfig: { model: "gpt-5" },
    runtimeConfig: {},
    budgetMonthlyCents: 0,
    capabilities: null,
    desiredSkills: ["review"],
    reportsTo: null,
  };
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/agents/agent-1" && init?.method === "GET") return respond(agent);
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") return respond([agent]);
    if (path === "/api/agents/agent-1/runtime-state" && init?.method === "GET") {
      return respond({ agentId: "agent-1", sessionDisplayId: "session-1", lastRunStatus: null, totalInputTokens: 0, totalOutputTokens: 0, totalCostCents: 0, lastError: null });
    }
    if (path === "/api/agents/agent-1/config-revisions" && init?.method === "GET") return respond([]);
    if (path === "/api/orgs/org-1/adapters/codex_local/models" && init?.method === "GET") {
      return respond([{ id: "gpt-5", label: "GPT-5" }]);
    }
    if (path === "/api/orgs/org-1/adapters/codex_local" && init?.method === "GET") {
      return respond({
        type: "codex_local",
        capabilities: { models: true, skills: true, quotaWindows: true },
        supportsLocalAgentJwt: true,
        agentConfigurationDoc: "Set model and cwd before running.",
      });
    }
    if (path === "/api/orgs/org-1/adapters/codex_local/quota-windows" && init?.method === "GET") {
      return respond({ provider: "openai", ok: false, error: "not configured", windows: [] });
    }
    if (path === "/api/orgs/org-1/adapters/codex_local/test-environment" && init?.method === "POST") {
      return respond({ agentRuntimeType: "codex_local", status: "pass", checks: [{ id: "cwd", label: "CWD", status: "pass", message: "ok" }] });
    }
    if (path === "/api/agents/agent-1/skills" && init?.method === "GET") {
      return respond({
        agentRuntimeType: "codex_local",
        supported: true,
        mode: "persistent",
        desiredSkills: ["review", "deploy"],
        entries: [
          {
            key: "review",
            selectionKey: "bundled:review",
            runtimeName: "Review",
            sourceClass: "bundled",
            origin: "bundled",
            state: "installed",
            alwaysEnabled: true,
            originLabel: "Bundled reference",
            locationLabel: "bundled skills",
            version: "1.0",
            enabled: true,
            tags: ["quality"],
            description:
              "Turn the current conversation's workflow into a reusable agent skill. Use this whenever the user wants to make a workflow reusable.",
            prompt: "Review carefully.",
          },
          {
            key: "deploy",
            selectionKey: "agent:deploy",
            runtimeName: "Deploy",
            sourceClass: "agent_home",
            origin: "user_installed",
            state: "external",
            version: "1.0",
            enabled: true,
            tags: ["release"],
            markdown: "---\ndescription: Deploy safely from frontmatter\n---\n\nDeploy carefully.",
          },
          {
            key: "debug",
            selectionKey: "external:debug",
            runtimeName: "Debug",
            sourceClass: "external",
            origin: "external",
            state: "missing",
            version: "1.0",
            enabled: false,
            tags: ["ops"],
            description: "Debug failures",
            prompt: "Debug carefully.",
          },
        ],
        warnings: ["debug missing from managed home"],
      });
    }
    if (path === "/api/agents/agent-1/skills/analytics?windowDays=30" && init?.method === "GET") {
      return respond({ agentId: "agent-1", windowDays: 30, totalCount: 7, totalRunsWithSkills: 3, skills: [{ key: "review" }] });
    }
    return respond({ agentRuntimeType: "codex_local", supported: true, mode: "persistent", desiredSkills: ["review", "debug"], entries: [] });
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/agents/agent-1/configuration");
  expect(await screen.findByText("Runtime Adapter")).toBeInTheDocument();
  expect(await screen.findByText("GPT-5")).toBeInTheDocument();
  expect(await screen.findByText("not configured")).toBeInTheDocument();
  expect(await screen.findByText("Set model and cwd before running.")).toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: "测试环境" }));
  expect(await screen.findByText("CWD")).toBeInTheDocument();

  await userEvent.click(screen.getByRole("link", { name: "技能" }));
  expect(await screen.findByRole("heading", { name: "技能管理" })).toBeInTheDocument();
  expect(await screen.findByText("使用分析")).toBeInTheDocument();
  expect(screen.queryByRole("tab")).not.toBeInTheDocument();
  expect(await screen.findByText("Review")).toBeInTheDocument();
  expect(await screen.findByText("debug missing from managed home")).toBeInTheDocument();
  expect(await screen.findByText("installed")).toBeInTheDocument();
  expect(await screen.findByText("external")).toBeInTheDocument();
  expect(await screen.findByText("missing")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Show" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Hide" })).not.toBeInTheDocument();
  expect(document.querySelector(".agent-skill-detail-card")).not.toBeInTheDocument();
  await userEvent.click(screen.getByText("Review"));
  expect(screen.getByText(/Turn the current conversation's workflow into a reusable agent skill/)).toBeInTheDocument();
  expect(screen.getByText("每次智能体运行都会自动加载。")).toBeInTheDocument();
  expect(screen.getByText("系统内置")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "派生" })).toBeInTheDocument();
  await userEvent.click(screen.getByText("Deploy"));
  expect(screen.getByText("Deploy safely from frontmatter")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "取消使用" }));
  await userEvent.click(screen.getByText("Debug"));
  await userEvent.click(screen.getByRole("button", { name: "使用" }));
  await userEvent.click(screen.getByRole("button", { name: "创建技能" }));
  const dialog = screen.getByRole("dialog");
  await userEvent.type(within(dialog).getByLabelText("名称"), "Incident Response");
  await userEvent.type(within(dialog).getByLabelText("Short name"), "incident-response");
  await userEvent.type(within(dialog).getByLabelText("描述"), "Handle incidents");
  await userEvent.type(within(dialog).getByLabelText("技能内容"), "schema_version: 1\nprompt: handle it");
  await userEvent.click(within(dialog).getByRole("button", { name: "创建" }));

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/adapters/codex_local/test-environment",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ agentRuntimeConfig: { model: "gpt-5" } }),
    }),
  );
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/agents/agent-1/skills/sync",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ desiredSkills: ["review"] }),
    }),
  );
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/agents/agent-1/skills/enable",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ skills: ["external:debug"] }),
    }),
  );
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/agents/agent-1/skills/private",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        name: "Incident Response",
        slug: "incident-response",
        description: "Handle incidents",
        markdown: "schema_version: 1\nprompt: handle it",
      }),
    }),
  );
});
