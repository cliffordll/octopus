import { useState, type ReactNode } from "react";
import type { AgentRuntimeType } from "../api/types";

type RuntimeConfigFieldsProps = {
  advancedEditor?: ReactNode;
  runtime: AgentRuntimeType;
  value: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
};

const UNSUPPORTED_RUNTIMES = new Set<AgentRuntimeType>([
  "gemini_local",
  "cursor",
  "pi_local",
  "hermes_local",
]);
const OPENCODE_SKIP_PERMISSIONS_ARG = "--dangerously-skip-permissions";
const PROCESS_DEMO_CONFIG = {
  command: "uv",
  args: ["run", "--no-sync", "python", "-m", "packages.runtimes.process.demo"],
  timeoutSec: 10,
};

function stringValue(config: Record<string, unknown>, key: string): string {
  const value = config[key];
  return typeof value === "string" ? value : "";
}

function numberValue(config: Record<string, unknown>, key: string): string {
  const value = config[key];
  return typeof value === "number" ? String(value) : "";
}

function stringListValue(config: Record<string, unknown>, key: string): string {
  const value = config[key];
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string").join(", ")
    : "";
}

function withoutEmpty(next: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(next).filter(([, value]) => {
      if (value === "" || value === undefined || value === null) return false;
      if (Array.isArray(value) && value.length === 0) return false;
      return true;
    }),
  );
}

function parseList(value: string): string[] {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}

function parseJsonObjectField(value: string): Record<string, unknown> | string {
  if (!value.trim()) return "";
  try {
    const parsed: unknown = JSON.parse(value);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>;
    }
  } catch {
    return value;
  }
  return value;
}

function hasOpenCodeSkipPermissions(config: Record<string, unknown>): boolean {
  return stringListValue(config, "extraArgs").split(",").map((item) => item.trim()).includes(OPENCODE_SKIP_PERMISSIONS_ARG);
}

function setOpenCodeSkipPermissions(config: Record<string, unknown>, enabled: boolean): Record<string, unknown> {
  const extraArgs = stringListValue(config, "extraArgs")
    .split(",")
    .map((item) => item.trim())
    .filter((item) => item && item !== OPENCODE_SKIP_PERMISSIONS_ARG);
  if (enabled) extraArgs.push(OPENCODE_SKIP_PERMISSIONS_ARG);
  return withoutEmpty({ ...config, extraArgs });
}

function runtimeSummary(runtime: AgentRuntimeType): string {
  if (runtime === "http") return "HTTP endpoint runtime";
  if (runtime === "openclaw_gateway") return "OpenClaw Gateway runtime";
  if (runtime === "process") return "Process runtime";
  if (["codex_local", "claude_local", "opencode_local"].includes(runtime)) return "Local CLI runtime";
  return `${runtime} runtime`;
}

function runtimeDefaultHint(runtime: AgentRuntimeType): string {
  if (runtime === "http") return "默认 POST，30s 超时，无自定义 headers";
  if (runtime === "openclaw_gateway") return "默认按 run 建立会话，30s 连接，5 分钟等待";
  if (runtime === "process") return "默认使用 server 侧命令配置和当前工作目录";
  if (["codex_local", "claude_local", "opencode_local"].includes(runtime)) return "默认使用本机 CLI 登录态和 server 工作目录";
  return "使用 server 推荐默认配置";
}

export function RuntimeConfigFields({ advancedEditor, runtime, value, onChange }: RuntimeConfigFieldsProps) {
  const [expanded, setExpanded] = useState(false);
  function setField(key: string, nextValue: unknown) {
    onChange(withoutEmpty({ ...value, [key]: nextValue }));
  }
  const configured = Object.keys(value).length > 0;

  function renderShell(children: ReactNode) {
    return (
      <div className="runtime-config-panel">
        <div className="runtime-config-summary">
          <div className="runtime-config-summary-text">
            <strong>{runtimeSummary(runtime)}</strong>
            <span className="muted">{configured ? "已配置，可按需调整" : "使用推荐默认配置"}</span>
            <small>{runtimeDefaultHint(runtime)}</small>
          </div>
          <button className="secondary small-button" onClick={() => setExpanded((current) => !current)} type="button">
            {expanded ? "收起配置" : "个性化配置"}
          </button>
        </div>
        {expanded && (
          <div className="runtime-config-fields">
            {children}
            {advancedEditor}
          </div>
        )}
      </div>
    );
  }

  if (UNSUPPORTED_RUNTIMES.has(runtime)) {
    return (
      <div className="runtime-config-panel">
        <p className="field-warning">{runtime} 当前未纳入完整执行能力；请保留为空配置或选择已支持 runtime。</p>
      </div>
    );
  }

  if (runtime === "http") {
    return renderShell(
      <>
        <label>
          Endpoint URL
          <input placeholder="默认使用 server 配置的 endpoint" value={stringValue(value, "url")} onChange={(event) => setField("url", event.target.value)} />
        </label>
        <label>
          HTTP method
          <select value={stringValue(value, "method")} onChange={(event) => setField("method", event.target.value)}>
            <option value="">默认</option>
            <option value="GET">GET</option>
            <option value="POST">POST</option>
            <option value="PUT">PUT</option>
            <option value="PATCH">PATCH</option>
          </select>
        </label>
        <label>
          Timeout seconds
          <input min="0" placeholder="30" type="number" value={numberValue(value, "timeoutSec")} onChange={(event) => setField("timeoutSec", event.target.value ? Number(event.target.value) : "")} />
        </label>
        <label>
          Headers JSON
          <textarea className="config-editor" placeholder={'默认 {}，例如 {"Authorization":"Bearer ..."}'} value={JSON.stringify(value.headers ?? {}, null, 2)} onChange={(event) => setField("headers", parseJsonObjectField(event.target.value))} />
        </label>
      </>,
    );
  }

  if (runtime === "openclaw_gateway") {
    return renderShell(
      <>
        <label>
          Gateway URL
          <input placeholder="默认使用 server 配置；例如 wss://gateway.example/ws" value={stringValue(value, "url")} onChange={(event) => setField("url", event.target.value)} />
        </label>
        <label>
          Auth token
          <input placeholder="默认使用 server secret，不在 UI 明文保存" value={stringValue(value, "authToken")} onChange={(event) => setField("authToken", event.target.value)} />
        </label>
        <label>
          Session key strategy
          <select value={stringValue(value, "sessionKeyStrategy")} onChange={(event) => setField("sessionKeyStrategy", event.target.value)}>
            <option value="">默认</option>
            <option value="run">run</option>
            <option value="issue">issue</option>
            <option value="fixed">fixed</option>
          </select>
        </label>
        <label>
          Timeout seconds
          <input min="0" placeholder="30" type="number" value={numberValue(value, "timeoutSec")} onChange={(event) => setField("timeoutSec", event.target.value ? Number(event.target.value) : "")} />
        </label>
        <label>
          Wait timeout ms
          <input min="0" placeholder="300000" type="number" value={numberValue(value, "waitTimeoutMs")} onChange={(event) => setField("waitTimeoutMs", event.target.value ? Number(event.target.value) : "")} />
        </label>
        <label>
          Headers JSON
          <textarea className="config-editor" placeholder='默认 {}' value={JSON.stringify(value.headers ?? {}, null, 2)} onChange={(event) => setField("headers", parseJsonObjectField(event.target.value))} />
        </label>
        <label>
          Payload template JSON
          <textarea className="config-editor" placeholder="默认使用标准 issue/run payload" value={JSON.stringify(value.payloadTemplate ?? {}, null, 2)} onChange={(event) => setField("payloadTemplate", parseJsonObjectField(event.target.value))} />
        </label>
      </>,
    );
  }

  if (runtime === "process") {
    return renderShell(
      <>
        <div className="runtime-config-check-row">
          <span>
            <strong>内置 process demo</strong>
            <small>验证 server 可以启动外部进程并收集 stdout；CWD 留空即可。</small>
          </span>
          <button className="secondary small-button" type="button" onClick={() => onChange(PROCESS_DEMO_CONFIG)}>
            使用内置 demo
          </button>
        </div>
        <label>
          Command
          <input placeholder="默认使用 server 侧命令" value={stringValue(value, "command")} onChange={(event) => setField("command", event.target.value)} />
        </label>
        <label>
          Args
          <input placeholder="默认无；逗号分隔" value={stringListValue(value, "args")} onChange={(event) => setField("args", parseList(event.target.value))} />
        </label>
        <label>
          CWD
          <input placeholder="默认组织工作区" value={stringValue(value, "cwd")} onChange={(event) => setField("cwd", event.target.value)} />
        </label>
      </>,
    );
  }

  return renderShell(
    <>
      <label>
        Command
        <input placeholder="默认使用 runtime 对应 CLI 命令" value={stringValue(value, "command")} onChange={(event) => setField("command", event.target.value)} />
      </label>
      <label>
        CWD
        <input placeholder="默认组织工作区" value={stringValue(value, "cwd")} onChange={(event) => setField("cwd", event.target.value)} />
      </label>
      <label>
        Extra args
        <input placeholder="默认无；逗号分隔" value={stringListValue(value, "extraArgs")} onChange={(event) => setField("extraArgs", parseList(event.target.value))} />
      </label>
      {runtime === "opencode_local" && (
        <label className="runtime-config-check-row">
          <strong>跳过确认</strong>
          <input
            aria-label="跳过 OpenCode 权限确认"
            checked={hasOpenCodeSkipPermissions(value)}
            type="checkbox"
            onChange={(event) => onChange(setOpenCodeSkipPermissions(value, event.target.checked))}
          />
          <small>使用 --dangerously-skip-permissions，自动批准未显式拒绝的本地工具权限请求；仅适用于本地可信开发环境。</small>
        </label>
      )}
      <label className="runtime-config-check-row">
        <strong>实时探测</strong>
        <input aria-label="实时探测运行时" checked={value.liveProbe === true} type="checkbox" onChange={(event) => setField("liveProbe", event.target.checked ? true : "")} />
        <small>保存或测试时真实检查本地 CLI / 适配器是否可用；默认关闭。</small>
      </label>
      <label>
        探测超时秒数
        <input min="0" placeholder="10" type="number" value={numberValue(value, "probeTimeoutSec")} onChange={(event) => setField("probeTimeoutSec", event.target.value ? Number(event.target.value) : "")} />
      </label>
    </>,
  );
}
