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
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") {
      return rootCauseMessage(body.detail);
    }
  } catch {
    // Fall through to the HTTP status when a non-JSON error is returned.
  }
  return `Request failed (${response.status})`;
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
