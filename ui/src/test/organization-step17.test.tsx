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

  const resourceHeading = await screen.findByRole("heading", { name: "资源", level: 1 });
  const resourceHeader = resourceHeading.closest("header")!;
  expect(resourceHeader).toHaveClass("page-header");
  expect(resourceHeader).not.toHaveClass("org-resource-hero");
  expect(resourceHeader.closest(".org-content")).toHaveClass("org-content-full");
  expect(within(resourceHeader).getByText("Resources")).toHaveClass("eyebrow");
  expect(within(resourceHeader).getByRole("button", { name: "添加资源" })).toBeInTheDocument();
  expect(within(resourceHeader).getByRole("link", { name: "浏览工作区" })).toHaveAttribute("href", "/orgs/org-1/workspaces");
  expect(screen.getByRole("link", { name: /资源/ })).toHaveClass("active");
  expect(await screen.findByText("Repository")).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "目录" })).not.toBeInTheDocument();
  expect(screen.queryByText("使用稳定名称和明确定位符，便于智能体可靠引用资源。")).not.toBeInTheDocument();
  const resourceList = screen.getByRole("region", { name: "资源列表" });
  expect(within(resourceList).getByRole("heading", { name: "Repository" })).toBeInTheDocument();
  expect(within(resourceList).getByTitle("Repository")).toBeInTheDocument();
  expect(within(resourceList).getByTitle("https://example.test/repo")).toHaveTextContent("https://example.test/repo");
  expect(within(resourceList).getByTitle("Code")).toHaveClass("org-resource-description");
  expect(within(resourceList).getByRole("button", { name: "编辑" })).toBeInTheDocument();
  expect(within(resourceList).getByRole("button", { name: "删除" })).toBeInTheDocument();
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

it("groups organization resources by type and omits empty groups", async () => {
  const rows = [
    { id: "link-1", name: "First link", kind: "url" },
    { id: "dir-1", name: "Workspace directory", kind: "directory" },
    { id: "connector-1", name: "External object", kind: "connector_object" },
    { id: "link-2", name: "Second link", kind: "url" },
  ].map((resource) => ({ ...resource, orgId: "org-1", locator: resource.id, description: null, metadata: null }));
  vi.stubGlobal("fetch", vi.fn((path: string) => respond(path === "/api/orgs/org-1/resources" ? rows : [])));

  renderApp("/orgs/org-1/resources");

  const links = await screen.findByRole("region", { name: "链接 · 2" });
  expect(within(links).getAllByRole("heading", { level: 3 }).map((heading) => heading.textContent)).toEqual(["First link", "Second link"]);
  expect(within(links).getAllByRole("button", { name: "编辑" })).toHaveLength(2);
  expect(within(links).queryByText("url")).not.toBeInTheDocument();
  expect(within(screen.getByRole("region", { name: "目录 · 1" })).getByText("Workspace directory")).toBeInTheDocument();
  expect(within(screen.getByRole("region", { name: "连接器对象 · 1" })).getByText("External object")).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: /^文件 ·/ })).not.toBeInTheDocument();
});

it("shows no type groups for an empty organization resources list", async () => {
  vi.stubGlobal("fetch", vi.fn(() => respond([])));

  renderApp("/orgs/org-1/resources");

  expect(await screen.findByLabelText("No resources")).toBeInTheDocument();
  expect(within(screen.getByRole("region", { name: "资源列表" })).queryAllByRole("heading")).toHaveLength(0);
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
  const skillsHeader = (await screen.findByRole("heading", { name: "技能", level: 1 })).closest("header")!;
  expect(skillsHeader).toHaveClass("page-header");
  expect(skillsHeader.closest(".org-content")).toHaveClass("org-content-full", "organization-skills-content");
  expect(within(skillsHeader).getByText("Skills")).toHaveClass("eyebrow");
  expect(await within(skillsHeader).findByText("3 个可用")).toHaveClass("tertiary-page-supporting");
  expect(within(skillsHeader).queryByRole("button")).not.toBeInTheDocument();
  const skillManagement = screen.getByRole("group", { name: "技能管理" });
  expect(within(skillManagement).getByRole("button", { name: "导入" })).toBeInTheDocument();
  expect(within(skillManagement).getByRole("button", { name: "扫描" })).toBeInTheDocument();
  expect(skillManagement.parentElement).toHaveClass("organization-skill-list-tools");
  expect(skillManagement.nextElementSibling).toContainElement(screen.getByLabelText("搜索技能"));
  await userEvent.click(within(skillManagement).getByRole("button", { name: "创建技能" }));
  expect(screen.getByRole("heading", { name: "添加技能" })).toBeInTheDocument();
  const createHeader = screen.getByRole("heading", { name: "添加技能" }).closest(".task-modal-header")!;
  await userEvent.click(within(createHeader).getByRole("button", { name: "取消" }));
  expect(screen.queryByRole("heading", { name: "添加技能" })).not.toBeInTheDocument();
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
  expect(screen.getByText("来源路径")).toBeVisible();
  expect(screen.queryByRole("button", { name: "更多信息" })).not.toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "技能信息", hidden: true })).not.toBeInTheDocument();
  expect(screen.getByText("兼容性")).toBeVisible();
  const searchSection = screen.getByLabelText("搜索技能").closest(".organization-skill-search")!;
  const listTools = searchSection.parentElement!;
  const skillsSidebar = listTools.parentElement!;
  expect(skillsSidebar).toHaveClass("organization-skills-sidebar");
  expect(listTools.nextElementSibling).toHaveClass("organization-skill-list-panel");
  const skillOverview = screen.getByRole("heading", { name: "Skill Creator" }).closest(".organization-skill-overview")!;
  expect(skillOverview.parentElement).toHaveClass("organization-skill-pane");
  expect(skillOverview.parentElement?.parentElement).toBe(skillsSidebar.parentElement);
  expect(skillOverview.nextElementSibling).toHaveClass("organization-skill-body");

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
  expect(editor.closest(".file-browser") as HTMLElement).toHaveClass("organization-skill-content-layout");
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
