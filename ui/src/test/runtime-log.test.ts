import { describe, expect, it } from "vitest";

import { formatRuntimeLog } from "../utils/runtimeLog";

describe("formatRuntimeLog", () => {
  it("turns streamed Codex JSONL into readable progress", () => {
    const content = [
      "[octopus] Codex CLI 已启动，正在等待运行时事件。",
      '{"type":"thread.started","thread_id":"thread-1"}',
      '{"type":"turn.started"}',
      '{"type":"item.started","item":{"type":"command_execution","command":"rg -n TODO server"}}',
      '{"type":"item.completed","item":{"type":"command_execution","exit_code":0}}',
      '{"type":"item.completed","item":{"type":"agent_message","text":"任务完成"}}',
      '{"type":"turn.completed","usage":{}}',
    ].join("\n");

    expect(formatRuntimeLog(content)).toBe([
      "[octopus] Codex CLI 已启动，正在等待运行时事件。",
      "[Codex] 会话已启动",
      "[Codex] 开始处理任务",
      "[Codex] 正在执行命令：rg -n TODO server",
      "[Codex] 命令执行完成（退出码 0）",
      "[Codex 回复] 任务完成",
      "[Codex] 本轮处理完成",
    ].join("\n"));
  });

  it("keeps unknown and partial output unchanged", () => {
    expect(formatRuntimeLog("plain output\n{partial")).toBe("plain output\n{partial");
  });
});
