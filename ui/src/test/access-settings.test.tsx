import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { MemberAccessSettings } from "../components/MemberAccessSettings";
import { replaceAuthenticatedSession } from "../auth/sessionCache";
import { renderApp, respond } from "./render-app";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("clears all previous-user data when the authenticated identity changes", () => {
  const queryClient = new QueryClient();
  queryClient.setQueryData(["organizations"], [{ id: "user-a-org" }]);
  queryClient.setQueryData(["issues", "user-a-org"], [{ id: "user-a-issue" }]);

  replaceAuthenticatedSession(queryClient, {
    user: { id: "user-b", name: "User B", email: "user-b@example.com" },
    session: { source: "session" },
  });

  expect(queryClient.getQueryData(["organizations"])).toBeUndefined();
  expect(queryClient.getQueryData(["issues", "user-a-org"])).toBeUndefined();
  expect(queryClient.getQueryData(["auth-session"])).toMatchObject({
    user: { id: "user-b" },
  });
});

it("redirects the control-plane home page to login when there is no Human Session", async () => {
  const fetchMock = vi.fn((path: string) => {
    if (path === "/api/auth/get-session") {
      return respond(null);
    }
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/", { authenticated: false });

  expect(await screen.findByRole("heading", { name: "登录 Octopus" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "返回控制面" })).toHaveAttribute("href", "/");
});

it("signs in with a local account and returns to the control plane", async () => {
  const fetchMock = vi.fn((path: string) => {
    if (path === "/api/auth/sign-in/email" || path === "/api/auth/get-session") {
      return respond({ user: { id: "user-1", email: "owner@example.com" } });
    }
    if (path === "/api/orgs") return respond([]);
    return respond(null);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/login?next=%2Forgs%2Fuser-a-org%2Fissues%2Fuser-a-issue");
  await userEvent.type(screen.getByLabelText("邮箱"), "owner@example.com");
  await userEvent.type(screen.getByLabelText("密码"), "password-123");
  await userEvent.click(screen.getByRole("button", { name: "登录" }));

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/auth/sign-in/email",
    expect.objectContaining({
      body: JSON.stringify({ email: "owner@example.com", password: "password-123" }),
      method: "POST",
    }),
  );
  expect(await screen.findByText("还没有组织")).toBeInTheDocument();
});

it("lists members, edits permissions, and creates invitations", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/members" && !init?.method) {
      return respond([
        {
          id: "member-1",
          orgId: "org-1",
          principalType: "user",
          principalId: "user-1",
          displayName: "Owner",
          status: "active",
          role: "owner",
          permissions: [{ permissionKey: "users:invite", scope: null }],
          createdAt: "2026-08-28T00:00:00Z",
          updatedAt: "2026-08-28T00:00:00Z",
        },
      ]);
    }
    if (path === "/api/orgs/org-1/invites" && !init?.method) return respond([]);
    if (path === "/api/orgs/org-1/invites" && init?.method === "POST") {
      return respond({
        id: "invite-1",
        orgId: "org-1",
        allowedJoinTypes: "human",
        inviteUrl: "/invite/token-1",
        expiresAt: "2026-09-04T00:00:00Z",
        revokedAt: null,
        acceptedAt: null,
      }, 201);
    }
    if (path === "/api/orgs/org-1/members/member-1/permissions") {
      return respond({ id: "member-1" });
    }
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });

  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <MemberAccessSettings orgId="org-1" />
      </MemoryRouter>
    </QueryClientProvider>,
  );

  const member = (await screen.findAllByRole("article"))[0];
  expect(within(member).getByText("Owner")).toBeInTheDocument();
  await userEvent.click(within(member).getByRole("button", { name: "编辑权限" }));
  await userEvent.click(within(member).getByLabelText("创建智能体"));
  await userEvent.click(within(member).getByRole("button", { name: "保存权限" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/members/member-1/permissions",
    expect.objectContaining({ method: "PATCH" }),
  );

  await userEvent.click(screen.getByRole("button", { name: "创建邀请" }));
  expect(await screen.findByLabelText("新邀请链接")).toHaveValue(`${window.location.origin}/invite/token-1`);
});

it("preserves an invitation destination while the human signs in", async () => {
  const fetchMock = vi.fn((path: string) => {
    if (path === "/api/invites/token-1") {
      return respond({
        id: "invite-1",
        orgId: "org-1",
        allowedJoinTypes: "human",
        expiresAt: "2099-09-04T00:00:00Z",
        revokedAt: null,
        acceptedAt: null,
      });
    }
    if (path === "/api/auth/get-session") return respond(null);
    return respond(null);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/invite/token-1");

  expect(await screen.findByRole("link", { name: "登录后接受邀请" })).toHaveAttribute(
    "href",
    "/login?next=%2Finvite%2Ftoken-1",
  );
});

it("shows organization members on a dedicated organization page", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs" && init?.method === "GET") {
      return respond([{ id: "org-1", name: "核心团队", status: "active" }]);
    }
    if (path === "/api/orgs/org-1/projects" && init?.method === "GET") return respond([]);
    if (path === "/api/orgs/org-1/members") {
      return respond([
        {
          id: "member-1",
          orgId: "org-1",
          principalType: "user",
          principalId: "user-1",
          displayName: "Owner",
          status: "active",
          role: "owner",
          permissions: [{ permissionKey: "users:invite", scope: null }],
          createdAt: "2026-08-28T00:00:00Z",
          updatedAt: "2026-08-28T00:00:00Z",
        },
      ]);
    }
    if (path === "/api/orgs/org-1/invites") return respond([]);
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/members");

  expect(await screen.findByRole("heading", { name: "组织成员" })).toBeInTheDocument();
  expect(await screen.findByText("Owner")).toBeInTheDocument();
  const organizationNavigation = within(screen.getByRole("navigation", { name: "组织导航" }));
  expect(organizationNavigation.getByRole("link", { name: "成员" })).toHaveClass("active");

  await userEvent.click(screen.getByRole("button", { name: "设置" }));
  const settings = within(screen.getByRole("dialog", { name: "设置" }));
  expect(settings.queryByText("成员与权限")).not.toBeInTheDocument();
});
