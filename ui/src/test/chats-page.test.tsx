import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { renderApp, respond } from "./render-app";

afterEach(() => {
  vi.unstubAllGlobals();
});

it("creates a chat and sends messages to its selected agent", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/chats" && init?.method === "GET") {
      return respond([{ id: "chat-1", title: "支持会话", status: "active" }]);
    }
    if (path === "/api/chats/chat-1" && init?.method === "GET") {
      return respond({ id: "chat-1", orgId: "org-1", title: "支持会话", status: "active" });
    }
    if (path === "/api/chats/chat-1/messages" && init?.method === "GET") {
      return respond([{ id: "message-1", role: "assistant", body: "已有回复", status: "completed" }]);
    }
    return respond({ messages: [{ id: "message-2", body: "新回复" }] }, 201);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/chats/chat-1");
  expect(await screen.findByRole("heading", { name: "支持会话" })).toBeInTheDocument();
  expect(await screen.findByText("已有回复")).toBeInTheDocument();

  await userEvent.type(screen.getByLabelText("消息"), "现在状态？");
  await userEvent.click(screen.getByRole("button", { name: "发送" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/chats/chat-1/messages",
    expect.objectContaining({ method: "POST", body: JSON.stringify({ body: "现在状态？" }) }),
  );
});
