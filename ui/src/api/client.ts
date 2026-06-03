export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function rootCauseMessage(message: string): string {
  const value = message.trim();
  if (!value) return value;
  const sqliteMatch = value.match(/\(sqlite3\.[^)]+\)\s*([^\r\n[]+)/i);
  if (sqliteMatch?.[1]?.trim()) return sqliteMatch[1].trim();
  const sqlalchemyMatch = value.match(/\(sqlalchemy\.[^)]+\)\s*([^\r\n[]+)/i);
  if (sqlalchemyMatch?.[1]?.trim()) return sqlalchemyMatch[1].trim();
  const firstLine = value.split(/\r?\n/).find((line) => line.trim());
  return firstLine?.trim() ?? value;
}

async function parseError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown; error?: unknown; message?: unknown };
    if (typeof body.detail === "string") {
      return friendlyBackendError(rootCauseMessage(body.detail));
    }
    if (body.detail && typeof body.detail === "object") {
      const detail = body.detail as { error?: unknown; message?: unknown; reason?: unknown };
      const message = detail.message ?? detail.error ?? detail.reason;
      if (typeof message === "string") return friendlyBackendError(rootCauseMessage(message));
    }
    if (typeof body.message === "string") return friendlyBackendError(rootCauseMessage(body.message));
    if (typeof body.error === "string") return friendlyBackendError(rootCauseMessage(body.error));
  } catch {
    // Fall through to the HTTP status when a non-JSON error is returned.
  }
  return `Request failed (${response.status})`;
}

function friendlyBackendError(message: string): string {
  const normalized = message.trim();
  if (!normalized) return normalized;
  const lower = normalized.toLowerCase();
  if (lower.includes("object not found")) return "存储对象不存在";
  if (lower.includes("asset not found")) return "资产不存在";
  if (lower.includes("storage unavailable")) return "存储服务不可用";
  if (lower.includes("provider mismatch")) return "存储 Provider 不匹配";
  return normalized;
}

export async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body !== undefined && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    throw new ApiError(response.status, await parseError(response));
  }
  if (response.status === 204) {
    return {} as T;
  }
  const text = await response.text();
  if (!text) {
    return {} as T;
  }
  return JSON.parse(text) as T;
}

export function jsonRequest<T>(
  path: string,
  method: "POST" | "PATCH",
  body: unknown,
  options: Omit<RequestInit, "body" | "method"> = {},
): Promise<T> {
  return request<T>(path, { ...options, method, body: JSON.stringify(body) });
}
