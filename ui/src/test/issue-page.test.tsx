import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { renderApp, respond, respondStream } from "./render-app";

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.unstubAllGlobals();
}, 10000);

async function expandRunRecords() {
  const region = await screen.findByRole("region", { name: "运行记录" });
  const expandButton = within(region).queryByRole("button", { name: "展开运行记录" });
  if (expandButton) await userEvent.click(expandButton);
  return region;
}

async function ensureRunExpanded(region: HTMLElement, runId: string) {
  const expandButton = within(region).queryByRole("button", { name: `展开运行 ${runId}` });
  if (expandButton) await userEvent.click(expandButton);
}

it("shows existing run records without collapsing the section by default", async () => {
  const longSummary = `任务执行摘要很长，需要默认收起，避免运行记录布局被撑乱。${"继续补充执行细节。".repeat(12)}最终结论。`;
  const issue = {
    id: "issue-1",
    orgId: "org-1",
    identifier: "OCT-1",
    title: "运行中任务",
    description: "查看运行记录",
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
    startedAt: "2026-06-02T10:00:00Z",
    completedAt: null,
    workProducts: [],
    createdAt: "",
    updatedAt: "",
  };
  const run = {
    id: "run-visible",
    runId: "run-visible",
    orgId: "org-1",
    agentId: "agent-1",
    issueId: "issue-1",
    invocationSource: "assignment",
    runPurpose: "task_execution",
    status: "running",
    summary: longSummary,
    usageJson: { cachedInputTokens: 900, costCents: 37, inputTokens: 1200, outputTokens: 340 },
    createdAt: "2026-06-02T10:00:00Z",
    startedAt: "2026-06-02T10:01:00Z",
  };
  const runDetail = {
    ...run,
    resultJson: { summary: longSummary },
  };
  const secondRun = {
    id: "run-second",
    runId: "run-second",
    orgId: "org-1",
    agentId: "agent-1",
    issueId: "issue-1",
    invocationSource: "automation",
    runPurpose: "closeout_followup",
    status: "failed",
    summary: "第二次运行失败",
    contextSnapshot: { wakeReason: "issue_passive_followup" },
    createdAt: "2026-06-02T11:00:00Z",
    startedAt: "2026-06-02T11:01:00Z",
  };
  const secondRunDetail = {
    ...secondRun,
    resultJson: { summary: "第二次运行失败" },
  };
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") {
      return respond([{ id: "agent-1", orgId: "org-1", name: "Builder", role: "engineer", status: "running" }]);
    }
    if (path === "/api/orgs/org-1/projects" && init?.method === "GET") return respond([]);
    if (path === "/api/orgs/org-1/goals" && init?.method === "GET") return respond([]);
    if (path === "/api/orgs/org-1/heartbeat-runs" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/runs" && init?.method === "GET") return respond([run, secondRun]);
    if (path === "/api/issues/issue-1/heartbeat-context" && init?.method === "GET") return respond({ issueId: "issue-1" });
    if (path === "/api/issues/issue-1/comments" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/attachments" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/documents" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/work-products" && init?.method === "GET") return respond([]);
    if (path === "/api/heartbeat-runs/run-visible" && init?.method === "GET") return respond({ ...runDetail, status: "succeeded" });
    if (path === "/api/heartbeat-runs/run-visible/events" && init?.method === "GET") return respond([]);
    if (path === "/api/heartbeat-runs/run-visible/workspace-operations" && init?.method === "GET") return respond([]);
    if (path === "/api/heartbeat-runs/run-second" && init?.method === "GET") return respond(secondRunDetail);
    if (path === "/api/heartbeat-runs/run-second/events" && init?.method === "GET") return respond([]);
    if (path === "/api/heartbeat-runs/run-second/workspace-operations" && init?.method === "GET") return respond([]);
    return respond(issue);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/issues/issue-1");

  const runRecordsRegion = await screen.findByRole("region", { name: "运行记录" });
  expect((await within(runRecordsRegion).findAllByText("run-visible")).length).toBeGreaterThan(0);
  expect(within(runRecordsRegion).getByRole("region", { name: "心跳上下文" })).toBeInTheDocument();
  expect(within(runRecordsRegion).queryByRole("button", { name: "折叠运行记录" })).not.toBeInTheDocument();
  expect(within(runRecordsRegion).queryByRole("button", { name: "展开运行记录" })).not.toBeInTheDocument();
  expect(within(runRecordsRegion).getByText("来源 assignment")).toBeInTheDocument();
  expect(within(runRecordsRegion).getByText("来源 automation")).toBeInTheDocument();
  expect(within(runRecordsRegion).getByText("任务执行")).toBeInTheDocument();
  expect(within(runRecordsRegion).getByText("收尾跟进")).toBeInTheDocument();
  expect(within(runRecordsRegion).getByText("触发原因 issue_passive_followup")).toBeInTheDocument();
  expect(screen.getByText("最新运行：运行中")).toBeInTheDocument();
  const summaryBlock = within(runRecordsRegion).getAllByText("输出摘要")[0].closest(".issue-run-record-summary");
  expect(summaryBlock).not.toHaveTextContent(longSummary);
  expect(summaryBlock).toHaveTextContent("展开");
  await userEvent.click(within(runRecordsRegion).getByRole("button", { name: "展开运行摘要 run-visible" }));
  expect(summaryBlock).toHaveTextContent(longSummary);
  await userEvent.click(within(runRecordsRegion).getByRole("button", { name: "收起运行摘要 run-visible" }));
  expect(summaryBlock).not.toHaveTextContent(longSummary);
  expect(summaryBlock).toHaveTextContent("展开");
  const costPanel = await screen.findByRole("region", { name: "任务成本" });
  expect(within(costPanel).getByRole("heading", { name: "成本" })).toBeInTheDocument();
  expect(within(costPanel).getByText(/(?:US)?\$0\.37/)).toBeInTheDocument();
  expect(within(costPanel).getByText("Total tokens")).toBeInTheDocument();
  expect(within(costPanel).getByText("1,540")).toBeInTheDocument();
  expect(within(costPanel).getByText("输入")).toBeInTheDocument();
  expect(within(costPanel).getByText("1,200")).toBeInTheDocument();
  expect(within(costPanel).getByText("输出")).toBeInTheDocument();
  expect(within(costPanel).getByText("340")).toBeInTheDocument();
  expect(within(costPanel).getByText("已缓存")).toBeInTheDocument();
  expect(within(costPanel).getByText("900")).toBeInTheDocument();

  await ensureRunExpanded(runRecordsRegion, "run-visible");
  expect(await within(runRecordsRegion).findByRole("heading", { name: "心跳上下文" })).toBeInTheDocument();
  expect(within(runRecordsRegion).getByRole("button", { name: /第 1 次 run-visible.*来源 assignment.*运行中/ })).toBeInTheDocument();
  expect(within(runRecordsRegion).queryByRole("button", { name: /第 1 次 run-visible.*来源 assignment.*成功/ })).not.toBeInTheDocument();
  expect(within(runRecordsRegion).getByRole("button", { name: /第 2 次 run-second.*来源 automation.*触发原因 issue_passive_followup.*失败/ })).toBeInTheDocument();
  expect(runRecordsRegion).not.toHaveTextContent("未知来源");
  await ensureRunExpanded(runRecordsRegion, "run-second");
  expect((await within(runRecordsRegion).findAllByRole("heading", { name: "心跳上下文" })).length).toBeGreaterThanOrEqual(2);
});

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
        metadata: {
          source: "execution_workspace_scan",
          workspacePath: "docs/login-flow.md",
          workspaceBrowserPath: "artifacts/issues/issue-1/runs/run-1/login.md",
        },
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
    if (path === "/api/issues/issue-1/runs" && init?.method === "GET") {
      return respond([{ id: "run-1", orgId: "org-1", agentId: "agent-1", issueId: "issue-1", invocationSource: "assignment", status: "succeeded", createdAt: "2026-05-28T08:59:00Z", startedAt: "2026-05-28T09:00:00Z" }]);
    }
    if (path === "/api/heartbeat-runs/run-1" && init?.method === "GET") {
      return respond({ id: "run-1", orgId: "org-1", agentId: "agent-1", issueId: "issue-1", invocationSource: "assignment", status: "succeeded", createdAt: "2026-05-28T08:59:00Z", startedAt: "2026-05-28T09:00:00Z" });
    }
    if (path === "/api/heartbeat-runs/run-1/events" && init?.method === "GET") return respond([]);
    if (path === "/api/heartbeat-runs/run-1/workspace-operations" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/heartbeat-context" && init?.method === "GET") {
      return respond({ issueId: "issue-1" });
    }
    if (path === "/api/issues/issue-1/activity" && init?.method === "GET") {
      return respond([
        {
          id: "activity-1",
          orgId: "org-1",
          action: "issue.status_changed",
          actorType: "user",
          actorId: "board",
          entityType: "issue",
          entityId: "issue-1",
          summary: "进入评审",
          details: { fromStatus: "todo", toStatus: "in_review" },
          createdAt: "2026-06-08T10:00:00Z",
        },
        {
          id: "activity-2",
          orgId: "org-1",
          action: "issue.executed",
          actorType: "user",
          actorId: "board",
          entityType: "issue",
          entityId: "issue-1",
          agentId: "agent-1",
          runId: "run-1",
          details: { runId: "run-1", agentId: "agent-1", reason: "issue_execute" },
          createdAt: "2026-06-08T10:05:00Z",
        },
      ]);
    }
    if (path === "/api/issues/issue-1/comments" && init?.method === "GET") {
      return respond([
        {
          id: "c-1",
          issueId: "issue-1",
          body: "已有讨论",
          authorAgentId: null,
          authorUserId: "board",
          createdAt: "2026-06-08T10:03:00Z",
          updatedAt: "2026-06-08T10:03:00Z",
        },
      ]);
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
    if (path === "/api/issues/issue-1/work-products" && init?.method === "GET") {
      return respond(issue.workProducts);
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
  expect(screen.getAllByRole("button", { name: "复制 ID" })).toHaveLength(1);
  expect(screen.getAllByRole("link", { name: "聊天" })).toHaveLength(1);
  const properties = screen.getByRole("region", { name: "任务属性" });
  expect(properties).toHaveTextContent("属性");
  expect(properties).toHaveTextContent("编号");
  expect(properties).toHaveTextContent("层级");
  expect(properties).toHaveTextContent("已启动");
  expect(properties).toHaveTextContent("已完成");
  expect(screen.getByRole("option", { name: "进行中" })).toBeDisabled();
  await userEvent.selectOptions(screen.getByLabelText("优先级"), "critical");
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/issues/issue-1",
    expect.objectContaining({ method: "PATCH", body: JSON.stringify({ priority: "critical" }) }),
  );
  expect(screen.getByRole("region", { name: "运行记录" })).not.toHaveTextContent("登录流程 PR");
  const runRecordsRegion = await expandRunRecords();
  await ensureRunExpanded(runRecordsRegion, "run-1");
  const workProductsRegion = screen.getByRole("region", { name: "运行产物" });
  expect(workProductsRegion).toHaveTextContent("任务产物已折叠");
  await userEvent.click(within(workProductsRegion).getByRole("button", { name: "展开任务产物 2" }));
  expect(workProductsRegion).toHaveTextContent("登录流程 PR");
  expect(workProductsRegion).toHaveTextContent("运行摘要");
  expect(workProductsRegion).toHaveTextContent("pull_request");
  expect(workProductsRegion).toHaveTextContent("运行产物");
  expect(workProductsRegion).toHaveTextContent("技术详情");
  expect(screen.getByText("登录流程 PR")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "下载运行产物" })).toHaveAttribute("href", "/api/assets/asset-product-1/content");
  expect(screen.getByRole("link", { name: "在工作区打开" })).toHaveAttribute(
    "href",
    "/orgs/org-1/workspaces?path=artifacts%2Fissues%2Fissue-1%2Fruns%2Frun-1%2Flogin.md",
  );
  expect(screen.getByRole("link", { name: "预览内容" })).toHaveAttribute("href", "/api/assets/asset-product-1/content");
  expect(screen.getByRole("link", { name: "打开运行产物" })).toHaveAttribute("href", "https://example.com/pr/42");
  expect(workProductsRegion).toHaveTextContent("不可下载");
  expect(screen.queryByDisplayValue("## 执行步骤")).not.toBeInTheDocument();
  expect(await screen.findByRole("region", { name: "任务文档" })).not.toHaveTextContent("执行计划");
  await userEvent.click(within(screen.getByRole("region", { name: "任务文档" })).getByRole("button", { name: "展开任务文档" }));
  expect(await screen.findByText("执行计划")).toBeInTheDocument();
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
  const activityRegion = await screen.findByRole("region", { name: "动态" });
  const attachmentRegion = await screen.findByRole("region", { name: "附件" });
  expect(attachmentRegion).toHaveTextContent("note.txt");
  expect(activityRegion).toHaveTextContent("1 个文件");
  expect(within(attachmentRegion).getByRole("link", { name: "note.txt" })).toHaveAttribute("href", "/api/assets/asset-1/content");
  expect(await screen.findByText("已有讨论")).toBeInTheDocument();
  expect(activityRegion).toHaveTextContent("状态变更");
  expect(activityRegion).toHaveTextContent("执行任务");
  expect(activityRegion).toHaveTextContent("run-1");
  expect(activityRegion).toHaveTextContent("2026年6月8日 18:05");
  expect(activityRegion).toHaveTextContent("2026年6月8日 18:03");
  expect(activityRegion).toHaveTextContent("进入评审");
  const activityItems = Array.from(activityRegion.querySelectorAll(".issue-activity-item"));
  expect(activityItems[0]).toHaveTextContent("状态变更");
  expect(activityItems[1]).toHaveTextContent("评论");
  expect(activityItems[1]).toHaveTextContent("已有讨论");
  expect(activityItems[2]).toHaveTextContent("执行任务");
  expect(JSON.parse(localStorage.getItem("octopus:recent-issues:org-1") ?? "[]")).toEqual([
    { id: "issue-1", title: longIssueTitle, identifier: "OCT-1", status: "in_review" },
  ]);

  await userEvent.type(screen.getByLabelText("添加评论"), "准备合并");
  await userEvent.click(screen.getByRole("button", { name: "发送评论" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/issues/issue-1/comments",
    expect.objectContaining({ method: "POST" }),
  );

  await userEvent.click(screen.getByRole("button", { name: "添加附件" }));
  await userEvent.upload(screen.getByLabelText("上传本地文件"), new File(["upload"], "upload.txt", { type: "text/plain" }));
  expect(await screen.findByRole("status")).toHaveTextContent("已上传 upload.txt");
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/issues/issue-1/attachments",
    expect.objectContaining({ method: "POST", body: expect.any(FormData) }),
  );

  await userEvent.click(within(attachmentRegion).getByRole("button", { name: "删除 note.txt" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/attachments/attachment-1",
    expect.objectContaining({ method: "DELETE" }),
  );

  await userEvent.click(screen.getByRole("button", { name: "通过评审" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/issues/issue-1/review-decision",
    expect.objectContaining({ method: "POST" }),
  );
  expect(screen.getByRole("region", { name: "评审" })).toHaveTextContent("等待 Builder 给出 closeout");
  expect(screen.getByRole("button", { name: "需要人工处理" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "标记阻塞" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "需要人工处理" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/issues/issue-1/review-decision",
    expect.objectContaining({ method: "POST", body: JSON.stringify({ decision: "needs_followup" }) }),
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
    if (path === "/api/issues/issue-1/runs" && init?.method === "GET") {
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
        {
          id: "run-0",
          orgId: "org-1",
          agentId: "agent-1",
          issueId: "issue-1",
          issueIdentifier: "OCT-1",
          issueTitle: "实现登录流程",
          invocationSource: "assignment",
          status: "succeeded",
          createdAt: "2026-06-02T09:00:00Z",
          resultJson: { summary: "早期运行" },
        },
      ] : []);
    }
    if (path === "/api/issues/issue-1/heartbeat-context" && init?.method === "GET") {
      return respond({ issueId: "issue-1" });
    }
    if (path === "/api/issues/issue-1/comments" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/attachments" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/documents" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/work-products" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1" && init?.method === "PATCH") {
      return respond({ ...issue, status: "in_progress", startedAt: "2026-06-02T10:00:00Z" });
    }
    if (path === "/api/issues/issue-1/execute" && init?.method === "POST") {
      hasExecuted = true;
      return respond({
        id: "run-1",
        orgId: "org-1",
        agentId: "agent-1",
        issueId: "issue-1",
        invocationSource: "assignment",
        status: "queued",
        createdAt: "2026-06-02T10:00:00Z",
      }, 202);
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
        { id: 11, runId: "run-1", agentId: "agent-1", seq: 11, eventType: "runtime.output", stream: "stdout", payload: { content: "payload only reply" }, createdAt: "2026-06-02T10:00:03Z" },
        { id: 10, runId: "run-1", agentId: "agent-1", seq: 10, eventType: "runtime.text", stream: "stdout", message: '{"summary":"结构化回复","ok":true}', createdAt: "2026-06-02T10:00:04Z" },
        { id: 6, runId: "run-1", agentId: "agent-1", seq: 6, eventType: "issue_review_requested", message: "review requested", createdAt: "2026-06-02T10:00:05Z" },
        { id: 7, runId: "run-1", agentId: "agent-1", seq: 7, eventType: "issue_review_closeout_missing", message: "missing closeout", createdAt: "2026-06-02T10:00:06Z" },
        { id: 8, runId: "run-1", agentId: "agent-1", seq: 8, eventType: "issue_passive_followup", message: "followup", createdAt: "2026-06-02T10:00:07Z" },
        { id: 9, runId: "run-1", agentId: "agent-1", seq: 9, eventType: "issue_execution_promoted", message: "promoted", createdAt: "2026-06-02T10:00:08Z" },
      ]);
    }
    if (path === "/api/heartbeat-runs/run-1/log" && init?.method === "GET") {
      return respond({ content: "persisted run log", endOffset: 17, eof: false, nextOffset: 17 });
    }
    if (path === "/api/heartbeat-runs/run-1/log?offset=17" && init?.method === "GET") {
      return respond({ content: "\ncontinued run log", endOffset: 35, eof: true });
    }
    if (path === "/api/heartbeat-runs/run-1/workspace-operations" && init?.method === "GET") {
      return respond([{ id: "op-1", orgId: "org-1", heartbeatRunId: "run-1", phase: "workspace_provision", status: "running", command: "npm test", stdoutExcerpt: "workspace output", logBytes: 40 }]);
    }
    if (path === "/api/workspace-operations/op-1/log" && init?.method === "GET") {
      return respond({ content: "operation log", endOffset: 13, eof: false, nextOffset: 13 });
    }
    if (path === "/api/workspace-operations/op-1/log?offset=13" && init?.method === "GET") {
      return respond({ content: "\ncontinued operation log", endOffset: 37, eof: true });
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
  expect(screen.getByText("已连接到运行 run-1")).toBeInTheDocument();

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/issues/issue-1",
    expect.objectContaining({ method: "PATCH", body: JSON.stringify({ status: "in_progress" }) }),
  );
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/issues/issue-1/execute",
    expect.objectContaining({ method: "POST", body: "{}" }),
  );
  const runRecordsRegion = await expandRunRecords();
  expect(runRecordsRegion).toHaveTextContent("输出摘要");
  expect(runRecordsRegion).toHaveTextContent("排队中");
  expect(runRecordsRegion).toHaveTextContent("第 1 次");
  expect(runRecordsRegion).toHaveTextContent("run-1");
  expect(runRecordsRegion).toHaveTextContent("任务执行");
  expect(runRecordsRegion).not.toHaveTextContent("等待执行");
  expect(screen.getByRole("region", { name: "动态" })).not.toHaveTextContent("等待执行");
  expect(within(runRecordsRegion).queryByRole("button", { name: "取消运行 run-1" })).not.toBeInTheDocument();
  await ensureRunExpanded(runRecordsRegion, "run-1");
  expect(await screen.findByRole("region", { name: "执行输出" })).toBeInTheDocument();
  expect(within(screen.getByRole("region", { name: "执行输出" })).getByRole("button", { name: "取消运行 run-1" })).toBeInTheDocument();
  expect(screen.getByRole("region", { name: "执行输出" })).toHaveTextContent("动态刷新中");
  expect(screen.getByRole("region", { name: "执行输出" })).toHaveTextContent("运行中会通过 stream 动态刷新事件和输出。");
  expect(screen.queryByRole("button", { name: "折叠执行输出" })).not.toBeInTheDocument();
  const runLogBlock = screen.getByRole("heading", { name: "运行日志" }).closest("section") as HTMLElement;
  expect(runLogBlock).toHaveTextContent("运行中会通过 stream 动态刷新事件和输出。");
  await userEvent.click(screen.getByRole("button", { name: /展开关键事件/ }));
  expect(await screen.findByText("Stream 正在输出")).toBeInTheDocument();
  expect(screen.getByRole("region", { name: "执行输出" })).toHaveTextContent("stream log chunk");
  expect(screen.queryByRole("button", { name: "实时日志增量" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("heading", { name: "实时日志增量" }));
  expect(screen.getByText("实时日志增量已折叠。")).toBeInTheDocument();
  expect(screen.getByRole("region", { name: "执行输出" })).not.toHaveTextContent("stream log chunk");
  await userEvent.click(screen.getByRole("heading", { name: "实时日志增量" }));
  expect(screen.getByRole("region", { name: "执行输出" })).toHaveTextContent("stream log chunk");
  expect(screen.getByRole("heading", { name: "执行输出" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "关键事件" })).toBeInTheDocument();
  expect(screen.queryByText("关键事件已折叠。")).not.toBeInTheDocument();
  expect(screen.getAllByText("回复详情").length).toBeGreaterThan(0);
  expect(screen.queryByRole("heading", { name: "Raw 数据" })).not.toBeInTheDocument();
  expect(screen.queryByText("resultJson")).not.toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "运行日志" })).toBeInTheDocument();
  expect(screen.getByRole("region", { name: "执行输出" })).toHaveTextContent("persisted run log");
  await userEvent.click(screen.getByRole("button", { name: "Raw" }));
  expect(screen.getByRole("heading", { name: "实时日志增量" })).toBeInTheDocument();
  expect(screen.getByRole("region", { name: "执行输出" })).toHaveTextContent("stream log chunk");
  expect(screen.getByRole("heading", { name: "Raw 数据" })).toBeInTheDocument();
  const outputHeadings = within(screen.getByRole("region", { name: "执行输出" })).getAllByRole("heading").map((heading) => heading.textContent);
  expect(outputHeadings.indexOf("实时日志增量")).toBeLessThan(outputHeadings.indexOf("Raw 数据"));
  expect(outputHeadings.indexOf("运行日志")).toBeLessThan(outputHeadings.indexOf("Raw 数据"));
  expect(screen.getByRole("region", { name: "执行输出" })).toHaveTextContent("persisted run log");
  await userEvent.click(screen.getByRole("button", { name: "折叠运行日志" }));
  expect(screen.getByText("运行日志已折叠。")).toBeInTheDocument();
  expect(screen.getByRole("region", { name: "执行输出" })).not.toHaveTextContent("persisted run log");
  await userEvent.click(screen.getByRole("button", { name: "展开运行日志" }));
  expect(screen.getByRole("region", { name: "执行输出" })).toHaveTextContent("persisted run log");
  const runLogSection = screen.getByRole("heading", { name: "运行日志" }).closest("section") as HTMLElement;
  await userEvent.click(within(runLogSection).getByRole("button", { name: "加载更多日志" }));
  expect(await screen.findByText(/continued run log/)).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/heartbeat-runs/run-1/log?offset=17",
    expect.objectContaining({ method: "GET" }),
  );
  expect(screen.getByRole("heading", { name: "关键事件" })).toBeInTheDocument();
  expect(screen.queryByText("关键事件已折叠。")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "折叠关键事件" })).toBeInTheDocument();
  expect(screen.getByText("resultJson")).toBeInTheDocument();
  expect(await screen.findByText("已入队")).toBeInTheDocument();
  expect(screen.getAllByText("Agent 回复")).toHaveLength(5);
  const replySummaries = screen.getAllByText("回复详情");
  expect(replySummaries).toHaveLength(5);
  for (const summary of replySummaries) {
    const details = summary.closest("details") as HTMLElement;
    expect(details).not.toHaveAttribute("open");
    await userEvent.click(summary);
    expect(details).toHaveAttribute("open");
  }
  expect(screen.getByText("payload only reply")).toBeInTheDocument();
  expect(screen.getByText(/"summary": "结构化回复"/)).toBeInTheDocument();
  expect(screen.getByText(/"ok": true/)).toBeInTheDocument();
  expect(screen.getByText("请求评审")).toBeInTheDocument();
  expect(screen.getByText("缺少评审结论")).toBeInTheDocument();
  expect(screen.getByText("补充关闭信号")).toBeInTheDocument();
  expect(screen.getByText("延期任务已恢复执行")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "折叠关键事件" }));
  expect(screen.getByText("关键事件已折叠。")).toBeInTheDocument();
  expect(screen.queryByText("已入队")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /展开关键事件/ }));
  expect(screen.getByText("已入队")).toBeInTheDocument();
  expect(screen.getByText("Agent 正在处理任务")).toBeInTheDocument();
  expect(screen.getByText(/长回复内容/)).toBeInTheDocument();
  expect(screen.queryByText(/最终结论/)).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "展开完整回复" }));
  expect(screen.getByText(new RegExp(`最终结论`))).toBeInTheDocument();
  expect(screen.queryByText("low value")).not.toBeInTheDocument();
  expect(screen.getByText("queued output")).toBeInTheDocument();
  expect(screen.getByText("workspace output")).toBeInTheDocument();
  const workspaceOperationsSection = screen.getByRole("heading", { name: "工作区操作" }).closest("section") as HTMLElement;
  expect(within(workspaceOperationsSection).getAllByText("workspace_provision")).toHaveLength(1);
  expect(await within(workspaceOperationsSection).findByText("operation log")).toBeInTheDocument();
  await userEvent.click(within(workspaceOperationsSection).getByRole("button", { name: "加载更多日志" }));
  expect(await screen.findByText(/continued operation log/)).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/workspace-operations/op-1/log?offset=13",
    expect.objectContaining({ method: "GET" }),
  );
  await userEvent.click(screen.getByRole("button", { name: /展开低价值事件/ }));
  expect(screen.getByText("low value")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "折叠运行 run-1" }));
  expect(screen.queryByRole("region", { name: "执行输出" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "展开运行 run-1" }));
  expect(await screen.findByRole("region", { name: "执行输出" })).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/heartbeat-runs/run-1/log",
    expect.objectContaining({ method: "GET" }),
  );
  await userEvent.click(within(screen.getByRole("region", { name: "执行输出" })).getByRole("button", { name: "取消运行 run-1" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/heartbeat-runs/run-1/cancel",
    expect.objectContaining({ method: "POST" }),
  );
});

it("auto-expands the latest live run and explains silent runtime progress", async () => {
  const issue = {
    id: "issue-1",
    orgId: "org-1",
    identifier: "OCT-1",
    title: "运行中任务",
    description: "查看运行进度",
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
    startedAt: "2026-06-02T10:00:00Z",
    completedAt: null,
    workProducts: [],
    createdAt: "",
    updatedAt: "",
  };
  const run = {
    id: "run-live",
    runId: "run-live",
    orgId: "org-1",
    agentId: "agent-1",
    issueId: "issue-1",
    invocationSource: "assignment",
    status: "running",
    createdAt: "2026-06-02T10:00:00Z",
    startedAt: "2026-06-02T10:01:00Z",
    processPid: 31740,
  };
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") {
      return respond([{ id: "agent-1", orgId: "org-1", name: "Builder", role: "engineer", status: "running" }]);
    }
    if (path === "/api/orgs/org-1/projects" && init?.method === "GET") return respond([]);
    if (path === "/api/orgs/org-1/goals" && init?.method === "GET") return respond([]);
    if (path === "/api/orgs/org-1/heartbeat-runs" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/runs" && init?.method === "GET") return respond([run]);
    if (path === "/api/issues/issue-1/heartbeat-context" && init?.method === "GET") return respond({ issueId: "issue-1" });
    if (path === "/api/issues/issue-1/comments" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/attachments" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/documents" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/work-products" && init?.method === "GET") return respond([]);
    if (path === "/api/heartbeat-runs/run-live" && init?.method === "GET") return respond(run);
    if (path === "/api/heartbeat-runs/run-live/events" && init?.method === "GET") {
      return respond([
        { id: 1, runId: "run-live", agentId: "agent-1", seq: 1, eventType: "lifecycle", stream: "system", message: "run started", createdAt: "2026-06-02T10:01:00Z" },
        { id: 2, runId: "run-live", agentId: "agent-1", seq: 2, eventType: "runtime.progress", stream: "system", message: "runtime still running", payload: { elapsedSeconds: 45, processPid: 31740 }, createdAt: "2026-06-02T10:01:45Z" },
      ]);
    }
    if (path === "/api/heartbeat-runs/run-live/log" && init?.method === "GET") return respond({ content: "", endOffset: 0, eof: true });
    if (path === "/api/heartbeat-runs/run-live/workspace-operations" && init?.method === "GET") return respond([]);
    if (path.startsWith("/api/heartbeat-runs/run-live/stream") && init?.method === "GET") return respondStream([]);
    return respond(issue);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/issues/issue-1");

  const runRecordsRegion = await expandRunRecords();
  expect(await within(runRecordsRegion).findByRole("button", { name: "折叠运行 run-live" })).toBeInTheDocument();
  const output = await screen.findByRole("region", { name: "执行输出" });
  expect(output).toHaveTextContent("进程 31740 已启动，等待 runtime 输出。");
  expect(output).toHaveTextContent("最近进度：runtime still running");
});

it("surfaces operator closeout review activity on the issue page", async () => {
  const issue = {
    id: "issue-1",
    orgId: "org-1",
    identifier: "OCT-1",
    title: "收口缺失任务",
    description: "需要人工确认",
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
    if (path === "/api/issues/issue-1/runs" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/heartbeat-context" && init?.method === "GET") return respond({ issueId: "issue-1" });
    if (path === "/api/issues/issue-1/comments" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/attachments" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/documents" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/work-products" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/activity" && init?.method === "GET") {
      return respond([
        {
          id: "activity-closeout",
          orgId: "org-1",
          action: "issue.closure_needs_operator_review",
          actorType: "system",
          actorId: "issue_closure_governance",
          entityType: "issue",
          entityId: "issue-1",
          agentId: "agent-1",
          runId: "run-closeout",
          details: {
            attempts: 2,
            maxAttempts: 2,
            reason: "missing_closure",
          },
          createdAt: "2026-06-08T10:10:00Z",
        },
      ]);
    }
    return respond(issue);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/issues/issue-1");

  expect(await screen.findByRole("heading", { name: "收口缺失任务" })).toBeInTheDocument();
  expect(await screen.findByRole("status", { name: "需要人工确认收口" })).toHaveTextContent(
    "自动收口已尝试 2/2 次",
  );
  const activityRegion = await screen.findByRole("region", { name: "动态" });
  expect(activityRegion).toHaveTextContent("需要人工确认收口");
  expect(activityRegion).toHaveTextContent("自动收口已尝试 2/2 次");
  expect(screen.getByText("需要人工确认收口").closest(".issue-activity-item")).toHaveClass("tone-needs-attention");
  expect(screen.getByText(/Run run-closeout/)).toHaveClass("muted");
});

it("prompts for explicit closeout when the latest run succeeded without a closeout signal", async () => {
  const issue = {
    id: "issue-1",
    orgId: "org-1",
    identifier: "OCT-1",
    title: "需要收尾的任务",
    description: "成功后仍需显式收口",
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
    startedAt: "2026-06-02T10:00:00Z",
    completedAt: null,
    workProducts: [],
    createdAt: "",
    updatedAt: "",
  };
  const run = {
    id: "run-closeout",
    runId: "run-closeout",
    orgId: "org-1",
    agentId: "agent-1",
    issueId: "issue-1",
    invocationSource: "assignment",
    status: "succeeded",
    createdAt: "2026-06-02T10:00:00Z",
    startedAt: "2026-06-02T10:01:00Z",
  };
  const followupRun = {
    id: "run-followup",
    runId: "run-followup",
    orgId: "org-1",
    agentId: "agent-1",
    issueId: "issue-1",
    invocationSource: "automation",
    runPurpose: "closeout_followup",
    triggerDetail: "issue_passive_followup",
    status: "queued",
    createdAt: "2026-06-02T10:03:00Z",
  };
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") {
      return respond([{ id: "agent-1", orgId: "org-1", name: "Builder", role: "engineer", status: "idle" }]);
    }
    if (path === "/api/orgs/org-1/projects" && init?.method === "GET") return respond([]);
    if (path === "/api/orgs/org-1/goals" && init?.method === "GET") return respond([]);
    if (path === "/api/orgs/org-1/heartbeat-runs" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/runs" && init?.method === "GET") return respond([run]);
    if (path === "/api/issues/issue-1/heartbeat-context" && init?.method === "GET") return respond({ issueId: "issue-1" });
    if (path === "/api/issues/issue-1/comments" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/attachments" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/documents" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/work-products" && init?.method === "GET") return respond([]);
    if (path === "/api/heartbeat-runs/run-closeout" && init?.method === "GET") return respond(run);
    if (path === "/api/issues/issue-1/passive-followup" && init?.method === "POST") return respond(followupRun, 202);
    if (path === "/api/heartbeat-runs/run-closeout/events" && init?.method === "GET") {
      return respond([
        {
          id: 1,
          runId: "run-closeout",
          agentId: "agent-1",
          seq: 1,
          eventType: "lifecycle",
          stream: "system",
          message: "run succeeded",
          createdAt: "2026-06-02T10:02:00Z",
        },
      ]);
    }
    if (path === "/api/heartbeat-runs/run-closeout/workspace-operations" && init?.method === "GET") return respond([]);
    return respond(issue);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/issues/issue-1");

  const prompt = await screen.findByRole("status", { name: "需要收尾" });
  expect(prompt).toHaveTextContent("最新运行已成功，但任务仍未收口");
  expect(prompt).toHaveTextContent("任务阶段下拉");
  expect(prompt).toHaveTextContent("done");
  await userEvent.click(screen.getByRole("button", { name: "立即收尾跟进" }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
    "/api/issues/issue-1/passive-followup",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({}),
    }),
  ));
  expect(await screen.findByText("已创建收尾跟进 run-followup")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "标记任务完成" })).not.toBeInTheDocument();
});

it("labels cancelled passive follow-up runs explicitly", async () => {
  const issue = {
    id: "issue-1",
    orgId: "org-1",
    identifier: "OCT-1",
    title: "需要收尾的任务",
    description: "补充关闭信号已取消",
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
    startedAt: "2026-06-02T10:00:00Z",
    completedAt: null,
    workProducts: [],
    createdAt: "",
    updatedAt: "",
  };
  const run = {
    id: "run-closeout",
    runId: "run-closeout",
    orgId: "org-1",
    agentId: "agent-1",
    issueId: "issue-1",
    invocationSource: "automation",
    runPurpose: "closeout_followup",
    triggerDetail: "issue_passive_followup",
    contextSnapshot: { wakeReason: "issue_passive_followup" },
    status: "cancelled",
    error: "run cancelled",
    createdAt: "2026-06-02T10:00:00Z",
    startedAt: "2026-06-02T10:01:00Z",
  };
  const taskRun = {
    id: "run-task",
    runId: "run-task",
    orgId: "org-1",
    agentId: "agent-1",
    issueId: "issue-1",
    invocationSource: "assignment",
    runPurpose: "task_execution",
    status: "succeeded",
    createdAt: "2026-06-02T09:00:00Z",
    startedAt: "2026-06-02T09:01:00Z",
    finishedAt: "2026-06-02T09:02:00Z",
  };
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") {
      return respond([{ id: "agent-1", orgId: "org-1", name: "Builder", role: "engineer", status: "idle" }]);
    }
    if (path === "/api/orgs/org-1/projects" && init?.method === "GET") return respond([]);
    if (path === "/api/orgs/org-1/goals" && init?.method === "GET") return respond([]);
    if (path === "/api/orgs/org-1/heartbeat-runs" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/runs" && init?.method === "GET") return respond([run, taskRun]);
    if (path === "/api/issues/issue-1/heartbeat-context" && init?.method === "GET") return respond({ issueId: "issue-1" });
    if (path === "/api/issues/issue-1/comments" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/attachments" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/documents" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/work-products" && init?.method === "GET") return respond([]);
    if (path === "/api/heartbeat-runs/run-closeout" && init?.method === "GET") return respond(run);
    if (path === "/api/heartbeat-runs/run-closeout/events" && init?.method === "GET") return respond([]);
    if (path === "/api/heartbeat-runs/run-closeout/workspace-operations" && init?.method === "GET") return respond([]);
    if (path === "/api/heartbeat-runs/run-task" && init?.method === "GET") return respond(taskRun);
    if (path === "/api/heartbeat-runs/run-task/events" && init?.method === "GET") return respond([]);
    if (path === "/api/heartbeat-runs/run-task/workspace-operations" && init?.method === "GET") return respond([]);
    return respond(issue);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/issues/issue-1");

  await screen.findByRole("heading", { name: "需要收尾的任务" });
  expect(screen.getByText("最新运行：成功")).toBeInTheDocument();
  const runRecords = await screen.findByRole("region", { name: "运行记录" });
  expect(within(runRecords).getByText("收尾跟进")).toBeInTheDocument();
  expect(within(runRecords).getByText("任务执行")).toBeInTheDocument();
  expect(within(runRecords).getAllByText("已停止").length).toBeGreaterThan(0);
  expect(screen.queryByText("run cancelled")).not.toBeInTheDocument();
});

it("does not show user cancelled task runs as page errors", async () => {
  const issue = {
    id: "issue-1",
    orgId: "org-1",
    identifier: "OCT-2",
    title: "取消后的任务",
    description: "用户取消普通运行",
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
    issueNumber: 2,
    requestDepth: 0,
    startedAt: "2026-06-02T10:00:00Z",
    completedAt: null,
    workProducts: [],
    createdAt: "",
    updatedAt: "",
  };
  const run = {
    id: "run-cancelled",
    runId: "run-cancelled",
    orgId: "org-1",
    agentId: "agent-1",
    issueId: "issue-1",
    invocationSource: "assignment",
    runPurpose: "task_execution",
    triggerDetail: "system",
    status: "cancelled",
    error: "run cancelled",
    createdAt: "2026-06-02T10:00:00Z",
    startedAt: "2026-06-02T10:01:00Z",
    finishedAt: "2026-06-02T10:02:00Z",
  };
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") {
      return respond([{ id: "agent-1", orgId: "org-1", name: "Builder", role: "engineer", status: "idle" }]);
    }
    if (path === "/api/orgs/org-1/projects" && init?.method === "GET") return respond([]);
    if (path === "/api/orgs/org-1/goals" && init?.method === "GET") return respond([]);
    if (path === "/api/orgs/org-1/heartbeat-runs" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/runs" && init?.method === "GET") return respond([run]);
    if (path === "/api/issues/issue-1/heartbeat-context" && init?.method === "GET") return respond({ issueId: "issue-1" });
    if (path === "/api/issues/issue-1/comments" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/attachments" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/documents" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/work-products" && init?.method === "GET") return respond([]);
    if (path === "/api/heartbeat-runs/run-cancelled" && init?.method === "GET") return respond(run);
    if (path === "/api/heartbeat-runs/run-cancelled/events" && init?.method === "GET") return respond([]);
    if (path === "/api/heartbeat-runs/run-cancelled/workspace-operations" && init?.method === "GET") return respond([]);
    return respond(issue);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/issues/issue-1");

  await screen.findByRole("heading", { name: "取消后的任务" });
  expect(screen.getByText("最新运行：已取消")).toBeInTheDocument();
  expect(screen.queryByText("run cancelled")).not.toBeInTheDocument();
});

it("refreshes server registered work products when an issue run succeeds", async () => {
  const issue = {
    id: "issue-1",
    orgId: "org-1",
    identifier: "OCT-9",
    title: "生成标题文档",
    description: "读取 README 并生成标题文档",
    status: "todo",
    priority: "medium",
    projectId: "project-1",
    goalId: null,
    parentId: null,
    assigneeAgentId: "agent-1",
    assigneeUserId: null,
    reviewerAgentId: null,
    reviewerUserId: null,
    originKind: "manual",
    originId: null,
    issueNumber: 9,
    requestDepth: 0,
    startedAt: null,
    completedAt: null,
    workProducts: [],
    createdAt: "",
    updatedAt: "",
  };
  const generatedWorkProduct = {
    id: "wp-generated",
    orgId: "org-1",
    projectId: "project-1",
    issueId: "issue-1",
    executionWorkspaceId: "exec-1",
    runtimeServiceId: "svc-1",
    type: "artifact",
    provider: "local_disk",
    externalId: null,
    assetId: "asset-generated",
    contentPath: "/api/assets/asset-generated/content",
    contentType: "text/markdown",
    byteSize: 64,
    sha256: "abc",
    title: "README 标题文档",
    url: null,
    status: "ready",
    reviewState: "none",
    isPrimary: false,
    healthStatus: "healthy",
    summary: "server 登记的生成文件",
    metadata: {
      source: "organization_artifacts_scan",
      workspacePath: "artifacts/readme-title.md",
    },
    createdByRunId: "run-1",
    createdAt: "2026-06-04T10:00:00Z",
    updatedAt: "2026-06-04T10:00:00Z",
  };
  let hasFinished = false;
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") {
      return respond([{ id: "agent-1", orgId: "org-1", name: "Builder", role: "engineer", status: "idle" }]);
    }
    if (path === "/api/orgs/org-1/projects" && init?.method === "GET") {
      return respond([{ id: "project-1", orgId: "org-1", name: "控制台", status: "in_progress", urlKey: "console" }]);
    }
    if (path === "/api/orgs/org-1/goals" && init?.method === "GET") return respond([]);
    if (path === "/api/orgs/org-1/heartbeat-runs" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/runs" && init?.method === "GET") {
      return respond(hasFinished ? [{ id: "run-1", orgId: "org-1", agentId: "agent-1", issueId: "issue-1", status: "succeeded", createdAt: "2026-06-04T10:00:00Z" }] : []);
    }
    if (path === "/api/issues/issue-1/heartbeat-context" && init?.method === "GET") return respond({ issueId: "issue-1" });
    if (path === "/api/issues/issue-1/comments" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/attachments" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/documents" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/work-products" && init?.method === "GET") {
      return respond(hasFinished ? [generatedWorkProduct] : []);
    }
    if (path === "/api/issues/issue-1" && init?.method === "PATCH") {
      return respond({ ...issue, status: "in_progress" });
    }
    if (path === "/api/issues/issue-1/execute" && init?.method === "POST") {
      return respond({ id: "run-1", orgId: "org-1", agentId: "agent-1", issueId: "issue-1", status: "queued" }, 202);
    }
    if (path.startsWith("/api/heartbeat-runs/run-1/stream") && init?.method === "GET") {
      hasFinished = true;
      return respondStream([{ type: "final", run: { id: "run-1", orgId: "org-1", agentId: "agent-1", issueId: "issue-1", status: "succeeded" } }]);
    }
    if (path === "/api/heartbeat-runs/run-1" && init?.method === "GET") {
      return respond({ id: "run-1", orgId: "org-1", agentId: "agent-1", issueId: "issue-1", status: hasFinished ? "succeeded" : "queued" });
    }
    if (path === "/api/heartbeat-runs/run-1/events" && init?.method === "GET") return respond([]);
    if (path === "/api/heartbeat-runs/run-1/workspace-operations" && init?.method === "GET") return respond([]);
    return respond(issue);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/issues/issue-1");
  await userEvent.click(await screen.findByRole("button", { name: "启动执行" }));

  const runRecordsRegion = await expandRunRecords();
  await ensureRunExpanded(runRecordsRegion, "run-1");
  await userEvent.click(within(screen.getByRole("region", { name: "运行产物" })).getByRole("button", { name: "展开任务产物 1" }));
  expect((await screen.findAllByText("README 标题文档"))[0]).toBeInTheDocument();
  expect(screen.getByText("server 登记的生成文件")).toBeInTheDocument();
  expect(screen.getByRole("region", { name: "运行产物" })).toHaveTextContent("organization_artifacts_scan");
  expect(screen.getByRole("region", { name: "运行产物" })).toHaveTextContent("artifacts/readme-title.md");
  expect(screen.getByRole("link", { name: "下载运行产物" })).toHaveAttribute("href", "/api/assets/asset-generated/content");
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/issues/issue-1/work-products",
    expect.objectContaining({ method: "GET" }),
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
    error: "Process lost -- child pid 31740 is no longer running",
    createdAt: "2026-06-02T10:00:00Z",
  };
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") {
      return respond([{ id: "agent-1", orgId: "org-1", name: "Builder", role: "engineer", status: "idle" }]);
    }
    if (path === "/api/orgs/org-1/projects" && init?.method === "GET") return respond([]);
    if (path === "/api/orgs/org-1/goals" && init?.method === "GET") return respond([]);
    if (path === "/api/orgs/org-1/heartbeat-runs" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/runs" && init?.method === "GET") return respond([failedRun]);
    if (path === "/api/issues/issue-1/heartbeat-context" && init?.method === "GET") return respond({ issueId: "issue-1" });
    if (path === "/api/issues/issue-1/comments" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/attachments" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/documents" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/work-products" && init?.method === "GET") return respond([]);
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
  expect(screen.getAllByText(/运行进程已中断。子进程在服务完成跟踪前已退出。/).length).toBeGreaterThan(0);
  expect(screen.queryByText(/Process lost -- child pid/)).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "重新执行" }));
  await waitFor(() => {
    expect(screen.queryByText(/最新运行失败：运行进程已中断。子进程在服务完成跟踪前已退出。/)).not.toBeInTheDocument();
  });
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/issues/issue-1/execute",
    expect.objectContaining({ method: "POST", body: "{}" }),
  );
});

it("retries failed reviewer and passive follow-up runs from their run records only", async () => {
  const issue = {
    id: "issue-1",
    orgId: "org-1",
    identifier: "OCT-REVIEW",
    title: "重新执行评审",
    description: "只允许重试失败的 reviewer run",
    status: "in_review",
    priority: "medium",
    projectId: null,
    goalId: null,
    parentId: null,
    assigneeAgentId: "agent-1",
    assigneeUserId: null,
    reviewerAgentId: "reviewer-1",
    reviewerUserId: null,
    originKind: "manual",
    originId: null,
    issueNumber: 14,
    requestDepth: 0,
    startedAt: null,
    completedAt: null,
    workProducts: [],
    createdAt: "",
    updatedAt: "",
  };
  const assignmentRun = {
    id: "run-assignment",
    orgId: "org-1",
    agentId: "agent-1",
    invocationSource: "assignment",
    runPurpose: "task_execution",
    status: "failed",
    createdAt: "2026-06-13T10:00:00Z",
  };
  const reviewRun = {
    id: "run-review",
    orgId: "org-1",
    agentId: "reviewer-1",
    invocationSource: "review",
    runPurpose: "review",
    status: "failed",
    error: "review tool failed",
    createdAt: "2026-06-13T10:01:00Z",
  };
  const followupRun = {
    id: "run-followup",
    orgId: "org-1",
    agentId: "agent-1",
    invocationSource: "automation",
    runPurpose: "closeout",
    triggerDetail: "issue_passive_followup",
    status: "cancelled",
    contextSnapshot: { wakeReason: "issue_passive_followup" },
    createdAt: "2026-06-13T10:02:00Z",
  };
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") {
      return respond([
        { id: "agent-1", orgId: "org-1", name: "Builder", role: "engineer", status: "idle" },
        { id: "reviewer-1", orgId: "org-1", name: "Reviewer", role: "engineer", status: "idle" },
      ]);
    }
    if (path === "/api/orgs/org-1/projects" && init?.method === "GET") return respond([]);
    if (path === "/api/orgs/org-1/goals" && init?.method === "GET") return respond([]);
    if (path === "/api/orgs/org-1/heartbeat-runs" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/runs" && init?.method === "GET") {
      return respond([assignmentRun, reviewRun, followupRun]);
    }
    if (path === "/api/issues/issue-1/heartbeat-context" && init?.method === "GET") return respond({ issueId: "issue-1" });
    if (path === "/api/issues/issue-1/comments" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/attachments" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/documents" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/work-products" && init?.method === "GET") return respond([]);
    if (path === "/api/heartbeat-runs/run-review" && init?.method === "GET") return respond(reviewRun);
    if (path === "/api/heartbeat-runs/run-review/events" && init?.method === "GET") return respond([]);
    if (path === "/api/heartbeat-runs/run-review/workspace-operations" && init?.method === "GET") return respond([]);
    if (path === "/api/heartbeat-runs/run-followup" && init?.method === "GET") return respond(followupRun);
    if (path === "/api/heartbeat-runs/run-followup/events" && init?.method === "GET") return respond([]);
    if (path === "/api/heartbeat-runs/run-followup/workspace-operations" && init?.method === "GET") return respond([]);
    if (path === "/api/heartbeat-runs/run-review/retry" && init?.method === "POST") {
      return respond({
        ...reviewRun,
        id: "run-review-retry",
        status: "queued",
        retryOfRunId: "run-review",
      });
    }
    if (path === "/api/heartbeat-runs/run-followup/retry" && init?.method === "POST") {
      return respond({
        ...followupRun,
        id: "run-followup-retry",
        status: "queued",
        retryOfRunId: "run-followup",
      });
    }
    return respond(issue);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/issues/issue-1");
  const runRecords = await expandRunRecords();
  expect(within(runRecords).getAllByText("Reviewer 评审")).toHaveLength(1);
  const reviewRecord = within(runRecords).getByRole("button", {
    name: /run-review Reviewer 评审.*失败/,
  });
  expect(reviewRecord.closest("article")).toHaveClass("review");
  expect(reviewRecord.querySelector(".issue-run-record-status")).toBeNull();
  expect(reviewRecord.querySelector(".issue-run-record-badges .agent-run-status-pill")).toHaveTextContent("失败");
  const followupRecord = within(runRecords).getByRole("button", {
    name: /run-followup 收尾跟进.*已取消/,
  });
  expect(followupRecord.closest("article")).toHaveClass("followup");
  expect(within(runRecords).queryByRole("button", { name: "重新执行 Reviewer 评审 run-review" })).not.toBeInTheDocument();
  expect(within(runRecords).queryByRole("button", { name: "重新执行 收尾跟进 run-followup" })).not.toBeInTheDocument();
  expect(within(runRecords).queryByRole("button", { name: "重新执行 Reviewer 评审 run-assignment" })).not.toBeInTheDocument();

  await ensureRunExpanded(runRecords, "run-review");
  let outputRegion = await screen.findByRole("region", { name: "执行输出" });
  await userEvent.click(within(outputRegion).getByRole("button", { name: "重新执行 Reviewer 评审 run-review" }));

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/heartbeat-runs/run-review/retry",
    expect.objectContaining({ method: "POST", body: "{}" }),
  );

  await ensureRunExpanded(runRecords, "run-followup");
  outputRegion = (await screen.findAllByRole("region", { name: "执行输出" })).find((region) =>
    within(region).queryByRole("button", { name: "重新执行 收尾跟进 run-followup" }),
  ) as HTMLElement;
  expect(outputRegion).toBeInTheDocument();
  await userEvent.click(within(outputRegion).getByRole("button", { name: "重新执行 收尾跟进 run-followup" }));

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/heartbeat-runs/run-followup/retry",
    expect.objectContaining({ method: "POST", body: "{}" }),
  );
});

it("hides the live stream log when it duplicates the persisted run log", async () => {
  const issue = {
    id: "issue-1",
    orgId: "org-1",
    identifier: "OCT-10",
    title: "同步日志展示",
    description: "避免重复日志",
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
    issueNumber: 10,
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
    if (path === "/api/orgs/org-1/projects" && init?.method === "GET") return respond([]);
    if (path === "/api/orgs/org-1/goals" && init?.method === "GET") return respond([]);
    if (path === "/api/orgs/org-1/heartbeat-runs" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/runs" && init?.method === "GET") {
      return respond([{ id: "run-1", orgId: "org-1", agentId: "agent-1", issueId: "issue-1", status: "running", createdAt: "2026-06-02T10:00:00Z" }]);
    }
    if (path === "/api/issues/issue-1/heartbeat-context" && init?.method === "GET") return respond({ issueId: "issue-1" });
    if (path === "/api/issues/issue-1/comments" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/attachments" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/documents" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/work-products" && init?.method === "GET") return respond([]);
    if (path.startsWith("/api/heartbeat-runs/run-1/stream") && init?.method === "GET") {
      return respondStream([{ type: "log", content: "same log", nextOffset: 8, eof: false }]);
    }
    if (path === "/api/heartbeat-runs/run-1" && init?.method === "GET") return respond({ id: "run-1", orgId: "org-1", agentId: "agent-1", status: "running" });
    if (path === "/api/heartbeat-runs/run-1/events" && init?.method === "GET") return respond([]);
    if (path === "/api/heartbeat-runs/run-1/log" && init?.method === "GET") return respond({ content: "same log", endOffset: 8, eof: true });
    if (path === "/api/heartbeat-runs/run-1/workspace-operations" && init?.method === "GET") return respond([]);
    return respond(issue);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/issues/issue-1");

  const runRecordsRegion = await expandRunRecords();
  await ensureRunExpanded(runRecordsRegion, "run-1");
  expect(await screen.findByRole("heading", { name: "执行输出" })).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "实时日志增量" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Raw" }));
  expect(await screen.findByRole("heading", { name: "运行日志" })).toBeInTheDocument();
  expect(await screen.findByText("same log")).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "实时日志增量" })).not.toBeInTheDocument();
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
    if (path === "/api/issues/issue-1/runs" && init?.method === "GET") {
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
    if (path === "/api/issues/issue-1/work-products" && init?.method === "GET") return respond([]);
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
  const runRecordsRegion = await expandRunRecords();
  expect(runRecordsRegion).toHaveTextContent("run-succeeded");
  expect(screen.getByText("最新运行：成功")).toBeInTheDocument();
  await ensureRunExpanded(runRecordsRegion, "run-succeeded");
  await userEvent.click(within(screen.getByRole("region", { name: "运行产物" })).getByRole("button", { name: "展开任务产物 0" }));
  expect(screen.getByRole("region", { name: "运行产物" })).toHaveTextContent("最新运行已成功，但 server 没有登记受管产物。");
});

it("ignores stale selected runs that do not belong to the issue", async () => {
  localStorage.setItem("octopus:issue-run:org-1:issue-1", "stale-running-run");
  const issue = {
    id: "issue-1",
    orgId: "org-1",
    identifier: "OCT-4",
    title: "生成说明书",
    description: "运行已结束但任务尚未关闭",
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
    issueNumber: 4,
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
    if (path === "/api/issues/issue-1/runs" && init?.method === "GET") {
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
    if (path === "/api/issues/issue-1/work-products" && init?.method === "GET") return respond([]);
    if (path === "/api/heartbeat-runs/stale-running-run" && init?.method === "GET") {
      return respond({
        id: "stale-running-run",
        orgId: "org-1",
        agentId: "agent-1",
        invocationSource: "assignment",
        status: "running",
        contextSnapshot: { issueId: "other-issue" },
      });
    }
    if (path === "/api/heartbeat-runs/stale-running-run/events" && init?.method === "GET") return respond([]);
    if (path === "/api/heartbeat-runs/stale-running-run/workspace-operations" && init?.method === "GET") return respond([]);
    return respond(issue);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/issues/issue-1");

  expect(await screen.findByRole("button", { name: "再次执行" })).toBeInTheDocument();
  expect(screen.getByText("最新运行：成功")).toBeInTheDocument();
  expect(screen.queryByText("运行：运行中")).not.toBeInTheDocument();
});

it("refreshes issue runs when execute returns no new run id", async () => {
  const issue = {
    id: "issue-1",
    orgId: "org-1",
    identifier: "OCT-4",
    title: "等待已有运行",
    description: "server 可能延期或复用已有运行",
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
    issueNumber: 4,
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
    if (path === "/api/orgs/org-1/projects" && init?.method === "GET") return respond([]);
    if (path === "/api/orgs/org-1/goals" && init?.method === "GET") return respond([]);
    if (path === "/api/orgs/org-1/heartbeat-runs" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/runs" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/heartbeat-context" && init?.method === "GET") return respond({ issueId: "issue-1" });
    if (path === "/api/issues/issue-1/comments" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/attachments" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/documents" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/work-products" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/execute" && init?.method === "POST") return respond({ status: "deferred" }, 202);
    return respond(issue);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/issues/issue-1");
  await userEvent.click(await screen.findByRole("button", { name: "启动执行" }));

  expect(screen.getByRole("status")).toHaveTextContent("执行请求已提交，暂未返回新的运行记录，正在刷新任务运行。");
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/issues/issue-1/runs",
    expect.objectContaining({ method: "GET" }),
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
    if (path === "/api/issues/issue-1/documents" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/work-products" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/runs" && init?.method === "GET") return respond([]);
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

it("explains queued issue runs from the assignee active queue", async () => {
  const issue = {
    id: "issue-1",
    orgId: "org-1",
    identifier: "OCT-1",
    title: "排队任务",
    description: "查看为什么还没执行",
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
  const queuedRun = {
    id: "run-queued",
    orgId: "org-1",
    agentId: "agent-1",
    issueId: "issue-1",
    invocationSource: "assignment",
    triggerDetail: "issue_assigned",
    status: "queued",
    createdAt: "2026-06-10T10:05:00Z",
  };
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") return respond([{ id: "agent-1", orgId: "org-1", name: "Builder", role: "engineer", status: "running" }]);
    if (path === "/api/orgs/org-1/projects" && init?.method === "GET") return respond([]);
    if (path === "/api/orgs/org-1/goals" && init?.method === "GET") return respond([]);
    if (path === "/api/orgs/org-1/heartbeat-runs" && init?.method === "GET") {
      return respond([
        { id: "run-timer", orgId: "org-1", agentId: "agent-1", invocationSource: "timer", triggerDetail: "heartbeat_timer", status: "running", createdAt: "2026-06-10T10:00:00Z" },
        { id: "run-auto", orgId: "org-1", agentId: "agent-1", invocationSource: "automation", triggerDetail: "issue_passive_followup", status: "queued", createdAt: "2026-06-10T10:01:00Z" },
        queuedRun,
      ]);
    }
    if (path === "/api/issues/issue-1/runs" && init?.method === "GET") return respond([queuedRun]);
    if (path === "/api/issues/issue-1/heartbeat-context" && init?.method === "GET") return respond({ issueId: "issue-1" });
    if (path === "/api/issues/issue-1/comments" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/attachments" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/documents" && init?.method === "GET") return respond([]);
    if (path === "/api/issues/issue-1/work-products" && init?.method === "GET") return respond([]);
    if (path === "/api/heartbeat-runs/run-queued" && init?.method === "GET") return respond(queuedRun);
    if (path === "/api/heartbeat-runs/run-queued/events" && init?.method === "GET") return respond([]);
    if (path === "/api/heartbeat-runs/run-queued/workspace-operations" && init?.method === "GET") return respond([]);
    return respond(issue);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/issues/issue-1");

  const queueRegion = await screen.findByRole("region", { name: "运行队列状态" });
  expect(queueRegion).toHaveTextContent("Builder 正在处理 3 个活跃运行");
  expect(queueRegion).toHaveTextContent("当前任务前面还有 2 个运行");
  expect(queueRegion).toHaveTextContent("定时心跳");
  expect(queueRegion).toHaveTextContent("assignment");
  expect(queueRegion).toHaveTextContent("issue_assigned");
  expect(queueRegion).toHaveTextContent("OCT-1");
  expect(queueRegion).toHaveTextContent("automation");
  expect(queueRegion).toHaveTextContent("issue_passive_followup");
  expect(within(queueRegion).getByRole("link", { name: "打开负责人运行页" })).toHaveAttribute("href", "/orgs/org-1/agents/agent-1/runs");
});
