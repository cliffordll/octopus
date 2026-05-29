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
      return respond([{
        id: "skill-1",
        orgId: "org-1",
        key: "review",
        slug: "review",
        name: "Review",
        description: "Review code changes",
        markdown: "# Review",
        sourceType: "local",
        sourceLocator: null,
        sourceRef: null,
        trustLevel: "trusted",
        compatibility: "compatible",
        fileInventory: [{ path: "SKILL.md", kind: "markdown" }],
        metadata: null,
        createdAt: "",
        updatedAt: "",
        attachedAgentCount: 1,
        editable: true,
        editableReason: null,
        sourceLabel: "Organization skill",
        sourceBadge: "local",
        sourcePath: null,
        workspaceEditPath: null,
      }]);
    }
    if (path === "/api/orgs/org-1/skills/skill-1" && init?.method === "GET") {
      return respond({ id: "skill-1", name: "Review", usedByAgents: [] });
    }
    if (path === "/api/orgs/org-1/skills/skill-1/update-status" && init?.method === "GET") {
      return respond({ supported: false, reason: null, trackingRef: null, currentRef: null, latestRef: null, hasUpdate: false });
    }
    if (path === "/api/orgs/org-1/skills/skill-1/files?path=SKILL.md" && init?.method === "GET") {
      return respond({ skillId: "skill-1", path: "SKILL.md", kind: "markdown", content: "# Review", language: "markdown", markdown: true, editable: true });
    }
    if (path === "/api/orgs/org-1/skills/skill-1/files" && init?.method === "PATCH") {
      return respond({ skillId: "skill-1", path: "SKILL.md", kind: "markdown", content: "# Review\nUpdated", language: "markdown", markdown: true, editable: true });
    }
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/skills");
  expect(await screen.findByRole("heading", { name: "技能" })).toBeInTheDocument();
  expect((await screen.findAllByText("Review code changes")).length).toBeGreaterThanOrEqual(1);
  expect(screen.getByRole("button", { name: /Review/ })).toHaveClass("selected");
  expect(screen.getByRole("heading", { name: "Files" })).toBeInTheDocument();
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
  expect(within(screen.getByRole("navigation", { name: "组织导航" })).getByRole("link", { name: /技能/ })).toHaveClass("active");
});
