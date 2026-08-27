type JsonRecord = Record<string, unknown>;

export function formatRuntimeLog(content: string | null | undefined): string {
  if (!content) return "";
  return content
    .split(/\r?\n/)
    .map((line) => formatRuntimeLogLine(line))
    .join("\n");
}

function formatRuntimeLogLine(line: string): string {
  const trimmed = line.trim();
  if (!trimmed.startsWith("{")) return line;
  let event: JsonRecord;
  try {
    const parsed = JSON.parse(trimmed);
    if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") return line;
    event = parsed as JsonRecord;
  } catch {
    return line;
  }
  const eventType = stringValue(event.type);
  const item = jsonRecord(event.item);
  const itemType = stringValue(item?.type);
  if (eventType === "thread.started") return "[Codex] 会话已启动";
  if (eventType === "turn.started") return "[Codex] 开始处理任务";
  if (eventType === "turn.completed") return "[Codex] 本轮处理完成";
  if (eventType === "turn.failed" || eventType === "error") {
    const error = jsonRecord(event.error);
    const message = stringValue(event.message) || stringValue(error?.message);
    return message ? `[Codex] 执行失败：${message}` : "[Codex] 执行失败";
  }
  if (eventType === "item.started") {
    if (itemType === "command_execution") {
      const command = stringValue(item?.command);
      return command ? `[Codex] 正在执行命令：${compact(command)}` : "[Codex] 正在执行命令";
    }
    if (itemType === "file_change") return "[Codex] 正在修改文件";
    if (itemType === "reasoning") return "[Codex] 正在分析";
    if (itemType) return `[Codex] 开始执行：${itemType}`;
  }
  if (eventType === "item.completed") {
    if (itemType === "agent_message") {
      const text = stringValue(item?.text);
      return text ? `[Codex 回复] ${text}` : "[Codex] 已生成回复";
    }
    if (itemType === "command_execution") {
      const exitCode = item?.exit_code;
      return typeof exitCode === "number"
        ? `[Codex] 命令执行完成（退出码 ${exitCode}）`
        : "[Codex] 命令执行完成";
    }
    if (itemType === "file_change") return "[Codex] 文件修改完成";
    if (itemType === "reasoning") return "[Codex] 分析完成";
    if (itemType) return `[Codex] 执行完成：${itemType}`;
  }
  return line;
}

function jsonRecord(value: unknown): JsonRecord | null {
  return value && !Array.isArray(value) && typeof value === "object" ? value as JsonRecord : null;
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function compact(value: string, limit = 240): string {
  const normalized = value.replace(/\s+/g, " ").trim();
  return normalized.length <= limit ? normalized : `${normalized.slice(0, limit).trimEnd()}…`;
}
