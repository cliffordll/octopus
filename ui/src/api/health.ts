import { request } from "./client";
import type { ServerHealth } from "./types";

export const healthApi = {
  get: (): Promise<ServerHealth> => request<ServerHealth>("/api/health", { method: "GET" }),
};
