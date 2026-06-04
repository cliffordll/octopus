import { cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { renderApp, respond, respondStream } from "./render-app";

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.unstubAllGlobals();
}, 10000);

it("shows an issue and records comments and review decisions", async () => {
  const longIssueTitle = "实现登录流程并处理一个非常长的任务名称用于验证顶部操作按钮不会被标题挤压变形";
  const issue = {
    id: "issue-1",
    orgId: "org-1",
    identifier: "OCT-1",
    title: longIssueTitle,
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
        sha256: "def",
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
      {
        id: "wp-2",
        orgId: "org-1",
        projectId: "project-1",
        issueId: "issue-1",
        executionWorkspaceId: null,
        runtimeServiceId: null,
        type: "artifact",
        provider: "minio",
        externalId: null,
        assetId: null,
        contentPath: null,
        contentType: null,
        byteSize: null,
        sha256: null,
        title: "运行摘要",
        url: null,
        status: "open",
        reviewState: "pending",
        isPrimary: false,
        healthStatus: "unknown",
        summary: "只有摘要，没有下载对象",
        metadata: null,
        createdByRunId: null,
        createdAt: "2026-05-28T09:00:00Z",
        updatedAt: "2026-05-28T10:00:00Z",
      },
    ],
    createdAt: "",
    updatedAt: "",
  };
  const childIssue = {
    ...issue,
    id: "issue-child",
    identifier: "OCT-2",
    title: "新增子任务",
    status: "todo",
    parentId: "issue-1",
    requestDepth: 1,
  };
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/issues" && init?.method === "GET") {
      return respond([issue]);
    }
    if (path === "/api/orgs/org-1/issues?parentId=issue-1" && init?.method === "GET") {
      return respond([childIssue]);
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
    if (path === "/api/issues/issue-1/documents" && init?.method === "GET") {
      return respond([{
        id: "doc-1",
        orgId: "org-1",
        issueId: "issue-1",
        key: "plan",
        title: "执行计划",
        format: "markdown",
        latestRevisionId: "rev-1",
        latestRevisionNumber: 1,
        createdByAgentId: null,
        createdByUserId: "board",
        updatedByAgentId: null,
        updatedByUserId: "board",
        createdAt: "2026-05-28T09:00:00Z",
        updatedAt: "2026-05-28T10:00:00Z",
      }]);
    }
    if (path === "/api/issues/issue-1/documents/plan" && init?.method === "GET") {
      return respond({
        id: "doc-1",
        orgId: "org-1",
        issueId: "issue-1",
        key: "plan",
        title: "执行计划",
        format: "markdown",
        latestRevisionId: "rev-1",
        latestRevisionNumber: 1,
        body: "## 执行步骤",
        createdByAgentId: null,
        createdByUserId: "board",
        updatedByAgentId: null,
        updatedByUserId: "board",
        createdAt: "2026-05-28T09:00:00Z",
        updatedAt: "2026-05-28T10:00:00Z",
      });
    }
    if (path === "/api/issues/issue-1/documents/plan/revisions" && init?.method === "GET") {
      return respond([{
        id: "rev-1",
        orgId: "org-1",
        documentId: "doc-1",
        issueId: "issue-1",
        key: "plan",
        revisionNumber: 1,
        body: "## 执行步骤",
        changeSummary: "初始版本",
        createdByAgentId: null,
        createdByUserId: "board",
        createdAt: "2026-05-28T10:00:00Z",
      }]);
    }
    if (path === "/api/issues/issue-1/documents/plan" && init?.method === "PUT") {
      return respond({
        id: "doc-1",
        orgId: "org-1",
        issueId: "issue-1",
        key: "plan",
        title: "执行计划更新",
        format: "markdown",
        latestRevisionId: "rev-2",
        latestRevisionNumber: 2,
        body: "## 执行步骤\n\n补充内容",
        createdByAgentId: null,
        createdByUserId: "board",
        updatedByAgentId: null,
        updatedByUserId: "board",
        createdAt: "2026-05-28T09:00:00Z",
        updatedAt: "2026-05-28T10:30:00Z",
      });
    }
    if (path === "/api/issues/issue-1/documents/plan" && init?.method === "DELETE") {
      return respond({ ok: true });
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
      return respond(childIssue, 201);
    }
    if (path === "/api/attachments/attachment-1" && init?.method === "DELETE") {
      return respond({}, 204);
    }
    if (path === "/api/work-products/wp-2" && init?.method === "DELETE") {
      return respond(issue.workProducts[1]);
    }
    return respond(issue);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/issues/issue-1");
  expect(await screen.findByRole("heading", { name: longIssueTitle })).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "复制 ID" })[0]).toBeInTheDocument();
  expect(screen.getAllByRole("link", { name: "聊天" })[0]).toBeInTheDocument();
  const properties = screen.getByRole("region", { name: "任务属性" });
  expect(properties).toHaveTextContent("属性");
  expect(properties).toHaveTextContent("编号");
  expect(properties).toHaveTextContent("层级");
  expect(properties).toHaveTextContent("已启动");
  expect(properties).toHaveTextContent("已完成");
  await userEvent.selectOptions(screen.getByLabelText("任务阶段"), "in_progress");
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
  expect(screen.getByRole("region", { name: "工作产物" })).toHaveTextContent("运行摘要");
  expect(screen.getByRole("region", { name: "工作产物" })).toHaveTextContent("pull_request");
  expect(screen.getByRole("region", { name: "工作产物" })).toHaveTextContent("UI 只展示下载入口");
  expect(screen.getByRole("link", { name: "下载产物文件" })).toHaveAttribute("href", "/api/assets/asset-product-1/content");
  expect(screen.getByRole("link", { name: "预览内容" })).toHaveAttribute("href", "/api/assets/asset-product-1/content");
  expect(screen.getByRole("link", { name: "打开产物" })).toHaveAttribute("href", "https://example.com/pr/42");
  expect(screen.getByRole("region", { name: "工作产物" })).toHaveTextContent("不可下载");
  expect(await screen.findByRole("region", { name: "任务文档" })).toHaveTextContent("执行计划");
  expect(await screen.findByDisplayValue("## 执行步骤")).toBeInTheDocument();
  await userEvent.click(within(screen.getByRole("region", { name: "任务文档" })).getByRole("button", { name: "隐藏" }));
  expect(screen.queryByDisplayValue("## 执行步骤")).not.toBeInTheDocument();
  await userEvent.click(within(screen.getByRole("region", { name: "任务文档" })).getByRole("button", { name: "显示" }));
  expect(await screen.findByDisplayValue("## 执行步骤")).toBeInTheDocument();
  await userEvent.clear(screen.getByLabelText("标题"));
  await userEvent.type(screen.getByLabelText("标题"), "执行计划更新");
  await userEvent.type(screen.getByLabelText("正文"), "\n\n补充内容");
  await userEvent.type(screen.getByLabelText("变更说明"), "补充步骤");
  await userEvent.click(screen.getByRole("button", { name: "保存文档" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/issues/issue-1/documents/plan",
    expect.objectContaining({
      method: "PUT",
      body: JSON.stringify({
        title: "执行计划更新",
        format: "markdown",
        body: "## 执行步骤\n\n补充内容",
        changeSummary: "补充步骤",
        baseRevisionId: "rev-1",
      }),
    }),
  );
  await userEvent.click(screen.getByText("历史版本"));
  expect(await screen.findByText(/初始版本/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "删除文档" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/issues/issue-1/documents/plan",
    expect.objectContaining({ method: "DELETE" }),
  );
  await userEvent.click(screen.getAllByRole("button", { name: "删除产物" })[1]);
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/work-products/wp-2",
    expect.objectContaining({ method: "DELETE" }),
  );
  expect(await screen.findByRole("region", { name: "附件" })).toHaveTextContent("note.txt");
  expect(screen.getByRole("link", { name: "下载" })).toHaveAttribute("href", "/api/assets/asset-1/content");
  expect(await screen.findByText("已有讨论")).toBeInTheDocument();
  expect(JSON.parse(localStorage.getItem("octopus:recent-issues:org-1") ?? "[]")).toEqual([
    { id: "issue-1", title: longIssueTitle, identifier: "OCT-1", status: "in_review" },
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
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/issues?parentId=issue-1",
    expect.objectContaining({ method: "GET" }),
  );
  expect(screen.getByRole("region", { name: "子任务" })).toHaveTextContent("新增子任务");
  expect(fetchMock).not.toHaveBeenCalledWith(
    "/api/issues/issue-child",
    expect.objectContaining({ method: "GET" }),
  );
});

it("executes an assigned issue through the issue execution route", async () => {
  let hasExecuted = false;
  const longAgentReply = `${"长回复内容。".repeat(130)}最终结论`;
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
      return respond(hasExecuted ? [
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
      ] : []);
    }
    if (path === "/api/issues/issue-1/heartbeat-context" && init?.method === "GET") {
      return respond({ issueId: "issue-1" });
    }
    if (path === "/api/issues/issue-1/comments" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/attachments" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/documents" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1" && init?.method === "PATCH") {
      return respond({ ...issue, status: "in_progress", startedAt: "2026-06-02T10:00:00Z" });
    }
    if (path === "/api/issues/issue-1/execute" && init?.method === "POST") {
      hasExecuted = true;
      return respond({ id: "run-1", orgId: "org-1", agentId: "agent-1", status: "queued" }, 202);
    }
    if (path.startsWith("/api/heartbeat-runs/run-1/stream") && init?.method === "GET") {
      return respondStream([
        {
          type: "run",
          run: {
            id: "run-1",
            orgId: "org-1",
            agentId: "agent-1",
            invocationSource: "assignment",
            status: "running",
            resultJson: { summary: "等待执行" },
          },
        },
        {
          type: "event",
          event: {
            id: 4,
            runId: "run-1",
            agentId: "agent-1",
            seq: 4,
            eventType: "runtime.text",
            stream: "stdout",
            message: "Stream 正在输出",
            createdAt: "2026-06-02T10:00:03Z",
          },
        },
        {
          type: "event",
          event: {
            id: 5,
            runId: "run-1",
            agentId: "agent-1",
            seq: 5,
            eventType: "runtime.text",
            stream: "stdout",
            message: longAgentReply,
            createdAt: "2026-06-02T10:00:04Z",
          },
        },
        { type: "log", content: "stream log chunk", nextOffset: 16, eof: false },
      ]);
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
  const executeButton = await screen.findByRole("button", { name: "启动执行" });
  expect(executeButton).not.toHaveAttribute("aria-disabled");
  await userEvent.click(executeButton);
  expect(screen.getByRole("button", { name: "通过评审" })).toHaveAttribute("aria-disabled", "true");
  expect(screen.getByRole("button", { name: "请求修改" })).toHaveAttribute("aria-disabled", "true");
  expect(screen.getByRole("button", { name: "标记待评审" })).toHaveAttribute("aria-disabled", "true");
  await userEvent.click(screen.getByRole("button", { name: "通过评审" }));
  expect(screen.getByText("请先设置 Reviewer，当前任务不能评审。")).toBeInTheDocument();
  expect(screen.getByText("已创建运行 run-1")).toBeInTheDocument();

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/issues/issue-1",
    expect.objectContaining({ method: "PATCH", body: JSON.stringify({ status: "in_progress" }) }),
  );
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/issues/issue-1/execute",
    expect.objectContaining({ method: "POST", body: "{}" }),
  );
  expect(await screen.findByRole("region", { name: "运行记录" })).toHaveTextContent("运行输出摘要");
  expect(screen.getByRole("region", { name: "运行记录" })).toHaveTextContent("等待执行");
  expect(screen.getByRole("region", { name: "动态" })).not.toHaveTextContent("等待执行");
  expect(await screen.findByRole("region", { name: "执行输出" })).toHaveTextContent("等待执行");
  expect(screen.getByRole("region", { name: "执行输出" })).toHaveTextContent("动态刷新中");
  expect(screen.getByRole("region", { name: "执行输出" })).toHaveTextContent("运行中会通过 stream 动态刷新事件和输出。");
  expect(await screen.findByText("Stream 正在输出")).toBeInTheDocument();
  expect(screen.getByRole("region", { name: "执行输出" })).toHaveTextContent("stream log chunk");
  expect(screen.getByRole("heading", { name: "运行详情" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "事件" })).toBeInTheDocument();
  expect(screen.getByText("查看 result/context/usage")).toBeInTheDocument();
  expect(await screen.findByText("已入队")).toBeInTheDocument();
  expect(screen.getAllByText("Agent 回复")).toHaveLength(3);
  expect(screen.getByText("Agent 正在处理任务")).toBeInTheDocument();
  expect(screen.getByText(/长回复内容/)).toBeInTheDocument();
  expect(screen.queryByText(/最终结论/)).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "展开完整回复" }));
  expect(screen.getByText(new RegExp(`最终结论`))).toBeInTheDocument();
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

it("allows re-executing an issue after the latest run failed", async () => {
  const issue = {
    id: "issue-1",
    orgId: "org-1",
    identifier: "OCT-1",
    title: "修复运行错误",
    description: "重新执行失败任务",
    status: "in_progress",
    priority: "high",
    projectId: null,
    goalId: null,
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
  const failedRun = {
    id: "run-failed",
    orgId: "org-1",
    agentId: "agent-1",
    issueId: "issue-1",
    invocationSource: "assignment",
    triggerDetail: "manual",
    status: "failed",
    error: "Separator is found in model output",
    createdAt: "2026-06-02T10:00:00Z",
  };
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") {
      return respond([{ id: "agent-1", orgId: "org-1", name: "Builder", role: "engineer", status: "idle" }]);
    }
    if (path === "/api/orgs/org-1/projects" && init?.method === "GET") return respond([]);
    if (path === "/api/orgs/org-1/goals" && init?.method === "GET") return respond([]);
    if (path === "/api/orgs/org-1/heartbeat-runs" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/heartbeat-runs" && init?.method === "GET") return respond([failedRun]);
    if (path === "/api/issues/issue-1/heartbeat-context" && init?.method === "GET") return respond({ issueId: "issue-1" });
    if (path === "/api/issues/issue-1/comments" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/attachments" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/documents" && init?.method === "GET") return respond([]);
    if (path === "/api/heartbeat-runs/run-failed" && init?.method === "GET") return respond(failedRun);
    if (path === "/api/heartbeat-runs/run-failed/events" && init?.method === "GET") return respond([]);
    if (path === "/api/heartbeat-runs/run-failed/workspace-operations" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/execute" && init?.method === "POST") {
      return respond({ id: "run-2", orgId: "org-1", agentId: "agent-1", status: "queued" }, 202);
    }
    if (path === "/api/heartbeat-runs/run-2" && init?.method === "GET") {
      return respond({ id: "run-2", orgId: "org-1", agentId: "agent-1", invocationSource: "assignment", status: "queued" });
    }
    if (path === "/api/heartbeat-runs/run-2/events" && init?.method === "GET") return respond([]);
    if (path === "/api/heartbeat-runs/run-2/workspace-operations" && init?.method === "GET") return respond([]);
    if (path.startsWith("/api/heartbeat-runs/run-2/stream") && init?.method === "GET") {
      return respondStream([{ type: "final", run: { id: "run-2", orgId: "org-1", agentId: "agent-1", invocationSource: "assignment", status: "succeeded" } }]);
    }
    return respond(issue);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/issues/issue-1");
  expect(await screen.findByRole("heading", { name: "修复运行错误" })).toBeInTheDocument();
  expect(await screen.findByRole("button", { name: "重新执行" })).toBeInTheDocument();
  expect(screen.getAllByText(/Separator is found in model output/).length).toBeGreaterThan(0);
  await userEvent.click(screen.getByRole("button", { name: "重新执行" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/issues/issue-1/execute",
    expect.objectContaining({ method: "POST", body: "{}" }),
  );
});

it("shows repeat execution after the latest run succeeded", async () => {
  const issue = {
    id: "issue-1",
    orgId: "org-1",
    identifier: "OCT-3",
    title: "分析源码",
    description: "继续分析",
    status: "in_progress",
    priority: "medium",
    projectId: null,
    goalId: null,
    parentId: null,
    assigneeAgentId: "agent-1",
    assigneeUserId: null,
    reviewerAgentId: null,
    reviewerUserId: null,
    originKind: "manual",
    originId: null,
    issueNumber: 3,
    requestDepth: 0,
    startedAt: "2026-06-02T10:00:00Z",
    completedAt: null,
    workProducts: [],
    createdAt: "",
    updatedAt: "",
  };
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") {
      return respond([{ id: "agent-1", orgId: "org-1", name: "Builder", role: "engineer", status: "idle" }]);
    }
    if (path === "/api/orgs/org-1/projects" && init?.method === "GET") return respond([]);
    if (path === "/api/orgs/org-1/goals" && init?.method === "GET") return respond([]);
    if (path === "/api/orgs/org-1/heartbeat-runs" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/heartbeat-runs" && init?.method === "GET") {
      return respond([{
        runId: "run-succeeded",
        orgId: "org-1",
        agentId: "agent-1",
        issueId: "issue-1",
        invocationSource: "assignment",
        status: "succeeded",
        createdAt: "2026-06-04T01:46:42Z",
        finishedAt: "2026-06-04T01:49:46Z",
      }]);
    }
    if (path === "/api/issues/issue-1/heartbeat-context" && init?.method === "GET") return respond({ issueId: "issue-1" });
    if (path === "/api/issues/issue-1/comments" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/attachments" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/documents" && init?.method === "GET") return respond([]);
    if (path === "/api/heartbeat-runs/run-succeeded" && init?.method === "GET") {
      return respond({ id: "run-succeeded", orgId: "org-1", agentId: "agent-1", invocationSource: "assignment", status: "succeeded" });
    }
    if (path === "/api/heartbeat-runs/run-succeeded/events" && init?.method === "GET") return respond([]);
    if (path === "/api/heartbeat-runs/run-succeeded/workspace-operations" && init?.method === "GET") return respond([]);
    return respond(issue);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/issues/issue-1");
  expect(await screen.findByRole("button", { name: "再次执行" })).toBeInTheDocument();
  expect(screen.getByRole("region", { name: "运行记录" })).toHaveTextContent("run-succeeded");
  expect(screen.getByText("运行：成功")).toBeInTheDocument();
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
    if (path === "/api/issues/issue-1/documents" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/heartbeat-runs" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/heartbeat-context" && init?.method === "GET") return respond({ issueId: "issue-1" });
    return respond(issue);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/issues/issue-1");
  const executeButton = await screen.findByRole("button", { name: "启动执行" });
  expect(executeButton).toHaveAttribute("aria-disabled", "true");
  expect(executeButton).not.toBeDisabled();
  await userEvent.click(executeButton);
  expect(screen.getByRole("status")).toHaveTextContent("请先分配负责人，再启动执行。");
  expect(fetchMock).not.toHaveBeenCalledWith(
    "/api/issues/issue-1/execute",
    expect.objectContaining({ method: "POST" }),
  );
});
