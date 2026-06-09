import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { OrganizationSettingsPanel } from "../components/OrganizationSettingsPanel";
import { respond } from "./render-app";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const availablePlugin = {
  id: "github.connector",
  displayName: "GitHub",
  version: "0.1.0",
  sourcePath: "server/plugins/bundled/plugin-github",
  example: true,
  manifest: {
    id: "github.connector",
    apiVersion: 1,
    version: "0.1.0",
    displayName: "GitHub",
    description: "Repository and pull request integration.",
    capabilities: ["http.outbound", "webhooks.receive"],
    entrypoints: { worker: "./dist/worker.js", ui: "./dist/ui" },
  },
};

const installedPlugin = {
  id: "plugin-1",
  pluginKey: "github.connector",
  displayName: "GitHub",
  version: "0.1.0",
  status: "installed",
  sourceType: "bundled",
  sourceLocator: "server/plugins/bundled/plugin-github",
  manifest: availablePlugin.manifest,
  installedAt: null,
  enabledAt: null,
  disabledAt: null,
  uninstalledAt: null,
  createdAt: "",
  updatedAt: "",
};

function renderSettings() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <OrganizationSettingsPanel orgId="org-1" />
    </QueryClientProvider>,
  );
}

it("shows bundled plugins and manages lifecycle actions", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path.startsWith("/api/orgs/org-1/runtime-providers") && init?.method === "GET") return respond([]);
    if (path === "/api/orgs" && init?.method === "GET") return respond([]);
    if (path === "/api/plugins/available" && init?.method === "GET") {
      return respond({ items: [availablePlugin], errors: [] });
    }
    if (path === "/api/plugins" && init?.method === "GET") return respond([]);
    if (path === "/api/plugins/install" && init?.method === "POST") return respond(installedPlugin, 201);
    return respond({});
  });
  vi.stubGlobal("fetch", fetchMock);

  renderSettings();

  await userEvent.click(screen.getByRole("button", { name: /插件/ }));
  expect(await screen.findByText("GitHub")).toBeInTheDocument();
  expect(screen.getByText("未安装")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "安装" }));

  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/plugins/install",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          manifest: availablePlugin.manifest,
          sourceType: "bundled",
          sourceLocator: "server/plugins/bundled/plugin-github",
        }),
      }),
    );
  });
});

it("shows installed plugin details and enables it", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path.startsWith("/api/orgs/org-1/runtime-providers") && init?.method === "GET") return respond([]);
    if (path === "/api/orgs" && init?.method === "GET") return respond([]);
    if (path === "/api/plugins/available" && init?.method === "GET") {
      return respond({ items: [availablePlugin], errors: [] });
    }
    if (path === "/api/plugins" && init?.method === "GET") return respond([installedPlugin]);
    if (path === "/api/plugins/plugin-1/jobs" && init?.method === "GET") {
      return respond([{ id: "job-1", pluginId: "plugin-1", jobKey: "sync", displayName: "Sync", schedule: null, enabled: true, createdAt: "", updatedAt: "" }]);
    }
    if (path === "/api/plugins/plugin-1/logs" && init?.method === "GET") {
      return respond([{ id: "log-1", pluginId: "plugin-1", level: "info", message: "Installed", detailsJson: null, createdAt: "" }]);
    }
    if (path === "/api/plugins/plugin-1/enable" && init?.method === "POST") {
      return respond({ ...installedPlugin, status: "ready" });
    }
    return respond({});
  });
  vi.stubGlobal("fetch", fetchMock);

  renderSettings();

  await userEvent.click(screen.getByRole("button", { name: /插件/ }));
  await userEvent.click(await screen.findByRole("button", { name: /GitHub/ }));
  expect(await screen.findByText("Sync")).toBeInTheDocument();
  expect(await screen.findByText("Installed")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "启用" }));

  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/plugins/plugin-1/enable",
      expect.objectContaining({ method: "POST" }),
    );
  });
});
