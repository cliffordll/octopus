import { cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { renderApp, respond } from "./render-app";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("manages organization resources from the organization navigation", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/projects" && init?.method === "GET") return respond([]);
    if (path === "/api/orgs/org-1/resources" && init?.method === "GET") {
      return respond([{ id: "res-1", orgId: "org-1", name: "Repository", kind: "url", locator: "https://example.test/repo", description: "Code", metadata: null }]);
    }
    if (path === "/api/orgs/org-1/resources" && init?.method === "POST") {
      return respond({ id: "res-2", orgId: "org-1", name: "Runbook", kind: "file", locator: "docs/runbook.md", description: null, metadata: null }, 201);
    }
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/resources");

  expect(await screen.findByRole("heading", { name: "资源" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /资源/ })).toHaveClass("active");
  expect(await screen.findByText("Repository")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "目录" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "添加资源" }));
  await userEvent.type(screen.getByLabelText("名称"), "Runbook");
  await userEvent.selectOptions(screen.getByLabelText("类型"), "file");
  await userEvent.type(screen.getByLabelText("定位符"), "docs/runbook.md");
  await userEvent.click(screen.getByRole("button", { name: "创建资源" }));

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/resources",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ name: "Runbook", kind: "file", locator: "docs/runbook.md", description: null }),
    }),
  );
});

it("shows organization skills and edits the selected skill file", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/projects" && init?.method === "GET") return respond([]);
    if (path === "/api/orgs/org-1/skills" && init?.method === "GET") {
      return respond([
        {
          id: "skill-bundled",
          orgId: "org-1",
          key: "system/skill-creator",
          slug: "skill-creator",
          name: "Skill Creator",
          description: "Create durable agent skills",
          markdown: "# Skill Creator",
          sourceType: "local_path",
          sourceLocator: "server/skills/bundled/skill-creator",
          sourceRef: null,
          trustLevel: "markdown_only",
          compatibility: "compatible",
          fileInventory: [{ path: "SKILL.md", kind: "skill" }],
          metadata: { sourceKind: "system_bundled" },
          createdAt: "",
          updatedAt: "",
          attachedAgentCount: 2,
          editable: false,
          editableReason: "Bundled reference",
          sourceLabel: "Bundled reference",
          sourceBadge: "bundled",
          sourcePath: "server/skills/bundled/skill-creator",
          workspaceEditPath: null,
        },
        {
          id: "skill-1",
          orgId: "org-1",
          key: "review",
          slug: "review",
          name: "Review",
          description: "Review code changes",
          markdown: "# Review",
          sourceType: "local_path",
          sourceLocator: "organizations/org-1/workspaces/skills/review",
          sourceRef: null,
          trustLevel: "markdown_only",
          compatibility: "compatible",
          fileInventory: [
            { path: "SKILL.md", kind: "skill" },
            { path: "references/checklist.md", kind: "other" },
          ],
          metadata: null,
          createdAt: "",
          updatedAt: "",
          attachedAgentCount: 1,
          editable: true,
          editableReason: null,
          sourceLabel: "Local organization skill",
          sourceBadge: "local",
          sourcePath: "organizations/org-1/workspaces/skills/review",
          workspaceEditPath: "organizations/org-1/workspaces/skills/review/SKILL.md",
        },
        {
          id: "skill-community",
          orgId: "org-1",
          key: "skills/deep-research",
          slug: "deep-research",
          name: "Deep Research",
          description: "Research deeply",
          markdown: "# Deep Research",
          sourceType: "local_path",
          sourceLocator: "server/skills/community/deep-research",
          sourceRef: null,
          trustLevel: "markdown_only",
          compatibility: "compatible",
          fileInventory: [{ path: "SKILL.md", kind: "skill" }],
          metadata: null,
          createdAt: "",
          updatedAt: "",
          attachedAgentCount: 0,
          editable: false,
          editableReason: "Community preset",
          sourceLabel: "Community preset",
          sourceBadge: "preset",
          sourcePath: "server/skills/community/deep-research",
          workspaceEditPath: null,
        },
      ]);
    }
    if (path === "/api/orgs/org-1/skills/skill-bundled" && init?.method === "GET") {
      return respond({
        id: "skill-bundled",
        name: "Skill Creator",
        usedByAgents: [
          { id: "agent-1", name: "Builder", urlKey: "builder", agentRuntimeType: "codex_local", desired: true, actualState: "enabled" },
          { id: "agent-2", name: "Reviewer", urlKey: "reviewer", agentRuntimeType: "codex_local", desired: false, actualState: "available" },
        ],
      });
    }
    if (path === "/api/orgs/org-1/skills/skill-bundled/update-status" && init?.method === "GET") {
      return respond({ supported: false, reason: "Local organization skills do not support upstream update checks.", trackingRef: null, currentRef: null, latestRef: null, hasUpdate: false });
    }
    if (path === "/api/orgs/org-1/skills/skill-bundled/files?path=SKILL.md" && init?.method === "GET") {
      return respond({ skillId: "skill-bundled", path: "SKILL.md", kind: "skill", content: "# Skill Creator", language: "markdown", markdown: true, editable: false });
    }
    if (path === "/api/orgs/org-1/skills/skill-1" && init?.method === "GET") {
      return respond({
        id: "skill-1",
        name: "Review",
        usedByAgents: [{ id: "agent-1", name: "Builder", urlKey: "builder", agentRuntimeType: "codex_local", desired: true, actualState: "enabled" }],
      });
    }
    if (path === "/api/orgs/org-1/skills/skill-1/update-status" && init?.method === "GET") {
      return respond({ supported: true, reason: null, trackingRef: "old", currentRef: "old", latestRef: "new", hasUpdate: true });
    }
    if (path === "/api/orgs/org-1/skills/skill-1/files?path=SKILL.md" && init?.method === "GET") {
      return respond({ skillId: "skill-1", path: "SKILL.md", kind: "markdown", content: "# Review", language: "markdown", markdown: true, editable: true });
    }
    if (path === "/api/orgs/org-1/skills/skill-1/files?path=references%2Fchecklist.md" && init?.method === "GET") {
      return respond({ skillId: "skill-1", path: "references/checklist.md", kind: "markdown", content: "# Checklist", language: "markdown", markdown: true, editable: true });
    }
    if (path === "/api/orgs/org-1/skills/skill-1/files" && init?.method === "PATCH") {
      return respond({ skillId: "skill-1", path: "SKILL.md", kind: "markdown", content: "# Review\nUpdated", language: "markdown", markdown: true, editable: true });
    }
    if (path === "/api/orgs/org-1/skills/skill-1/install-update" && init?.method === "POST") {
      return respond({ id: "skill-1", name: "Review" });
    }
    if (path === "/api/orgs/org-1/skills/import" && init?.method === "POST") {
      return respond({ id: "skill-1", name: "Review" }, 201);
    }
    if (path === "/api/orgs/org-1/skills/scan-local" && init?.method === "POST") {
      return respond({
        candidates: [{ sourcePath: "D:/skills/review", slug: "review", name: "Review", description: null, sourceRef: "abc", alreadyImported: true, skillId: "skill-1" }],
        imported: [],
      });
    }
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/skills");
  expect(await screen.findByRole("heading", { name: "技能" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "内置技能列表" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "社区技能列表" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "本地技能列表" })).toBeInTheDocument();
  expect(await screen.findByRole("button", { name: /Deep Research/ })).toBeInTheDocument();
  expect(screen.queryByText("Create durable agent skills")).not.toBeInTheDocument();
  expect(screen.getAllByText("内置").length).toBeGreaterThanOrEqual(2);
  expect(screen.getByText("2 智能体")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Skill Creator/ })).toHaveClass("selected");
  expect(screen.queryByText("只读：内置")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "删除" })).toBeDisabled();
  expect(await screen.findByText("Builder")).toBeInTheDocument();
  expect(await screen.findByText("Reviewer")).toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: /Review/ }));
  expect(screen.queryByText("Review code changes")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Review/ })).toHaveClass("selected");
  await userEvent.click(screen.getByRole("button", { name: "安装更新" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/skills/skill-1/install-update",
    expect.objectContaining({ method: "POST" }),
  );
  expect(screen.getByText("organizations/org-1/workspaces/skills/review")).toBeInTheDocument();
  expect(screen.getByText("organizations/org-1/workspaces/skills/review/SKILL.md")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "文件" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /references/ })).toHaveAttribute("aria-expanded", "false");
  expect(screen.queryByRole("button", { name: /checklist.md/ })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /references/ }));
  expect(screen.getByRole("button", { name: /references/ })).toHaveAttribute("aria-expanded", "true");
  await userEvent.click(screen.getByRole("button", { name: /checklist.md/ }));
  expect(await screen.findByLabelText("references/checklist.md")).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/skills/skill-1/files?path=references%2Fchecklist.md",
    expect.objectContaining({ method: "GET" }),
  );
  await userEvent.click(screen.getByRole("button", { name: /SKILL.md/ }));
  const editor = await screen.findByLabelText("SKILL.md");
  await userEvent.type(editor, "{End}{Enter}Updated");
  await userEvent.click(screen.getByRole("button", { name: "保存" }));

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/skills/skill-1/files",
    expect.objectContaining({
      method: "PATCH",
      body: JSON.stringify({ path: "SKILL.md", content: "# Review\nUpdated" }),
    }),
  );

  await userEvent.click(screen.getByRole("button", { name: "导入" }));
  await userEvent.type(screen.getByLabelText("来源路径"), "D:/skills/review");
  await userEvent.type(screen.getByLabelText("Short name"), "review");
  await userEvent.click(screen.getByRole("button", { name: "导入技能" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/skills/import",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ sourcePath: "D:/skills/review", slug: "review", name: null, description: null, overwrite: false }),
    }),
  );

  await userEvent.click(screen.getByRole("button", { name: "扫描" }));
  await userEvent.type(screen.getByLabelText("根路径"), "D:/skills");
  await userEvent.click(screen.getByLabelText("扫描后导入"));
  await userEvent.click(screen.getAllByRole("button", { name: "扫描" }).at(-1)!);
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/skills/scan-local",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ rootPath: "D:/skills", importDiscovered: true, overwrite: false }),
    }),
  );
  expect(await screen.findByText("1 个候选，已导入 0 个。")).toBeInTheDocument();
  expect(within(screen.getByRole("navigation", { name: "组织导航" })).getByRole("link", { name: /技能/ })).toHaveClass("active");
}, 10000);
