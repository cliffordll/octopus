import { cleanup, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { renderApp, respond } from "./render-app";

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.unstubAllGlobals();
});

it("shows an issue and records comments and review decisions", async () => {
  const issue = {
    id: "issue-1",
    orgId: "org-1",
    identifier: "OCT-1",
    title: "实现登录流程",
    description: "接入页面",
    status: "in_review",
    priority: "high",
    projectId: null,
    goalId: null,
    parentId: null,
    assigneeAgentId: "agent-1",
    assigneeUserId: null,
    reviewerAgentId: "agent-1",
    reviewerUserId: null,
    originKind: "manual",
    originId: null,
    issueNumber: 1,
    requestDepth: 0,
    startedAt: null,
    completedAt: null,
    workProducts: [
      {
        id: "wp-1",
        orgId: "org-1",
        projectId: "project-1",
        issueId: "issue-1",
        executionWorkspaceId: "exec-1",
        runtimeServiceId: "svc-1",
        type: "pull_request",
        provider: "github",
        externalId: "42",
        assetId: "asset-product-1",
        contentPath: "/api/assets/asset-product-1/content",
        contentType: "text/markdown",
        byteSize: 128,
        title: "登录流程 PR",
        url: "https://example.com/pr/42",
        status: "open",
        reviewState: "pending",
        isPrimary: true,
        healthStatus: "healthy",
        summary: "实现登录流程并等待 review",
        metadata: null,
        createdByRunId: "run-1",
        createdAt: "2026-05-28T09:00:00Z",
        updatedAt: "2026-05-28T10:00:00Z",
      },
    ],
    createdAt: "",
    updatedAt: "",
  };
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/issues" && init?.method === "GET") {
      return respond([issue]);
    }
    if (path === "/api/orgs/org-1/projects" && init?.method === "GET") {
      return respond([{ id: "project-1", orgId: "org-1", name: "控制台", status: "in_progress", urlKey: "console" }]);
    }
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") {
      return respond([{ id: "agent-1", orgId: "org-1", name: "Builder", role: "engineer", status: "idle" }]);
    }
    if (path === "/api/orgs/org-1/goals" && init?.method === "GET") {
      return respond([{ id: "goal-1", orgId: "org-1", title: "提升体验", level: "organization", status: "active", parentId: null, ownerAgentId: null }]);
    }
    if (path === "/api/orgs/org-1/heartbeat-runs" && init?.method === "GET") {
      return respond([]);
    }
    if (path === "/api/issues/issue-1/heartbeat-runs" && init?.method === "GET") {
      return respond([]);
    }
    if (path === "/api/issues/issue-1/heartbeat-context" && init?.method === "GET") {
      return respond({ issueId: "issue-1" });
    }
    if (path === "/api/issues/issue-1/comments" && init?.method === "GET") {
      return respond([{ id: "c-1", issueId: "issue-1", body: "已有讨论" }]);
    }
    if (path === "/api/issues/issue-1/attachments" && init?.method === "GET") {
      return respond([
        {
          id: "attachment-1",
          orgId: "org-1",
          issueId: "issue-1",
          issueCommentId: null,
          assetId: "asset-1",
          usage: "evidence",
          provider: "local",
          objectKey: "issue/attachments/note.txt",
          contentType: "text/plain",
          byteSize: 12,
          sha256: "abc",
          originalFilename: "note.txt",
          createdAt: "",
          updatedAt: "",
          contentPath: "/api/assets/asset-1/content",
        },
      ]);
    }
    if (path === "/api/orgs/org-1/issues/issue-1/attachments" && init?.method === "POST") {
      return respond({ id: "attachment-2", originalFilename: "upload.txt" }, 201);
    }
    if (path === "/api/orgs/org-1/issues" && init?.method === "POST") {
      return respond({ ...issue, id: "issue-child", identifier: "OCT-2", title: "新增子任务", parentId: "issue-1" }, 201);
    }
    if (path === "/api/attachments/attachment-1" && init?.method === "DELETE") {
      return respond({}, 204);
    }
    return respond(issue);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/issues/issue-1");
  expect(await screen.findByRole("heading", { name: "实现登录流程" })).toBeInTheDocument();
  const properties = screen.getByRole("region", { name: "任务属性" });
  expect(properties).toHaveTextContent("属性");
  expect(properties).toHaveTextContent("编号");
  expect(properties).toHaveTextContent("层级");
  expect(properties).toHaveTextContent("已启动");
  expect(properties).toHaveTextContent("已完成");
  await userEvent.selectOptions(screen.getByLabelText("状态"), "in_progress");
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/issues/issue-1",
    expect.objectContaining({ method: "PATCH", body: JSON.stringify({ status: "in_progress" }) }),
  );
  await userEvent.selectOptions(screen.getByLabelText("优先级"), "critical");
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/issues/issue-1",
    expect.objectContaining({ method: "PATCH", body: JSON.stringify({ priority: "critical" }) }),
  );
  expect(screen.getByRole("region", { name: "工作产物" })).toHaveTextContent("登录流程 PR");
  expect(screen.getByRole("region", { name: "工作产物" })).toHaveTextContent("pull_request");
  expect(screen.getByRole("link", { name: "下载产物" })).toHaveAttribute("href", "/api/assets/asset-product-1/content");
  expect(screen.getByRole("link", { name: "打开产物" })).toHaveAttribute("href", "https://example.com/pr/42");
  expect(await screen.findByRole("region", { name: "附件" })).toHaveTextContent("note.txt");
  expect(screen.getByRole("link", { name: "下载" })).toHaveAttribute("href", "/api/assets/asset-1/content");
  expect(await screen.findByText("已有讨论")).toBeInTheDocument();
  expect(JSON.parse(localStorage.getItem("octopus:recent-issues:org-1") ?? "[]")).toEqual([
    { id: "issue-1", title: "实现登录流程", identifier: "OCT-1", status: "in_review" },
  ]);

  await userEvent.type(screen.getByLabelText("添加评论"), "准备合并");
  await userEvent.click(screen.getByRole("button", { name: "发送评论" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/issues/issue-1/comments",
    expect.objectContaining({ method: "POST" }),
  );

  await userEvent.upload(screen.getByLabelText("附件文件"), new File(["upload"], "upload.txt", { type: "text/plain" }));
  await userEvent.click(screen.getByRole("button", { name: "上传附件" }));
  expect(await screen.findByRole("status")).toHaveTextContent("已上传 upload.txt");
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/issues/issue-1/attachments",
    expect.objectContaining({ method: "POST", body: expect.any(FormData) }),
  );

  await userEvent.click(screen.getByRole("button", { name: "删除" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/attachments/attachment-1",
    expect.objectContaining({ method: "DELETE" }),
  );

  await userEvent.click(screen.getByRole("button", { name: "通过评审" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/issues/issue-1/review-decision",
    expect.objectContaining({ method: "POST" }),
  );

  await userEvent.type(screen.getByLabelText("子任务名称"), "新增子任务");
  await userEvent.click(screen.getByRole("button", { name: "添加子任务" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/issues",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        title: "新增子任务",
        parentId: "issue-1",
        projectId: null,
        goalId: null,
        assigneeAgentId: "agent-1",
        reviewerAgentId: "agent-1",
        priority: "high",
        status: "todo",
      }),
    }),
  );
});

it("executes an assigned issue through the issue execution route", async () => {
  const issue = {
    id: "issue-1",
    orgId: "org-1",
    identifier: "OCT-1",
    title: "实现登录流程",
    description: "接入页面",
    status: "todo",
    priority: "high",
    projectId: "project-1",
    goalId: "goal-1",
    parentId: null,
    assigneeAgentId: "agent-1",
    assigneeUserId: null,
    reviewerAgentId: null,
    reviewerUserId: null,
    originKind: "manual",
    originId: null,
    issueNumber: 1,
    requestDepth: 0,
    startedAt: null,
    completedAt: null,
    workProducts: [],
    createdAt: "",
    updatedAt: "",
  };
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") {
      return respond([{ id: "agent-1", orgId: "org-1", name: "Builder", role: "engineer", status: "idle" }]);
    }
    if (path === "/api/orgs/org-1/projects" && init?.method === "GET") {
      return respond([{ id: "project-1", orgId: "org-1", name: "控制台", status: "in_progress", urlKey: "console" }]);
    }
    if (path === "/api/orgs/org-1/goals" && init?.method === "GET") {
      return respond([{ id: "goal-1", orgId: "org-1", title: "提升体验", level: "organization", status: "active", parentId: null, ownerAgentId: null }]);
    }
    if (path === "/api/orgs/org-1/heartbeat-runs" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/heartbeat-runs" && init?.method === "GET") {
      return respond([
        {
          id: "run-1",
          orgId: "org-1",
          agentId: "agent-1",
          issueId: "issue-1",
          issueIdentifier: "OCT-1",
          issueTitle: "实现登录流程",
          invocationSource: "assignment",
          status: "queued",
          createdAt: "2026-06-02T10:00:00Z",
        },
      ]);
    }
    if (path === "/api/issues/issue-1/heartbeat-context" && init?.method === "GET") {
      return respond({ issueId: "issue-1" });
    }
    if (path === "/api/issues/issue-1/comments" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/attachments" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1" && init?.method === "PATCH") {
      return respond({ ...issue, status: "in_progress", startedAt: "2026-06-02T10:00:00Z" });
    }
    if (path === "/api/issues/issue-1/execute" && init?.method === "POST") {
      return respond({ id: "run-1", orgId: "org-1", agentId: "agent-1", status: "queued" }, 202);
    }
    if (path === "/api/heartbeat-runs/run-1" && init?.method === "GET") {
      return respond({
        id: "run-1",
        orgId: "org-1",
        agentId: "agent-1",
        invocationSource: "assignment",
          triggerDetail: "manual",
          status: "queued",
          createdAt: "2026-06-02T10:00:00Z",
          stdoutExcerpt: "queued output",
          resultJson: { summary: "等待执行" },
          contextSnapshot: { issueId: "issue-1" },
        });
    }
    if (path === "/api/heartbeat-runs/run-1/events" && init?.method === "GET") {
      return respond([
        { id: 1, runId: "run-1", agentId: "agent-1", seq: 1, eventType: "heartbeat.queued", message: "已入队", createdAt: "2026-06-02T10:00:00Z" },
        { id: 2, runId: "run-1", agentId: "agent-1", seq: 2, eventType: "runtime.text", stream: "stdout", message: "Agent 正在处理任务", createdAt: "2026-06-02T10:00:01Z" },
        { id: 3, runId: "run-1", agentId: "agent-1", seq: 3, eventType: "step_start", message: "low value", createdAt: "2026-06-02T10:00:02Z" },
      ]);
    }
    if (path === "/api/heartbeat-runs/run-1/workspace-operations" && init?.method === "GET") {
      return respond([{ id: "op-1", orgId: "org-1", heartbeatRunId: "run-1", phase: "setup", status: "running", command: "npm test", stdoutExcerpt: "workspace output" }]);
    }
    if (path === "/api/heartbeat-runs/run-1/cancel" && init?.method === "POST") {
      return respond({ id: "run-1", orgId: "org-1", agentId: "agent-1", invocationSource: "assignment", status: "cancelled" });
    }
    return respond(issue);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/issues/issue-1");
  const executeButton = await screen.findByRole("button", { name: "执行任务" });
  expect(executeButton).not.toHaveAttribute("aria-disabled");
  await userEvent.click(executeButton);
  expect(screen.getByRole("button", { name: "通过评审" })).toHaveAttribute("aria-disabled", "true");
  expect(screen.getByRole("button", { name: "请求修改" })).toHaveAttribute("aria-disabled", "true");
  expect(screen.getByRole("button", { name: "标记待评审" })).toHaveAttribute("aria-disabled", "true");
  await userEvent.click(screen.getByRole("button", { name: "通过评审" }));
  expect(screen.getByRole("status")).toHaveTextContent("请先设置 Reviewer，当前任务不能评审。");

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/issues/issue-1",
    expect.objectContaining({ method: "PATCH", body: JSON.stringify({ status: "in_progress" }) }),
  );
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/issues/issue-1/execute",
    expect.objectContaining({ method: "POST", body: "{}" }),
  );
  expect(await screen.findByRole("region", { name: "执行记录" })).toHaveTextContent("运行输出摘要");
  expect(screen.getByRole("region", { name: "执行记录" })).toHaveTextContent("等待执行");
  expect(screen.getByRole("region", { name: "动态" })).not.toHaveTextContent("等待执行");
  expect(await screen.findByRole("region", { name: "执行输出" })).toHaveTextContent("等待执行");
  expect(screen.getByRole("heading", { name: "运行详情" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "事件" })).toBeInTheDocument();
  expect(screen.getByText("查看 result/context/usage")).toBeInTheDocument();
  expect(await screen.findByText("已入队")).toBeInTheDocument();
  expect(screen.getByText("Agent 回复")).toBeInTheDocument();
  expect(screen.getByText("Agent 正在处理任务")).toBeInTheDocument();
  expect(screen.queryByText("queued output")).not.toBeInTheDocument();
  expect(screen.queryByText("workspace output")).not.toBeInTheDocument();
  expect(screen.queryByText("low value")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "展开" }));
  expect(screen.getByText("queued output")).toBeInTheDocument();
  expect(screen.getByText("workspace output")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /显示低价值事件/ }));
  expect(screen.getByText("low value")).toBeInTheDocument();
  expect(fetchMock).not.toHaveBeenCalledWith(
    "/api/heartbeat-runs/run-1/log",
    expect.objectContaining({ method: "GET" }),
  );
  await userEvent.click(screen.getByRole("button", { name: "取消运行" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/heartbeat-runs/run-1/cancel",
    expect.objectContaining({ method: "POST" }),
  );
});

it("explains why an unassigned issue cannot be executed", async () => {
  const issue = {
    id: "issue-1",
    orgId: "org-1",
    identifier: "OCT-1",
    title: "实现登录流程",
    description: "接入页面",
    status: "todo",
    priority: "high",
    projectId: null,
    goalId: null,
    parentId: null,
    assigneeAgentId: null,
    assigneeUserId: null,
    reviewerAgentId: null,
    reviewerUserId: null,
    originKind: "manual",
    originId: null,
    issueNumber: 1,
    requestDepth: 0,
    startedAt: null,
    completedAt: null,
    workProducts: [],
    createdAt: "",
    updatedAt: "",
  };
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") return respond([]);
    if (path === "/api/orgs/org-1/projects" && init?.method === "GET") return respond([]);
    if (path === "/api/orgs/org-1/goals" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/comments" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/attachments" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/heartbeat-runs" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/heartbeat-context" && init?.method === "GET") return respond({ issueId: "issue-1" });
    return respond(issue);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/issues/issue-1");
  const executeButton = await screen.findByRole("button", { name: "执行任务" });
  expect(executeButton).toHaveAttribute("aria-disabled", "true");
  expect(executeButton).not.toBeDisabled();
  await userEvent.click(executeButton);
  expect(screen.getByRole("status")).toHaveTextContent("请先分配负责人，再执行任务。");
  expect(fetchMock).not.toHaveBeenCalledWith(
    "/api/issues/issue-1/execute",
    expect.objectContaining({ method: "POST" }),
  );
});
