import { useState, type ReactNode } from "react";
import type { AgentRuntimeType } from "../api/types";

type RuntimeConfigFieldsProps = {
  advancedEditor?: ReactNode;
  runtime: AgentRuntimeType;
  showLiveProbeField?: boolean;
  showProbeTimeoutField?: boolean;
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
const LOCAL_RUNTIME_DEFAULT_COMMANDS: Partial<Record<AgentRuntimeType, string>> = {
  codex_local: "codex",
  claude_local: "claude",
  opencode_local: "opencode",
  openclaw_local: "openclaw",
};
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

function millisecondsAsSeconds(config: Record<string, unknown>, key: string): string {
  const value = config[key];
  return typeof value === "number" ? String(value / 1000) : "";
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
  if (runtime === "http") return "HTTP 接口参数";
  if (runtime === "openclaw_gateway") return "OpenClaw Gateway 参数";
  if (runtime === "process") return "进程参数";
  if (["codex_local", "claude_local", "opencode_local", "openclaw_local"].includes(runtime)) return "本地 CLI 参数";
  return `${runtime} 参数`;
}

function runtimeDefaultHint(runtime: AgentRuntimeType): string {
  if (runtime === "http") return "需配置接口地址 · 默认 POST · 30 秒超时";
  if (runtime === "openclaw_gateway") return "需配置网关地址 · 默认按任务建立会话 · 超时 120 秒";
  if (runtime === "process") return "需配置启动命令 · 默认组织工作区 · 不限制执行时间";
  if (["codex_local", "claude_local", "opencode_local", "openclaw_local"].includes(runtime)) return "默认本机 CLI 登录态 · 组织工作区 · 不限制执行时间";
  return "未填写项使用服务端推荐值";
}

function RuntimeFieldLabel({ defaultValue, name, required = false }: { defaultValue?: string; name: string; required?: boolean }) {
  return (
    <span className="runtime-config-field-label">
      <span>{name}</span>
      <small className={required ? "is-required" : undefined}>{required ? "必填" : `默认：${defaultValue}`}</small>
    </span>
  );
}

export function RuntimeConfigFields({ advancedEditor, runtime, showLiveProbeField = true, showProbeTimeoutField = true, value, onChange }: RuntimeConfigFieldsProps) {
  const [expanded, setExpanded] = useState(false);
  function setField(key: string, nextValue: unknown) {
    onChange(withoutEmpty({ ...value, [key]: nextValue }));
  }
  const configured = Object.keys(value).length > 0;

  function renderShell(children: ReactNode, layout: "three" | "four" | "gateway" = "three") {
    return (
      <div className="runtime-config-panel">
        <div className="runtime-config-summary">
          <div className="runtime-config-summary-text">
            <strong>{runtimeSummary(runtime)}</strong>
            <span className="muted">{configured ? "已自定义 · " : ""}{runtimeDefaultHint(runtime)}</span>
          </div>
          <button className="secondary small-button" onClick={() => setExpanded((current) => !current)} type="button">
            {expanded ? "收起参数" : "高级参数"}
          </button>
        </div>
        {expanded && (
          <div className={`runtime-config-fields runtime-config-fields--${layout}`}>
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
          <RuntimeFieldLabel name="接口地址" required />
          <input aria-label="接口地址" placeholder="https://runtime.example/execute" value={stringValue(value, "url")} onChange={(event) => setField("url", event.target.value)} />
        </label>
        <label>
          <RuntimeFieldLabel defaultValue="POST" name="请求方法" />
          <select aria-label="请求方法" value={stringValue(value, "method")} onChange={(event) => setField("method", event.target.value)}>
            <option value="">使用默认值</option>
            <option value="GET">GET</option>
            <option value="POST">POST</option>
            <option value="PUT">PUT</option>
            <option value="PATCH">PATCH</option>
          </select>
        </label>
        <label>
          <RuntimeFieldLabel defaultValue="30 秒" name="请求超时（秒）" />
          <input aria-label="请求超时（秒）" min="0" placeholder="30" type="number" value={numberValue(value, "timeoutSec")} onChange={(event) => setField("timeoutSec", event.target.value ? Number(event.target.value) : "")} />
        </label>
        <label>
          <RuntimeFieldLabel defaultValue="空对象" name="请求头（JSON）" />
          <textarea aria-label="请求头（JSON）" className="config-editor" placeholder={'例如 {"Authorization":"Bearer ..."}'} value={JSON.stringify(value.headers ?? {}, null, 2)} onChange={(event) => setField("headers", parseJsonObjectField(event.target.value))} />
        </label>
      </>,
      "three",
    );
  }

  if (runtime === "openclaw_gateway") {
    return renderShell(
      <>
        <label>
          <RuntimeFieldLabel name="网关地址" required />
          <input aria-label="网关地址" placeholder="wss://gateway.example/ws" value={stringValue(value, "url")} onChange={(event) => setField("url", event.target.value)} />
        </label>
        <label>
          <RuntimeFieldLabel defaultValue="无" name="认证令牌" />
          <input aria-label="认证令牌" autoComplete="off" placeholder="网关需要认证时填写" type="password" value={stringValue(value, "authToken")} onChange={(event) => setField("authToken", event.target.value)} />
        </label>
        <label>
          <RuntimeFieldLabel defaultValue="按任务" name="会话策略" />
          <select aria-label="会话策略" value={stringValue(value, "sessionKeyStrategy")} onChange={(event) => setField("sessionKeyStrategy", event.target.value)}>
            <option value="">使用默认值</option>
            <option value="issue">按任务</option>
            <option value="run">按运行</option>
            <option value="fixed">固定会话</option>
          </select>
        </label>
        <label className="runtime-config-field-half">
          <RuntimeFieldLabel defaultValue="120 秒" name="连接超时（秒）" />
          <input aria-label="连接超时（秒）" min="0" placeholder="120" type="number" value={numberValue(value, "timeoutSec")} onChange={(event) => setField("timeoutSec", event.target.value ? Number(event.target.value) : "")} />
        </label>
        <label className="runtime-config-field-half">
          <RuntimeFieldLabel defaultValue="120 秒" name="等待超时（秒）" />
          <input aria-label="等待超时（秒）" min="0" placeholder="120" type="number" value={millisecondsAsSeconds(value, "waitTimeoutMs")} onChange={(event) => setField("waitTimeoutMs", event.target.value ? Number(event.target.value) * 1000 : "")} />
        </label>
        <label>
          <RuntimeFieldLabel defaultValue="空对象" name="请求头（JSON）" />
          <textarea aria-label="请求头（JSON）" className="config-editor" placeholder="{}" value={JSON.stringify(value.headers ?? {}, null, 2)} onChange={(event) => setField("headers", parseJsonObjectField(event.target.value))} />
        </label>
        <label>
          <RuntimeFieldLabel defaultValue="标准任务与运行载荷" name="载荷模板（JSON）" />
          <textarea aria-label="载荷模板（JSON）" className="config-editor" placeholder="{}" value={JSON.stringify(value.payloadTemplate ?? {}, null, 2)} onChange={(event) => setField("payloadTemplate", parseJsonObjectField(event.target.value))} />
        </label>
      </>,
      "gateway",
    );
  }

  if (runtime === "process") {
    return renderShell(
      <>
        <div className="runtime-config-check-row">
          <span>
            <strong>内置进程示例</strong>
            <small>用于验证服务端可以启动外部进程并收集输出，工作目录留空即可。</small>
          </span>
          <button className="secondary small-button" type="button" onClick={() => onChange(PROCESS_DEMO_CONFIG)}>
            使用示例
          </button>
        </div>
        <label>
          <RuntimeFieldLabel name="启动命令" required />
          <input aria-label="启动命令" placeholder="例如 uv" value={stringValue(value, "command")} onChange={(event) => setField("command", event.target.value)} />
        </label>
        <label>
          <RuntimeFieldLabel defaultValue="无" name="命令参数" />
          <input aria-label="命令参数" placeholder="多个参数用逗号分隔" value={stringListValue(value, "args")} onChange={(event) => setField("args", parseList(event.target.value))} />
        </label>
        <label>
          <RuntimeFieldLabel defaultValue="组织工作区" name="工作目录" />
          <input aria-label="工作目录" placeholder="留空使用组织工作区" value={stringValue(value, "cwd")} onChange={(event) => setField("cwd", event.target.value)} />
        </label>
        <label>
          <RuntimeFieldLabel defaultValue="不限制" name="执行超时（秒）" />
          <input aria-label="执行超时（秒）" min="0" placeholder="0" type="number" value={numberValue(value, "timeoutSec")} onChange={(event) => setField("timeoutSec", event.target.value ? Number(event.target.value) : "")} />
        </label>
      </>,
      "four",
    );
  }

  const defaultCommand = LOCAL_RUNTIME_DEFAULT_COMMANDS[runtime] ?? "CLI";
  return renderShell(
    <>
      <label>
        <RuntimeFieldLabel defaultValue={defaultCommand} name="启动命令" />
        <input aria-label="启动命令" placeholder={`留空使用 ${defaultCommand}`} value={stringValue(value, "command")} onChange={(event) => setField("command", event.target.value)} />
      </label>
      <label>
        <RuntimeFieldLabel defaultValue="组织工作区" name="工作目录" />
        <input aria-label="工作目录" placeholder="留空使用组织工作区" value={stringValue(value, "cwd")} onChange={(event) => setField("cwd", event.target.value)} />
      </label>
      <label>
        <RuntimeFieldLabel defaultValue="无" name="附加参数" />
        <input aria-label="附加参数" placeholder="多个参数用逗号分隔" value={stringListValue(value, "extraArgs")} onChange={(event) => setField("extraArgs", parseList(event.target.value))} />
      </label>
      <label>
        <RuntimeFieldLabel defaultValue="不限制" name="执行超时（秒）" />
        <input aria-label="执行超时（秒）" min="0" placeholder="0" type="number" value={numberValue(value, "timeoutSec")} onChange={(event) => setField("timeoutSec", event.target.value ? Number(event.target.value) : "")} />
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
      {showLiveProbeField && <label className="runtime-config-check-row">
        <strong>实时探测</strong>
        <input aria-label="实时探测运行时" checked={value.liveProbe === true} type="checkbox" onChange={(event) => setField("liveProbe", event.target.checked ? true : "")} />
        <small>保存或测试时真实检查本地 CLI / 适配器是否可用；默认关闭。</small>
      </label>}
      {showProbeTimeoutField && <label>
        <RuntimeFieldLabel defaultValue="5 秒" name="检查超时（秒）" />
        <input aria-label="检查超时（秒）" min="0" placeholder="5" type="number" value={numberValue(value, "probeTimeoutSec")} onChange={(event) => setField("probeTimeoutSec", event.target.value ? Number(event.target.value) : "")} />
      </label>}
    </>,
    "four",
  );
}
