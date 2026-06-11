import { getLocalePreference } from "./locale";

const STATUS_LABELS: Record<string, string> = {
  active: "活跃",
  approved: "已同意",
  archived: "已归档",
  achieved: "已达成",
  backlog: "待规划",
  blocked: "阻塞",
  cancelled: "已取消",
  completed: "已完成",
  done: "已完成",
  error: "错误",
  failed: "失败",
  "failed-runs": "失败运行",
  idle: "空闲",
  in_progress: "进行中",
  in_review: "评审中",
  ok: "正常",
  paused: "已暂停",
  pass: "通过",
  passed: "通过",
  pending_approval: "待审批",
  pending: "待处理",
  planned: "已计划",
  queued: "排队中",
  resolved: "已解决",
  rejected: "已拒绝",
  revision_requested: "需修改",
  running: "运行中",
  succeeded: "成功",
  success: "成功",
  terminated: "已终止",
  timed_out: "已超时",
  todo: "待处理",
  warning: "警告",
  approvals: "审批",
  "budget-alerts": "预算提醒",
  chat: "对话",
  issues: "任务",
  "join-requests": "加入申请",
};

const EN_STATUS_LABELS: Record<string, string> = {
  active: "Active",
  approved: "Approved",
  archived: "Archived",
  achieved: "Achieved",
  backlog: "Backlog",
  blocked: "Blocked",
  cancelled: "Cancelled",
  completed: "Completed",
  done: "Completed",
  error: "Error",
  failed: "Failed",
  "failed-runs": "Failed runs",
  idle: "Idle",
  in_progress: "In progress",
  in_review: "In review",
  ok: "OK",
  paused: "Paused",
  pass: "Pass",
  passed: "Passed",
  pending_approval: "Pending approval",
  pending: "Pending",
  planned: "Planned",
  queued: "Queued",
  resolved: "Resolved",
  rejected: "Rejected",
  revision_requested: "Revision requested",
  running: "Running",
  succeeded: "Succeeded",
  success: "Success",
  terminated: "Terminated",
  timed_out: "Timed out",
  todo: "To do",
  warning: "Warning",
  approvals: "Approvals",
  "budget-alerts": "Budget alerts",
  chat: "Chat",
  issues: "Issues",
  "join-requests": "Join requests",
};

const PRIORITY_LABELS: Record<string, string> = {
  critical: "紧急",
  high: "高",
  low: "低",
  medium: "中",
};

const EN_PRIORITY_LABELS: Record<string, string> = {
  critical: "Critical",
  high: "High",
  low: "Low",
  medium: "Medium",
};

const ROLE_LABELS: Record<string, string> = {
  ceo: "CEO",
  cfo: "CFO",
  cmo: "CMO",
  cto: "CTO",
  designer: "设计",
  devops: "运维",
  engineer: "工程",
  general: "通用",
  pm: "产品",
  qa: "测试",
  researcher: "研究",
  reviewer: "评审",
};

const EN_ROLE_LABELS: Record<string, string> = {
  ceo: "CEO",
  cfo: "CFO",
  cmo: "CMO",
  cto: "CTO",
  designer: "Designer",
  devops: "DevOps",
  engineer: "Engineer",
  general: "General",
  pm: "PM",
  qa: "QA",
  researcher: "Researcher",
  reviewer: "Reviewer",
};

const SOURCE_LABELS: Record<string, string> = {
  assignment: "任务分配",
  automation: "自动化",
  bundled: "内置",
  "built-in": "内置",
  built_in: "内置",
  community: "社区",
  community_preset: "社区",
  external: "外部",
  local: "本地",
  manual: "手动",
  on_demand: "手动触发",
  runtime: "运行时",
  preset: "预置",
  review: "评审",
  system: "系统",
  system_bundled: "内置",
  timer: "定时心跳",
};

const EN_SOURCE_LABELS: Record<string, string> = {
  assignment: "Assignment",
  automation: "Automation",
  bundled: "Built-in",
  "built-in": "Built-in",
  built_in: "Built-in",
  community: "Community",
  community_preset: "Community",
  external: "External",
  local: "Local",
  manual: "Manual",
  on_demand: "Manual",
  runtime: "Runtime",
  preset: "Preset",
  review: "Review",
  system: "System",
  system_bundled: "Built-in",
  timer: "Timer",
};

export function displayLabel(value: string | null | undefined): string {
  if (!value) return "-";
  if (getLocalePreference() === "en-US") {
    return EN_STATUS_LABELS[value] ?? EN_PRIORITY_LABELS[value] ?? EN_ROLE_LABELS[value] ?? EN_SOURCE_LABELS[value] ?? value;
  }
  return STATUS_LABELS[value] ?? PRIORITY_LABELS[value] ?? ROLE_LABELS[value] ?? SOURCE_LABELS[value] ?? value;
}

export function statusLabel(value: string | null | undefined): string {
  return displayLabel(value);
}

export function priorityLabel(value: string | null | undefined): string {
  return displayLabel(value);
}

export function roleLabel(value: string | null | undefined): string {
  return displayLabel(value);
}

export function sourceLabel(value: string | null | undefined): string {
  return displayLabel(value);
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(getLocalePreference(), {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export function formatMoneyCents(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "-";
  return new Intl.NumberFormat(getLocalePreference(), {
    currency: "USD",
    maximumFractionDigits: 2,
    style: "currency",
  }).format(value / 100);
}

export function formatBytes(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "-";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}
