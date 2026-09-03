import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { agentsApi } from "../api/agents";
import { issuesApi } from "../api/issues";
import { organizationsApi } from "../api/organizations";
import { projectsApi } from "../api/projects";
import type {
  ExecutionWorkspace,
  ExecutionWorkspaceFiles,
  Agent,
  IssueListItem,
  IssueWorkProduct,
  OrganizationResource,
  ProjectCodebase,
  ProjectResourceRole,
  ProjectStatus,
  ProjectWorkspace,
  WorkspaceFileTreeNode,
} from "../api/types";
import { Badge } from "../components/Badge";
import { TertiaryPageHeader, TertiaryPageShell, TertiaryPageViewport } from "../components/TertiaryPageShell";
import { ErrorNotice } from "../components/ErrorNotice";
import { IssueStatusBoard } from "../components/IssueStatusBoard";
import { ProjectWorkspaceExplorer } from "../components/ProjectWorkspaceExplorer";
import { formatDateTime, statusLabel } from "../utils/display";
import { OrgWorkspace } from "./OrganizationPage";

const STATUSES: ProjectStatus[] = ["backlog", "planned", "in_progress", "completed", "cancelled"];
const ROLES: ProjectResourceRole[] = [
  "working_set",
  "reference",
  "tracking",
  "deliverable",
  "background",
];
const RESOURCE_KINDS: OrganizationResource["kind"][] = ["file", "directory", "url", "connector_object"];
const RESOURCE_KIND_LABELS: Record<OrganizationResource["kind"], string> = {
  connector_object: "连接器对象",
  directory: "目录",
  file: "文件",
  url: "URL",
};
const RESOURCE_ROLE_LABELS: Record<ProjectResourceRole, string> = {
  background: "背景资料",
  deliverable: "交付物",
  reference: "参考",
  tracking: "跟踪",
  working_set: "工作集",
};
const PROJECT_PAUSE_REASON_LABELS = {
  budget: "预算限制",
  manual: "手动暂停",
  system: "系统暂停",
} as const;
const WORKSPACE_POLICY_MODES = ["shared_workspace", "isolated_workspace", "operator_branch"] as const;
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

type WorkspacePolicyMode = (typeof WORKSPACE_POLICY_MODES)[number];

const WORKSPACE_POLICY_OPTIONS: Array<{
  description: string;
  label: string;
  mode: WorkspacePolicyMode;
}> = [
  {
    mode: "shared_workspace",
    label: "共享工作区",
    description: "直接使用项目代码目录，不创建任务级执行目录。",
  },
  {
    mode: "isolated_workspace",
    label: "独立工作区",
    description: "从项目代码创建独立 Git worktree，适合隔离改动。",
  },
  {
    mode: "operator_branch",
    label: "操作分支",
    description: "在操作分支上推进代码改动，需先具备 Git 代码来源。",
  },
];

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function formatJson(value: Record<string, unknown> | null | undefined): string {
  return value ? JSON.stringify(value, null, 2) : "";
}

function parseJsonObject(value: string): Record<string, unknown> | null {
  if (!value.trim()) return null;
  const parsed: unknown = JSON.parse(value);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("代码任务执行方式必须是 JSON 对象。");
  }
  return parsed as Record<string, unknown>;
}

function parseGoalIds(value: string): string[] {
  const ids = value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  if (ids.some((id) => !UUID_PATTERN.test(id))) {
    throw new Error("目标 ID 必须是 UUID，多个目标请用逗号分隔。");
  }
  return ids;
}

function normalizeWorkspacePolicyMode(value: unknown): WorkspacePolicyMode {
  if (value === "project_primary") return "shared_workspace";
  if (value === "isolated") return "isolated_workspace";
  return WORKSPACE_POLICY_MODES.includes(value as WorkspacePolicyMode)
    ? value as WorkspacePolicyMode
    : "shared_workspace";
}

function workspacePolicyModeFromPolicy(value: Record<string, unknown> | null | undefined): WorkspacePolicyMode {
  if (!value) return "shared_workspace";
  const strategy = isRecord(value.workspaceStrategy) ? value.workspaceStrategy : null;
  return normalizeWorkspacePolicyMode(value.defaultMode ?? strategy?.mode);
}

function workspacePolicyDescription(mode: WorkspacePolicyMode): string {
  return WORKSPACE_POLICY_OPTIONS.find((option) => option.mode === mode)?.description ?? "";
}

function workspaceModeNotice(mode: string | null | undefined): string {
  if (mode !== "shared_workspace") return "";
  return "共享工作区不会隔离文件；多个任务可以操作同一目录，覆盖由路径约定、diff 审核和 closeout 控制。";
}

type PushCredentials = { username: string; password: string };

function promptForPushCredentials(): PushCredentials | null {
  const username = window.prompt("Git 用户名（留空则使用本机已有凭据）", "");
  if (username === null) return null;
  if (!username.trim()) return null;
  const password = window.prompt("GitHub token/PAT（不会保存，仅用于本次 push）", "");
  if (password === null || !password.trim()) return null;
  return { username: username.trim(), password };
}
function workspacePolicyForMode(currentJson: string, mode: WorkspacePolicyMode): string {
  let current: Record<string, unknown> = {};
  try {
    current = parseJsonObject(currentJson) ?? {};
  } catch {
    current = {};
  }
  const currentStrategy = isRecord(current.workspaceStrategy) ? current.workspaceStrategy : {};
  return formatJson({
    ...current,
    enabled: true,
    defaultMode: mode,
    workspaceStrategy: {
      ...currentStrategy,
      mode,
    },
  });
}

function nullableText(value: string | null | undefined): string {
  return value && value.trim() ? value : "未设置";
}

function projectWorkspaceDisplay(workspace: ProjectWorkspace): string {
  if (workspace.cwd?.trim()) return workspace.cwd;
  if (workspace.repoUrl?.trim()) return "首次运行会创建受管 checkout";
  return "未设置本地 cwd 或仓库 URL";
}

function roleCount(
  resources: Array<{ role: ProjectResourceRole }>,
  role: ProjectResourceRole,
): number {
  return resources.filter((resource) => resource.role === role).length;
}

function resourceKindMark(kind: OrganizationResource["kind"] | undefined): string {
  switch (kind) {
    case "directory":
      return "D";
    case "file":
      return "F";
    case "connector_object":
      return "C";
    case "url":
    default:
      return "U";
  }
}

function workProductProjectPath(product: IssueWorkProduct): string {
  const metadata = product.metadata ?? {};
  const candidate = (typeof metadata.workspacePath === "string" ? metadata.workspacePath : null)
    ?? (typeof metadata.workspaceBrowserPath === "string" ? metadata.workspaceBrowserPath : null)
    ?? (typeof metadata.workspaceRelativePath === "string" ? metadata.workspaceRelativePath : null)
    ?? (typeof metadata.filePath === "string" ? metadata.filePath : null)
    ?? (typeof metadata.path === "string" ? metadata.path : null)
    ?? product.contentPath
    ?? product.url
    ?? product.externalId;
  return candidate?.trim() || `${product.type}/${product.title}`;
}

function isWorkspaceArtifactProduct(product: IssueWorkProduct): boolean {
  return product.type !== "commit";
}

function normalizedWorkspacePath(value: string): string {
  return value.replace(/\\/g, "/").replace(/^\/+/, "").trim();
}

function withProductFilesInTree(nodes: WorkspaceFileTreeNode[], products: IssueWorkProduct[]): WorkspaceFileTreeNode[] {
  const cloned: WorkspaceFileTreeNode[] = nodes.map((node) => ({ ...node, children: node.children ? withProductFilesInTree(node.children, []) : node.children }));
  const ensureDirectory = (siblings: WorkspaceFileTreeNode[], name: string, path: string): WorkspaceFileTreeNode => {
    const existing = siblings.find((node) => node.type === "directory" && node.name === name);
    if (existing) {
      existing.children = existing.children ?? [];
      return existing;
    }
    const created: WorkspaceFileTreeNode = { name, path, type: "directory", children: [] };
    siblings.push(created);
    siblings.sort((left, right) => (left.type === right.type ? left.name.localeCompare(right.name) : left.type === "directory" ? -1 : 1));
    return created;
  };

  for (const product of products) {
    const normalized = normalizedWorkspacePath(workProductProjectPath(product));
    const parts = normalized.split("/").filter(Boolean);
    if (parts.length === 0) continue;
    let siblings = cloned;
    let currentPath = "";
    for (const part of parts.slice(0, -1)) {
      currentPath = currentPath ? `${currentPath}/${part}` : part;
      const directory = ensureDirectory(siblings, part, currentPath);
      siblings = directory.children ?? [];
    }
    const fileName = parts.at(-1) ?? product.title;
    const filePath = currentPath ? `${currentPath}/${fileName}` : fileName;
    if (!siblings.some((node) => node.type === "file" && normalizedWorkspacePath(node.path) === filePath)) {
      siblings.push({
        name: fileName,
        path: filePath,
        type: "file",
        size: product.byteSize ?? null,
        modifiedAt: product.updatedAt ?? product.createdAt ?? null,
      });
      siblings.sort((left, right) => (left.type === right.type ? left.name.localeCompare(right.name) : left.type === "directory" ? -1 : 1));
    }
  }
  return cloned;
}

function productsByWorkspacePath(products: IssueWorkProduct[]): Map<string, IssueWorkProduct[]> {
  const grouped = new Map<string, IssueWorkProduct[]>();
  for (const product of products) {
    const path = normalizedWorkspacePath(workProductProjectPath(product));
    grouped.set(path, [...(grouped.get(path) ?? []), product]);
  }
  return grouped;
}

function ProjectWorkspaceDirectory({ agents, issues, orgId, products, workspace }: { agents: Agent[]; issues: Map<string, IssueListItem>; orgId: string; products: IssueWorkProduct[]; workspace: ExecutionWorkspace }) {
  const files = useQuery<ExecutionWorkspaceFiles>({
    queryKey: ["execution-workspace-files", workspace.id],
    queryFn: () => projectsApi.executionWorkspaceFiles(workspace.id),
  });
  const productsByPath = productsByWorkspacePath(products);
  const fileTree = withProductFilesInTree(files.data?.tree ?? [], products);
  return (
    <section className="project-workspace-directory" aria-label={`${workspace.name} 文件树`}>
      {files.data?.truncated && <div className="project-workspace-tree-status"><Badge>已截断</Badge></div>}
      {files.isLoading && <p className="project-resource-empty muted">正在加载项目目录...</p>}
      {files.error && <ErrorNotice error={files.error} />}
      {!files.isLoading && files.data && !files.data.available && <p className="project-resource-empty muted">{files.data.error ?? "当前工作区目录不可浏览。"}</p>}
      {!files.isLoading && files.data?.available && fileTree.length === 0 && <p className="project-resource-empty muted">项目目录为空。</p>}
      {files.data?.available && fileTree.length > 0 && (
        <ProjectWorkspaceExplorer agents={agents} issues={issues} nodes={fileTree} orgId={orgId} productsByPath={productsByPath} />
      )}
    </section>
  );
}
function ProjectWorkspaceArtifacts({
  agents,
  executionWorkspaces,
  issues,
  loading,
  orgId,
  products,
}: {
  agents: Agent[];
  executionWorkspaces: ExecutionWorkspace[];
  issues: IssueListItem[];
  loading: boolean;
  orgId: string;
  products: IssueWorkProduct[];
}) {
  const issueMap = new Map(issues.map((issue) => [issue.id, issue]));
  const executionWorkspaceMap = new Map(executionWorkspaces.map((workspace) => [workspace.id, workspace]));
  const visibleWorkspaceIds = new Set(executionWorkspaceMap.keys());
  const artifactProducts = products.filter(
    (product) => isWorkspaceArtifactProduct(product)
      && Boolean(product.executionWorkspaceId && visibleWorkspaceIds.has(product.executionWorkspaceId)),
  );
  const groupedProducts = new Map<string, IssueWorkProduct[]>();
  for (const product of artifactProducts) {
    const key = product.executionWorkspaceId || "unassigned";
    groupedProducts.set(key, [...(groupedProducts.get(key) ?? []), product]);
  }
  const workspaceIds = executionWorkspaces.map((workspace) => workspace.id);

  return (
    <section className="project-workspace-artifacts project-tab-panel-wide" aria-label="工作区产物">
      <div className="project-workspace-artifacts-body">
        {loading && <p className="muted">正在加载工作区产物...</p>}
        {!loading && executionWorkspaces.length === 0 && <p className="project-resource-empty muted">当前执行模式暂无工作区。任务开始运行后会显示在这里。</p>}
        <div className="project-artifact-workspace-list">
          {workspaceIds.map((workspaceId) => {
            const workspaceProducts = groupedProducts.get(workspaceId) ?? [];
            if (workspaceProducts.length === 0 && workspaceId === "unassigned") return null;
            const workspace = executionWorkspaceMap.get(workspaceId);
            return (
              <section className="project-artifact-workspace" key={workspaceId} aria-label={workspace?.name ?? "未绑定工作区"}>
                <div className="project-artifact-workspace-heading">
                  <div>
                    <strong>{workspace?.name ?? "未绑定工作区"}</strong>
                    <span title={workspace?.cwd ?? undefined}>{workspace?.cwd ?? "未记录执行目录"}</span>
                  </div>
                  <div className="project-workspace-badges">
                    {workspace?.mode && <Badge>{workspace.mode}</Badge>}
                    {workspace?.status && <Badge>{workspace.status}</Badge>}
                    <Badge>{workspaceProducts.length} 个产物</Badge>
                  </div>
                </div>
                {workspace && <ProjectWorkspaceDirectory agents={agents} issues={issueMap} orgId={orgId} products={workspaceProducts} workspace={workspace} />}
              </section>
            );
          })}
        </div>
      </div>
    </section>
  );
}
function ProjectOutputLocations({ codebase }: { codebase: ProjectCodebase | undefined }) {
  const workspaceRoot = codebase?.managedFolder;
  const artifactsPath = workspaceRoot ? `${workspaceRoot}/artifacts` : "未设置";
  const plansAndSkillsPath = workspaceRoot ? `${workspaceRoot}/plans · ${workspaceRoot}/skills` : "未设置";
  return (
    <details className="project-config-collapsible project-config-step-output" open>
      <summary>
        <span><strong>高级信息</strong><small>组织目录与产物位置</small></span>
        <Badge>只读</Badge>
      </summary>
      <div className="project-config-collapsible-body project-property-list">
        <div className="project-property-row">
          <span>组织草稿目录</span>
          <strong title={workspaceRoot ?? "未设置"}>{workspaceRoot ?? "未设置"}</strong>
        </div>
        <div className="project-property-row">
          <span>任务产物</span>
          <strong title={artifactsPath}>{artifactsPath}</strong>
        </div>
        <div className="project-property-row">
          <span>计划与技能</span>
          <strong title={plansAndSkillsPath}>{plansAndSkillsPath}</strong>
        </div>
      </div>
    </details>
  );
}

function ExecutionWorkspacePanel({
  abandonPending,
  archivePending,
  cleanupDiscardConfirmed,
  cleanupPending,
  createPrPending,
  diffPending,
  diffPreview,
  error,
  onAbandon,
  onArchive,
  onCleanup,
  onCleanupDiscardConfirmed,
  onCommit,
  onCreatePr,
  onLoadDiff,
  onMerge,
  onMergePreview,
  onPreparePr,
  onPush,
  onSelect,
  mergePending,
  mergePreview,
  mergePreviewPending,
  preparePrPending,
  pushPending,
  commitPending,
  selectedId,
  status,
  statusPending,
  workspaces,
}: {
  abandonPending: boolean;
  archivePending: boolean;
  cleanupDiscardConfirmed: boolean;
  cleanupPending: boolean;
  createPrPending: boolean;
  diffPending: boolean;
  diffPreview: string;
  error: unknown;
  onAbandon: (workspaceId: string) => void;
  onArchive: (workspaceId: string) => void;
  onCleanup: (workspaceId: string, discardDirty: boolean) => void;
  onCleanupDiscardConfirmed: (confirmed: boolean) => void;
  onCommit: (workspaceId: string) => void;
  onCreatePr: (workspaceId: string) => void;
  onLoadDiff: (workspaceId: string) => void;
  onMerge: (workspaceId: string) => void;
  onMergePreview: (workspaceId: string) => void;
  onPreparePr: (workspaceId: string) => void;
  onPush: (workspaceId: string) => void;
  onSelect: (workspaceId: string) => void;
  mergePending: boolean;
  mergePreview: string;
  mergePreviewPending: boolean;
  preparePrPending: boolean;
  pushPending: boolean;
  commitPending: boolean;
  selectedId: string;
  status: {
    git: { available: boolean; branch?: string | null; dirty?: boolean; entries?: string[]; summary?: string | null; error?: string | null } | null;
    lease: { locked: boolean; operationId: string | null; runId: string | null };
    canArchive: boolean;
  } | undefined;
  statusPending: boolean;
  workspaces: ExecutionWorkspace[];
}) {
  const selected = workspaces.find((workspace) => workspace.id === selectedId);
  const selectedDirty = Boolean(status?.git?.dirty);
  const gitAvailable = Boolean(status?.git?.available);
  const canCleanup = Boolean(status?.canArchive) || (selectedDirty && cleanupDiscardConfirmed && !status?.lease.locked);
  return (
    <details className="project-config-collapsible project-config-step-history">
      <summary>
        <span><strong>运行管理</strong><small>Git 状态、合并、提交与归档</small></span>
        <Badge>{workspaces.length} 条</Badge>
      </summary>
      <section className="project-config-collapsible-body project-workspace-manager" aria-label="任务运行记录">
        {Boolean(error) && <ErrorNotice error={error} />}
        <div className="project-workspace-list execution-workspace-list">
        {workspaces.length === 0 && <p className="project-workspace-empty">暂无任务运行记录。代码任务开始运行后会创建记录。</p>}
        {workspaces.map((workspace) => {
          const isSelected = workspace.id === selectedId;
          return (
            <div className={`project-workspace-item execution-workspace-row ${isSelected ? "selected" : ""}`} key={workspace.id}>
              <button
                className="execution-workspace-row-main"
                onClick={() => onSelect(workspace.id)}
                type="button"
              >
                <div className="execution-workspace-summary">
                  <strong className="execution-workspace-name">{workspace.name}</strong>
                  <div className="project-workspace-badges execution-workspace-badges">
                    <Badge>{workspace.mode}</Badge>
                    <Badge>{workspace.status}</Badge>
                    {workspace.branchName && <Badge>{workspace.branchName}</Badge>}
                  </div>
                  <span className="execution-workspace-path" title={nullableText(workspace.cwd)}>{nullableText(workspace.cwd)}</span>
                </div>
              </button>
              {isSelected && selected && (
                <div className="execution-workspace-row-detail">
                  <div className="execution-workspace-status-line">
                    <span>分支：{status?.git?.branch ?? selected.branchName ?? "未识别"}</span>
                    <span>Git：{statusPending ? "检查中..." : status?.git?.available ? (status.git.dirty ? "有未提交改动" : "干净") : status?.git?.error ?? "不可用"}</span>
                    <span>租约：{status?.lease.locked ? `运行中 ${status.lease.operationId ?? ""}` : "空闲"}</span>
                  </div>
                  {workspaceModeNotice(selected.mode) && <p className="issue-action-notice" role="note">{workspaceModeNotice(selected.mode)}</p>}
                  <div className="project-workspace-actions">
                    <button
                      className="secondary small-button"
                      disabled={diffPending || !gitAvailable}
                      onClick={() => onLoadDiff(selected.id)}
                      title={gitAvailable ? "查看当前工作目录的 Git diff" : "当前工作目录不是 Git 仓库，无法查看 diff"}
                      type="button"
                    >
                      查看 diff
                    </button>
                    <button className="secondary small-button" disabled={mergePreviewPending || selected.mode === "shared_workspace"} onClick={() => onMergePreview(selected.id)} type="button">检查 merge</button>
                    <button className="secondary small-button" disabled={mergePending || selected.mode === "shared_workspace" || Boolean(status?.lease.locked)} onClick={() => onMerge(selected.id)} type="button">merge 到目标分支</button>
                    <button className="secondary small-button" disabled={preparePrPending || selected.mode === "shared_workspace" || !selected.branchName} onClick={() => onPreparePr(selected.id)} type="button">准备 PR</button>
                    <button className="secondary small-button" disabled={commitPending || !selectedDirty || Boolean(status?.lease.locked)} onClick={() => onCommit(selected.id)} type="button">确认提交</button>
                    <button className="secondary small-button" disabled={createPrPending || selected.mode === "shared_workspace" || !selected.branchName} onClick={() => onCreatePr(selected.id)} type="button">创建 PR</button>
                    <button className="secondary small-button" disabled={pushPending || !selected.branchName || selectedDirty} onClick={() => onPush(selected.id)} type="button">push 分支</button>
                    <button
                      className="danger small-button"
                      disabled={abandonPending || selected.mode === "shared_workspace" || Boolean(status?.lease.locked)}
                      onClick={() => onAbandon(selected.id)}
                      title={selected.mode === "shared_workspace" ? "共享工作区由多个任务共同使用，不能按单个任务放弃结果" : "将当前独立工作区标记为已放弃，但保留目录"}
                      type="button"
                    >
                      放弃结果
                    </button>
                    <div className="workspace-cleanup-action">
                      {selectedDirty && (
                        <label className="workspace-danger-confirm" title="清理目录会丢弃该运行目录的未提交改动">
                          <input checked={cleanupDiscardConfirmed} onChange={(event) => onCleanupDiscardConfirmed(event.target.checked)} type="checkbox" />
                          <span>丢弃改动</span>
                        </label>
                      )}
                      <button
                        className="danger small-button workspace-cleanup-button"
                        disabled={cleanupPending || selected.mode === "shared_workspace" || !canCleanup}
                        onClick={() => onCleanup(selected.id, selectedDirty && cleanupDiscardConfirmed)}
                        title={selected.mode === "shared_workspace" ? "共享工作区是项目主目录，不能按单个任务清理" : "归档并清理当前独立执行目录"}
                        type="button"
                      >
                        清理目录
                      </button>
                    </div>
                    <button className="danger small-button" disabled={archivePending || !status?.canArchive} onClick={() => onArchive(selected.id)} type="button">归档旧流程</button>
                  </div>
                  {mergePreview && <pre className="workspace-diff-preview">{mergePreview}</pre>}
                  {diffPreview && <pre className="workspace-diff-preview">{diffPreview}</pre>}
                </div>
              )}
            </div>
          );
        })}
        </div>
      </section>
    </details>
  );
}
export function ProjectPage() {
  const { orgId = "", projectId = "", tab = "configuration" } = useParams();
  const activeTab = ["configuration", "workspace", "resources", "issues", "budget"].includes(tab) ? tab : "configuration";
  const [projectName, setProjectName] = useState("");
  const [description, setDescription] = useState("");
  const [status, setStatus] = useState<ProjectStatus>("backlog");
  const [leadAgentId, setLeadAgentId] = useState("");
  const [targetDate, setTargetDate] = useState("");
  const [goalIds, setGoalIds] = useState("");
  const [workspacePolicyMode, setWorkspacePolicyMode] = useState<WorkspacePolicyMode>("shared_workspace");
  const [workspaceName, setWorkspaceName] = useState("");
  const [workspaceCwd, setWorkspaceCwd] = useState("");
  const [workspaceRepoUrl, setWorkspaceRepoUrl] = useState("");
  const [workspaceRepoRef, setWorkspaceRepoRef] = useState("");
  const [workspaceSourceError, setWorkspaceSourceError] = useState("");
  const [workspaceCreateOpen, setWorkspaceCreateOpen] = useState(false);
  const [attachCatalogOpen, setAttachCatalogOpen] = useState(false);
  const [createResourceOpen, setCreateResourceOpen] = useState(false);
  const [newResourceName, setNewResourceName] = useState("");
  const [newResourceKind, setNewResourceKind] = useState<OrganizationResource["kind"]>("directory");
  const [newResourceLocator, setNewResourceLocator] = useState("");
  const [newResourceDescription, setNewResourceDescription] = useState("");
  const [newResourceRole, setNewResourceRole] = useState<ProjectResourceRole>("reference");
  const [newResourceNote, setNewResourceNote] = useState("");
  const [selectedExecutionWorkspaceId, setSelectedExecutionWorkspaceId] = useState("");
  const [workspaceDiffPreview, setWorkspaceDiffPreview] = useState("");
  const [workspaceMergePreview, setWorkspaceMergePreview] = useState("");
  const [cleanupDiscardConfirmed, setCleanupDiscardConfirmed] = useState(false);
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const project = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => projectsApi.get(projectId),
  });
  const resources = useQuery({
    queryKey: ["project-resources", projectId],
    queryFn: () => projectsApi.listResources(projectId),
    enabled: activeTab === "resources",
  });
  const organizationResources = useQuery({
    queryKey: ["organization-resources", orgId],
    queryFn: () => organizationsApi.resources(orgId),
    enabled: activeTab === "resources" && Boolean(orgId),
  });
  const issues = useQuery({
    queryKey: ["issues", orgId, "project", projectId],
    queryFn: () => issuesApi.list(orgId, { projectId }),
    enabled: activeTab === "issues" || activeTab === "workspace",
  });
  const agents = useQuery({
    queryKey: ["agents", orgId],
    queryFn: () => agentsApi.list(orgId),
    enabled: activeTab === "configuration" || activeTab === "issues" || activeTab === "workspace",
  });
  const executionWorkspaces = useQuery({
    queryKey: ["execution-workspaces", orgId, projectId],
    queryFn: () => projectsApi.listExecutionWorkspaces(orgId, projectId),
    enabled: (activeTab === "configuration" || activeTab === "workspace") && Boolean(orgId && projectId),
  });
  const workProducts = useQuery({
    queryKey: ["project-work-products", projectId],
    queryFn: () => projectsApi.listWorkProducts(projectId),
    enabled: activeTab === "workspace" && Boolean(projectId),
  });  const executionWorkspaceStatus = useQuery({
    queryKey: ["execution-workspace-status", selectedExecutionWorkspaceId],
    queryFn: () => projectsApi.executionWorkspaceStatus(selectedExecutionWorkspaceId),
    enabled: activeTab === "configuration" && Boolean(selectedExecutionWorkspaceId),
  });
  useEffect(() => {
    if (project.data) {
      setProjectName(project.data.name);
      setDescription(project.data.description ?? "");
      setStatus(project.data.status);
      setLeadAgentId(project.data.leadAgentId ?? "");
      setTargetDate(project.data.targetDate ?? "");
      setGoalIds((project.data.goalIds ?? (project.data.goalId ? [project.data.goalId] : [])).join(","));
    }
  }, [project.data]);
  const executionWorkspaceList = Array.isArray(executionWorkspaces.data) ? executionWorkspaces.data : [];
  const projectWorkspaces = project.data?.workspaces ?? [];
  const primaryProjectWorkspace = project.data?.primaryWorkspace
    ?? projectWorkspaces.find((workspace) => workspace.isPrimary)
    ?? projectWorkspaces[0];
  const projectWorkspaceExecutionList = primaryProjectWorkspace
    ? executionWorkspaceList.filter(
      (workspace) => workspace.projectWorkspaceId === primaryProjectWorkspace.id
        && workspace.mode === "shared_workspace",
    ).slice(0, 1)
    : [];
  useEffect(() => {
    const firstWorkspaceId = executionWorkspaceList[0]?.id ?? "";
    if (!selectedExecutionWorkspaceId && firstWorkspaceId) setSelectedExecutionWorkspaceId(firstWorkspaceId);
  }, [executionWorkspaceList, selectedExecutionWorkspaceId]);
  const update = useMutation({
    mutationFn: () => {
      const parsedGoalIds = parseGoalIds(goalIds);
      return projectsApi.update(projectId, {
        description: description.trim() || null,
        name: projectName.trim() || project.data?.name,
        status,
        leadAgentId: leadAgentId || null,
        targetDate: targetDate || null,
        goalIds: parsedGoalIds,
      });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["project", projectId] });
      void queryClient.invalidateQueries({ queryKey: ["projects", orgId] });
    },
  });
  const invalidateProjectResources = () => {
    void queryClient.invalidateQueries({ queryKey: ["project", projectId] });
    void queryClient.invalidateQueries({ queryKey: ["project-resources", projectId] });
    void queryClient.invalidateQueries({ queryKey: ["organization-resources", orgId] });
  };
  const invalidateProject = () => {
    void queryClient.invalidateQueries({ queryKey: ["project", projectId] });
    void queryClient.invalidateQueries({ queryKey: ["projects", orgId] });
  };
  const createWorkspace = useMutation({
    mutationFn: () => projectsApi.createWorkspace(projectId, {
      name: workspaceName.trim(),
      sourceType: workspaceRepoUrl.trim() ? "git_repo" : "local_path",
      cwd: workspaceCwd.trim() || null,
      repoUrl: workspaceRepoUrl.trim() || null,
      repoRef: workspaceRepoRef.trim() || null,
      defaultRef: workspaceRepoRef.trim() || null,
      executionWorkspacePolicy: parseJsonObject(workspacePolicyForMode("", workspacePolicyMode)),
    }),
    onSuccess: () => {
      setWorkspaceName("");
      setWorkspaceCwd("");
      setWorkspaceRepoUrl("");
      setWorkspaceRepoRef("");
      setWorkspacePolicyMode("shared_workspace");
      setWorkspaceSourceError("");
      setWorkspaceCreateOpen(false);
      invalidateProject();
    },
  });
  const updateWorkspacePolicy = useMutation({
    mutationFn: ({
      workspaceId,
      mode,
      currentPolicy,
    }: {
      workspaceId: string;
      mode: WorkspacePolicyMode;
      currentPolicy: Record<string, unknown> | null;
    }) =>
      projectsApi.updateWorkspace(projectId, workspaceId, {
        executionWorkspacePolicy: parseJsonObject(
          workspacePolicyForMode(formatJson(currentPolicy ?? {}), mode),
        ),
      }),
    onSuccess: invalidateProject,
  });
  const setPrimaryWorkspace = useMutation({
    mutationFn: (workspaceId: string) => projectsApi.updateWorkspace(projectId, workspaceId, { isPrimary: true }),
    onSuccess: invalidateProject,
  });
  const removeWorkspace = useMutation({
    mutationFn: (workspaceId: string) => projectsApi.removeWorkspace(projectId, workspaceId),
    onSuccess: invalidateProject,
  });
  const refreshExecutionWorkspaces = () => {
    void queryClient.invalidateQueries({ queryKey: ["execution-workspaces", orgId, projectId] });
    if (selectedExecutionWorkspaceId) {
      void queryClient.invalidateQueries({ queryKey: ["execution-workspace-status", selectedExecutionWorkspaceId] });
    }
  };
  const loadWorkspaceDiff = useMutation({
    mutationFn: (workspaceId: string) => projectsApi.executionWorkspaceDiff(workspaceId),
    onSuccess: (payload) => {
      setWorkspaceDiffPreview(payload.diff || payload.stat || payload.error || "无 diff");
    },
  });
  const previewExecutionWorkspaceMerge = useMutation({
    mutationFn: (workspaceId: string) => projectsApi.executionWorkspaceMergePreview(workspaceId),
    onSuccess: (payload) => {
      const title = payload.canMerge ? "可以 clean merge" : payload.conflict ? "存在 merge 冲突" : "不能 merge";
      const files = payload.conflictFiles.length > 0 ? `
冲突文件：${payload.conflictFiles.join(", ")}` : "";
      setWorkspaceMergePreview(`${title}
目标：${payload.targetRef ?? "未设置"}
来源：${payload.sourceBranch ?? "未识别"}${files}

${payload.preview || payload.error || "无详细输出"}`);
    },
  });
  const mergeExecutionWorkspace = useMutation({
    mutationFn: (workspaceId: string) => projectsApi.mergeExecutionWorkspace(workspaceId),
    onSuccess: (payload) => {
      setWorkspaceMergePreview(`已 merge 到 ${payload.targetRef}
merge commit: ${payload.mergedCommit ?? "未识别"}`);
      refreshExecutionWorkspaces();
    },
  });
  const prepareExecutionWorkspacePr = useMutation({
    mutationFn: (workspaceId: string) => projectsApi.prepareExecutionWorkspacePr(workspaceId),
    onSuccess: (payload) => {
      setWorkspaceMergePreview(`PR 准备信息
源分支：${payload.sourceBranch}
目标：${payload.targetRef}
命令：${payload.command}
${payload.compareUrl ?? "未识别远端 compare URL"}`);
    },
  });
  const createExecutionWorkspacePr = useMutation({
    mutationFn: (workspaceId: string) => projectsApi.createExecutionWorkspacePr(workspaceId),
    onSuccess: (payload) => {
      setWorkspaceMergePreview(`已创建 PR：${payload.url ?? (payload.stdout || "未返回 URL")}`);
      refreshExecutionWorkspaces();
    },
  });
  const commitExecutionWorkspace = useMutation({
    mutationFn: ({ workspaceId, message }: { workspaceId: string; message: string }) => projectsApi.commitExecutionWorkspace(workspaceId, message),
    onSuccess: (payload) => {
      setWorkspaceDiffPreview("");
      setWorkspaceMergePreview(`已提交：${payload.commit ?? "未识别"}\n${payload.stat || "无 diff 摘要"}`);
      refreshExecutionWorkspaces();
    },
  });
  const pushExecutionWorkspace = useMutation({
    mutationFn: ({ workspaceId, credentials }: { workspaceId: string; credentials?: PushCredentials | null }) => projectsApi.pushExecutionWorkspace(workspaceId, credentials),
    onSuccess: refreshExecutionWorkspaces,
  });
  const archiveExecutionWorkspace = useMutation({
    mutationFn: (workspaceId: string) => projectsApi.archiveExecutionWorkspace(workspaceId),
    onSuccess: () => {
      setWorkspaceDiffPreview("");
      setWorkspaceMergePreview("");
      refreshExecutionWorkspaces();
    },
  });
  const abandonExecutionWorkspace = useMutation({
    mutationFn: (workspaceId: string) => projectsApi.abandonExecutionWorkspace(workspaceId),
    onSuccess: refreshExecutionWorkspaces,
  });
  const cleanupExecutionWorkspace = useMutation({
    mutationFn: ({ workspaceId, discardDirty }: { workspaceId: string; discardDirty: boolean }) => projectsApi.cleanupExecutionWorkspace(workspaceId, discardDirty),
    onSuccess: () => {
      setWorkspaceDiffPreview("");
      setWorkspaceMergePreview("");
      setCleanupDiscardConfirmed(false);
      refreshExecutionWorkspaces();
    },
  });
  const addResource = useMutation({
    mutationFn: (payload: { resourceId: string; role?: ProjectResourceRole; note?: string | null; sortOrder?: number }) =>
      projectsApi.addResource(projectId, {
        resourceId: payload.resourceId,
        role: payload.role ?? "reference",
        note: payload.note,
        sortOrder: payload.sortOrder,
      }),
    onSuccess: () => {
      setAttachCatalogOpen(false);
      invalidateProjectResources();
    },
  });
  const removeResource = useMutation({
    mutationFn: (attachmentId: string) => projectsApi.removeResource(projectId, attachmentId),
    onSuccess: invalidateProjectResources,
  });
  const updateResource = useMutation({
    mutationFn: (payload: {
      attachmentId: string;
      role?: ProjectResourceRole;
      note?: string | null;
      sortOrder?: number;
    }) => projectsApi.updateResource(projectId, payload.attachmentId, {
      role: payload.role,
      note: payload.note,
      sortOrder: payload.sortOrder,
    }),
    onSuccess: invalidateProjectResources,
  });
  const createAndAttachResource = useMutation({
    mutationFn: async () => {
      const created = await organizationsApi.createResource(orgId, {
        name: newResourceName.trim(),
        kind: newResourceKind,
        locator: newResourceLocator.trim(),
        description: newResourceDescription.trim() || null,
      });
      return projectsApi.addResource(projectId, {
        resourceId: created.id,
        role: newResourceRole,
        note: newResourceNote.trim() || null,
        sortOrder: resources.data?.length ?? 0,
      });
    },
    onSuccess: () => {
      setNewResourceName("");
      setNewResourceKind("directory");
      setNewResourceLocator("");
      setNewResourceDescription("");
      setNewResourceRole("reference");
      setNewResourceNote("");
      setCreateResourceOpen(false);
      invalidateProjectResources();
    },
  });
  const removeProject = useMutation({
    mutationFn: () => projectsApi.remove(projectId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["projects", orgId] });
      navigate(`/orgs/${orgId}/projects`);
    },
  });
  function save(event: FormEvent) {
    event.preventDefault();
    update.mutate();
  }
  function submitWorkspace() {
    setWorkspaceSourceError("");
    if (!workspaceName.trim()) {
      setWorkspaceSourceError("请先填写代码来源名称。");
      return;
    }
    if (!workspaceCwd.trim() && !workspaceRepoUrl.trim()) {
      setWorkspaceSourceError("本地 cwd 和仓库 URL 至少填写一项。");
      return;
    }
    createWorkspace.mutate();
  }
  function submitInlineResource(event: FormEvent) {
    event.preventDefault();
    if (newResourceName.trim() && newResourceLocator.trim()) createAndAttachResource.mutate();
  }
  const projectIssues = issues.data ?? [];
  const agentList = Array.isArray(agents.data) ? agents.data : [];
  const attachedResources = [...(resources.data ?? project.data?.resources ?? [])].sort(
    (left, right) => (left.sortOrder ?? 0) - (right.sortOrder ?? 0),
  );
  const availableOrganizationResources = (organizationResources.data ?? []).filter(
    (resource) => !attachedResources.some((attachment) => attachment.resourceId === resource.id),
  );
  if (project.error) return <ErrorNotice error={project.error} />;
  return (
    <OrgWorkspace contentClassName={`org-content-full tertiary-page-content${activeTab === "workspace" ? " project-workspace-content" : ""}`} orgId={orgId}>
      <TertiaryPageShell className="project-detail-shell">
      <TertiaryPageHeader
        actions={project.data ? <>
          <Link className="button secondary" to={`/orgs/${orgId}/chats`}>聊天</Link>
          <button className="danger" disabled={removeProject.isPending} onClick={() => removeProject.mutate()} type="button">删除项目</button>
        </> : undefined}
        eyebrow="Project"
        supporting={project.data ? <div className="project-header-meta">
              <Badge>{project.data.urlKey}</Badge>
              {project.data.description && <span>{project.data.description}</span>}
        </div> : undefined}
        title={project.data?.name ?? "载入中..."}
      />
      {project.data && (
        <>
          {project.data.pauseReason === "budget" && (
            <div className="project-budget-stop">
              <span />
              因预算硬限制暂停
            </div>
          )}
          <nav aria-label="项目详情导航" className="detail-tabs">
            <Link aria-current={activeTab === "configuration" ? "page" : undefined} className={activeTab === "configuration" ? "active" : undefined} to={`/orgs/${orgId}/projects/${projectId}/configuration`}>配置</Link>
            <Link aria-current={activeTab === "workspace" ? "page" : undefined} className={activeTab === "workspace" ? "active" : undefined} to={`/orgs/${orgId}/projects/${projectId}/workspace`}>工作区</Link>
            <Link aria-current={activeTab === "resources" ? "page" : undefined} className={activeTab === "resources" ? "active" : undefined} to={`/orgs/${orgId}/projects/${projectId}/resources`}>资源</Link>
            <Link aria-current={activeTab === "issues" ? "page" : undefined} className={activeTab === "issues" ? "active" : undefined} to={`/orgs/${orgId}/projects/${projectId}/issues`}>任务</Link>
            <Link aria-current={activeTab === "budget" ? "page" : undefined} className={activeTab === "budget" ? "active" : undefined} to={`/orgs/${orgId}/projects/${projectId}/budget`}>预算</Link>
          </nav>
          <TertiaryPageViewport
            className={activeTab === "workspace" ? "tertiary-page-viewport-contained" : undefined}
          >
          {activeTab === "budget" && (
            <section className="project-budget-panel project-tab-panel" aria-label="项目预算">
              <div className={`project-budget-governance${project.data.pauseReason === "budget" ? " is-limited" : project.data.pauseReason ? " is-paused" : " is-ok"}`}>
                <span aria-hidden="true" className="project-budget-governance-indicator" />
                <div className="project-budget-governance-copy">
                  <span>预算治理状态</span>
                  <strong>{project.data.pauseReason === "budget" ? "已触发预算硬限制" : "预算限制未触发"}</strong>
                  <p>
                    {project.data.pauseReason === "budget"
                      ? "项目已因预算治理自动暂停。"
                      : project.data.pauseReason
                        ? `项目当前因${PROJECT_PAUSE_REASON_LABELS[project.data.pauseReason]}，并非预算限制。`
                        : "项目当前未因预算治理暂停。"}
                  </p>
                </div>
                {project.data.pauseReason && (
                  <dl className="project-budget-governance-meta">
                    <div>
                      <dt>暂停原因</dt>
                      <dd>{PROJECT_PAUSE_REASON_LABELS[project.data.pauseReason]}</dd>
                    </div>
                    {project.data.pausedAt && (
                      <div>
                        <dt>暂停时间</dt>
                        <dd>{formatDateTime(project.data.pausedAt)}</dd>
                      </div>
                    )}
                  </dl>
                )}
              </div>
            </section>
          )}
          {activeTab === "configuration" && <div className="project-properties-card project-tab-panel">
            <div className="project-config-sections project-config-flow">
              <form className="project-config-section project-config-step-basic" onSubmit={save}>
                <div className="project-section-heading project-section-heading-actions">
                  <div>
                    <p className="eyebrow">Basic settings</p>
                    <h2>基础设置</h2>
                  </div>
                  <button className="project-config-action" disabled={update.isPending} type="submit">
                    {update.isPending ? "保存中..." : "保存设置"}
                  </button>
                </div>
                <div className="project-property-list">
                  <label className="project-property-row">
                    <span>项目名称</span>
                    <input value={projectName} onChange={(event) => setProjectName(event.target.value)} required />
                  </label>
                  <label className="project-property-row">
                    <span>状态</span>
                    <select value={status} onChange={(event) => setStatus(event.target.value as ProjectStatus)}>
                      {STATUSES.map((item) => <option key={item} value={item}>{statusLabel(item)}</option>)}
                    </select>
                  </label>
                  <label className="project-property-row">
                    <span>负责人</span>
                    <select value={leadAgentId} onChange={(event) => setLeadAgentId(event.target.value)}>
                      <option value="">未设置</option>
                      {agentList.map((agent) => (
                        <option key={agent.id} value={agent.id}>
                          {agent.name}
                        </option>))}
                    </select>
                  </label>
                  <label className="project-property-row">
                    <span>目标日期</span>
                    <input type="date" value={targetDate} onChange={(event) => setTargetDate(event.target.value)} />
                  </label>
                  <label className="project-property-row project-property-row-start">
                    <span>描述</span>
                    <textarea value={description} onChange={(event) => setDescription(event.target.value)} />
                  </label>
                  <details className="project-system-metadata">
                    <summary>系统信息与关联目标</summary>
                    <label className="project-property-row">
                      <span>目标 ID</span>
                      <input value={goalIds} onChange={(event) => setGoalIds(event.target.value)} />
                    </label>
                    <div className="project-property-row">
                      <span>URL 标识</span>
                      <strong>{project.data.urlKey}</strong>
                    </div>
                    <div className="project-property-row">
                      <span>关联目标</span>
                      <div className="project-goal-chips">
                        {(project.data.goals ?? []).map((goal) => <Badge key={goal.id}>{goal.title}</Badge>)}
                        {(project.data.goals ?? []).length === 0 && project.data.goalId && <Badge>{project.data.goalId}</Badge>}
                        {(project.data.goals ?? []).length === 0 && !project.data.goalId && <span className="muted">暂无关联目标</span>}
                      </div>
                    </div>
                    <div className="project-property-row">
                      <span>创建时间</span>
                      <strong>{formatDateTime(project.data.createdAt)}</strong>
                    </div>
                    <div className="project-property-row">
                      <span>更新时间</span>
                      <strong>{formatDateTime(project.data.updatedAt)}</strong>
                    </div>
                  </details>
                </div>
                {update.error && <ErrorNotice error={update.error} />}
              </form>
              <section className="project-config-section project-workspace-manager project-config-step-source" aria-label="项目工作区配置">
              <div className="project-section-heading project-section-heading-actions">
                <div>
                  <p className="eyebrow">Workspace settings</p>
                  <h2>工作区设置</h2>
                </div>
                <button className="secondary small-button project-config-action" onClick={() => {
                  setWorkspaceCreateOpen((open) => !open);
                  setWorkspaceSourceError("");
                }} type="button">
                  {workspaceCreateOpen ? "取消添加" : "添加工作区"}
                </button>
              </div>
              {projectWorkspaces.length === 0 && (
                <div className="project-workspace-fallback compact">
                  <strong>尚未配置项目工作区</strong>
                  <span>无代码任务仍可使用组织草稿目录；代码任务需先添加代码来源并选择执行模式。</span>
                </div>
              )}
              {workspaceCreateOpen && <div className="project-workspace-create-grid">
                <label>
                  名称
                  <input
                    aria-label="代码来源名称"
                    value={workspaceName}
                    onChange={(event) => setWorkspaceName(event.target.value)}
                    placeholder="默认代码来源"
                  />
                </label>
                <label>
                  本地 cwd
                  <input
                    aria-label="代码来源本地 cwd"
                    value={workspaceCwd}
                    onChange={(event) => setWorkspaceCwd(event.target.value)}
                    placeholder="D:/coding/project"
                  />
                </label>
                <label>
                  仓库 URL
                  <input
                    aria-label="代码来源仓库 URL"
                    value={workspaceRepoUrl}
                    onChange={(event) => setWorkspaceRepoUrl(event.target.value)}
                    placeholder="https://github.com/acme/project.git"
                  />
                </label>
                <label>
                  分支
                  <input
                    aria-label="代码来源分支"
                    value={workspaceRepoRef}
                    onChange={(event) => setWorkspaceRepoRef(event.target.value)}
                    placeholder="main"
                  />
                </label>
                <label>
                  执行模式
                  <span className="project-workspace-mode-field">
                    <select
                      aria-label="新工作区执行模式"
                      value={workspacePolicyMode}
                      onChange={(event) => setWorkspacePolicyMode(event.target.value as WorkspacePolicyMode)}
                    >
                      {WORKSPACE_POLICY_OPTIONS.map((option) => (
                        <option key={option.mode} value={option.mode}>{option.label}</option>))}
                    </select>
                    <small>{workspacePolicyDescription(workspacePolicyMode)}</small>
                  </span>
                </label>
                <button
                  className="project-workspace-create-button project-config-action"
                  disabled={createWorkspace.isPending}
                  onClick={submitWorkspace}
                  type="button"
                >
                  {createWorkspace.isPending ? "添加中..." : "确认添加"}
                </button>
              </div>}
              {workspaceCreateOpen && workspaceSourceError && <p className="error-notice">{workspaceSourceError}</p>}
              <div className="project-workspace-list">
                {(project.data.workspaces ?? []).map((workspace) => (
                  <div className="project-workspace-item" key={workspace.id}>
                    <div className="project-workspace-main">
                      <div className="project-workspace-name-row">
                        <strong>{workspace.name}</strong>
                        <span className="project-workspace-path-inline" title={projectWorkspaceDisplay(workspace)}>
                          {projectWorkspaceDisplay(workspace)}
                        </span>
                        <div className="project-workspace-badges">
                          {workspace.isPrimary && <Badge>默认</Badge>}
                          <Badge>{workspace.sourceType}</Badge>
                          {workspace.sharedWorkspaceKey && <Badge>{workspace.sharedWorkspaceKey}</Badge>}
                        </div>
                      </div>
                      {(workspace.repoUrl || workspace.repoRef || workspace.defaultRef) && (
                        <small
                          className="project-workspace-repo-line"
                          title={[workspace.repoUrl, workspace.repoRef ?? workspace.defaultRef].filter(Boolean).join(" · ")}
                        >
                          {[workspace.repoUrl, workspace.repoRef ?? workspace.defaultRef].filter(Boolean).join(" · ")}
                        </small>
                      )}
                      <div className="project-workspace-config-row">
                        <label className="project-workspace-mode-control">
                          <span>执行模式</span>
                          <span className="project-workspace-mode-field">
                            <select
                              aria-label={`${workspace.name} 执行模式`}
                              disabled={updateWorkspacePolicy.isPending}
                              value={workspacePolicyModeFromPolicy(workspace.executionWorkspacePolicy)}
                              onChange={(event) => updateWorkspacePolicy.mutate({
                                workspaceId: workspace.id,
                                mode: event.target.value as WorkspacePolicyMode,
                                currentPolicy: workspace.executionWorkspacePolicy,
                              })}
                            >
                              {WORKSPACE_POLICY_OPTIONS.map((option) => (
                                <option key={option.mode} value={option.mode}>{option.label}</option>))}
                            </select>
                            <small>{workspacePolicyDescription(workspacePolicyModeFromPolicy(workspace.executionWorkspacePolicy))}</small>
                          </span>
                        </label>
                        <div className="project-workspace-actions">
                          <button
                            className="secondary small-button project-config-action"
                            disabled={workspace.isPrimary || setPrimaryWorkspace.isPending}
                            onClick={() => setPrimaryWorkspace.mutate(workspace.id)}
                            type="button"
                          >
                            设为默认
                          </button>
                          <button
                            className="danger small-button project-config-action"
                            disabled={
                              removeWorkspace.isPending
                              || (workspace.isPrimary && projectWorkspaces.length > 1)
                            }
                            onClick={() => removeWorkspace.mutate(workspace.id)}
                            title={
                              workspace.isPrimary && projectWorkspaces.length > 1
                                ? "请先将另一个工作区设为默认"
                                : undefined
                            }
                            type="button"
                          >
                            删除代码来源
                          </button>
                        </div>
                      </div>
                    </div>
                  </div>))}
              </div>
            </section>
              <ProjectOutputLocations codebase={project.data.codebase} />
              <ExecutionWorkspacePanel
                abandonPending={abandonExecutionWorkspace.isPending}
                archivePending={archiveExecutionWorkspace.isPending}
                cleanupDiscardConfirmed={cleanupDiscardConfirmed}
                cleanupPending={cleanupExecutionWorkspace.isPending}
                createPrPending={createExecutionWorkspacePr.isPending}
                commitPending={commitExecutionWorkspace.isPending}
                diffPending={loadWorkspaceDiff.isPending}
                diffPreview={workspaceDiffPreview}
                error={executionWorkspaces.error || executionWorkspaceStatus.error || loadWorkspaceDiff.error || previewExecutionWorkspaceMerge.error || mergeExecutionWorkspace.error || prepareExecutionWorkspacePr.error || createExecutionWorkspacePr.error || commitExecutionWorkspace.error || pushExecutionWorkspace.error || archiveExecutionWorkspace.error || abandonExecutionWorkspace.error || cleanupExecutionWorkspace.error}
                mergePending={mergeExecutionWorkspace.isPending}
                mergePreview={workspaceMergePreview}
                mergePreviewPending={previewExecutionWorkspaceMerge.isPending}
                onAbandon={(workspaceId) => abandonExecutionWorkspace.mutate(workspaceId)}
                onArchive={(workspaceId) => archiveExecutionWorkspace.mutate(workspaceId)}
                onCleanup={(workspaceId, discardDirty) => cleanupExecutionWorkspace.mutate({ workspaceId, discardDirty })}
                onCleanupDiscardConfirmed={setCleanupDiscardConfirmed}
                onCommit={(workspaceId) => {
                  const message = window.prompt("提交信息", `Update execution workspace ${workspaceId.slice(0, 8)}`);
                  if (message?.trim()) commitExecutionWorkspace.mutate({ workspaceId, message });
                }}
                onCreatePr={(workspaceId) => createExecutionWorkspacePr.mutate(workspaceId)}
                onLoadDiff={(workspaceId) => loadWorkspaceDiff.mutate(workspaceId)}
                onMerge={(workspaceId) => mergeExecutionWorkspace.mutate(workspaceId)}
                onMergePreview={(workspaceId) => previewExecutionWorkspaceMerge.mutate(workspaceId)}
                onPreparePr={(workspaceId) => prepareExecutionWorkspacePr.mutate(workspaceId)}
                onPush={(workspaceId) => {
                  const credentials = promptForPushCredentials();
                  pushExecutionWorkspace.mutate({ workspaceId, credentials });
                }}
                preparePrPending={prepareExecutionWorkspacePr.isPending}
                onSelect={(workspaceId) => {
                  setSelectedExecutionWorkspaceId(workspaceId);
                  setWorkspaceDiffPreview("");
                  setWorkspaceMergePreview("");
                  setCleanupDiscardConfirmed(false);
                }}
                pushPending={pushExecutionWorkspace.isPending}
                selectedId={selectedExecutionWorkspaceId}
                status={executionWorkspaceStatus.data}
                statusPending={executionWorkspaceStatus.isFetching}
                workspaces={executionWorkspaceList}
              />
            </div>
            {createWorkspace.error && <ErrorNotice error={createWorkspace.error} />}
            {updateWorkspacePolicy.error && <ErrorNotice error={updateWorkspacePolicy.error} />}
            {setPrimaryWorkspace.error && <ErrorNotice error={setPrimaryWorkspace.error} />}
            {removeWorkspace.error && <ErrorNotice error={removeWorkspace.error} />}
            {removeProject.error && <ErrorNotice error={removeProject.error} />}
          </div>}
          {activeTab === "workspace" && <>
            {workProducts.error && <ErrorNotice error={workProducts.error} />}
            {executionWorkspaces.error && <ErrorNotice error={executionWorkspaces.error} />}
            {issues.error && <ErrorNotice error={issues.error} />}
            <ProjectWorkspaceArtifacts
              agents={agentList}
              executionWorkspaces={projectWorkspaceExecutionList}
              issues={projectIssues}
              loading={project.isLoading || workProducts.isLoading || executionWorkspaces.isLoading || issues.isLoading}
              orgId={orgId}
              products={workProducts.data ?? []}
            />
          </>}          {activeTab === "resources" && <section className="project-resources project-tab-panel-wide">
            <div className="project-resource-toolbar project-summary-toolbar">
              <div aria-label="资源摘要" className="project-resource-summary project-compact-summary" role="group">
                <span className="project-summary-chip"><strong>{attachedResources.length}</strong> 已附加</span>
                <span className="project-summary-chip"><strong>{roleCount(attachedResources, "working_set")}</strong> 工作集</span>
                <span className="project-summary-chip"><strong>{roleCount(attachedResources, "reference")}</strong> 参考资料</span>
              </div>
              <div className="project-resource-actions">
                  <div className="project-resource-popover-anchor">
                    <button
                      className="secondary small-button"
                      disabled={availableOrganizationResources.length === 0 || addResource.isPending}
                      onClick={() => setAttachCatalogOpen((value) => !value)}
                      type="button"
                    >
                      附加已有
                    </button>
                    {attachCatalogOpen && (
                      <div className="project-resource-popover">
                        <div className="project-resource-popover-heading">
                          <strong>从组织资源目录附加</strong>
                          <span>选择已有共享资源，默认作为参考资料加入当前项目。</span>
                        </div>
                        {availableOrganizationResources.length === 0 ? (
                          <p className="muted">组织资源已经全部附加到当前项目。</p>
                        ) : (
                          <div className="project-resource-catalog-list">
                            {availableOrganizationResources.map((resource) => (
                              <button
                                key={resource.id}
                                onClick={() => addResource.mutate({
                                  resourceId: resource.id,
                                  role: "reference",
                                  sortOrder: attachedResources.length,
                                })}
                                type="button"
                              >
                                <span className={`project-resource-kind-icon org-resource-kind-${resource.kind}`} aria-hidden="true">
                                  {resourceKindMark(resource.kind)}
                                </span>
                                <span>
                                  <strong>{resource.name}</strong>
                                  <small>{resource.locator}</small>
                                  {resource.description && <em>{resource.description}</em>}
                                </span>
                                <Badge>{RESOURCE_KIND_LABELS[resource.kind]}</Badge>
                              </button>))}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                  <button className="small-button" onClick={() => setCreateResourceOpen(true)} type="button">新增资源</button>
                  <Link className="button secondary small-button" to={`/orgs/${orgId}/resources`}>组织资源目录</Link>
              </div>
            </div>
            {resources.error && <ErrorNotice error={resources.error} />}
            {updateResource.error && <ErrorNotice error={updateResource.error} />}
            {addResource.error && <ErrorNotice error={addResource.error} />}
            {createAndAttachResource.error && <ErrorNotice error={createAndAttachResource.error} />}
            {organizationResources.error && <ErrorNotice error={organizationResources.error} />}
            <div className="project-resource-list">
                {attachedResources.map((attachment) => (
                <article className="project-resource-item" key={attachment.id}>
                  <div className="project-resource-item-main">
                    <span className={`project-resource-kind-icon org-resource-kind-${attachment.resource.kind}`} aria-hidden="true">
                      {resourceKindMark(attachment.resource.kind)}
                    </span>
                    <div>
                      <div className="project-resource-title-row">
                        <strong>{attachment.resource.name}</strong>
                        <Badge>{RESOURCE_KIND_LABELS[attachment.resource.kind]}</Badge>
                        <Badge>{RESOURCE_ROLE_LABELS[attachment.role]}</Badge>
                      </div>
                      <span className="project-resource-locator">{attachment.resource.locator}</span>
                      {attachment.resource.description && <p>{attachment.resource.description}</p>}
                    </div>
                  </div>
                  <div className="project-resource-edit-row">
                    <label>
                      项目角色
                      <select
                        value={attachment.role}
                        onChange={(event) => updateResource.mutate({
                          attachmentId: attachment.id,
                          note: attachment.note,
                          role: event.target.value as ProjectResourceRole,
                          sortOrder: attachment.sortOrder,
                        })}
                      >
                        {ROLES.map((item) => <option key={item} value={item}>{RESOURCE_ROLE_LABELS[item]}</option>)}
                      </select>
                    </label>
                    <label>
                      项目备注
                      <input
                        defaultValue={attachment.note ?? ""}
                        onBlur={(event) => {
                          const note = event.currentTarget.value.trim();
                          if (note !== (attachment.note ?? "")) {
                            updateResource.mutate({
                              attachmentId: attachment.id,
                              note: note || null,
                              role: attachment.role,
                              sortOrder: attachment.sortOrder,
                            });
                          }
                        }}
                        placeholder="可选，写给智能体的项目内使用说明"
                      />
                    </label>
                  </div>
                  <div className="project-resource-card-actions">
                  <button
                    className="danger small-button"
                    onClick={() => removeResource.mutate(attachment.id)}
                    type="button"
                  >
                    移除
                  </button>
                  </div>
                </article>))}
                {resources.isSuccess && attachedResources.length === 0 && <p className="project-resource-empty muted">暂无关联资源。</p>}
            </div>
            {createResourceOpen && (
              <div className="modal-backdrop">
                <form className="panel task-modal resource-dialog" onSubmit={submitInlineResource}>
                  <div className="task-modal-header">
                    <div>
                      <h2>新增资源</h2>
                      <p className="muted">创建组织资源并同时附加到当前项目。</p>
                    </div>
                    <button className="secondary small-button" onClick={() => setCreateResourceOpen(false)} type="button">取消</button>
                  </div>
                  <div className="form">
                    <div className="task-form-row two-columns">
                      <label>
                        名称
                        <input value={newResourceName} onChange={(event) => setNewResourceName(event.target.value)} placeholder="应用代码仓库" required />
                      </label>
                      <label>
                        类型
                        <select value={newResourceKind} onChange={(event) => setNewResourceKind(event.target.value as OrganizationResource["kind"])}>
                          {RESOURCE_KINDS.map((item) => <option key={item} value={item}>{RESOURCE_KIND_LABELS[item]}</option>)}
                        </select>
                      </label>
                    </div>
                    <label>
                      定位
                      <input value={newResourceLocator} onChange={(event) => setNewResourceLocator(event.target.value)} placeholder="D:/coding/octopus 或 https://example.com/spec" required />
                    </label>
                    <label>
                      说明
                      <textarea value={newResourceDescription} onChange={(event) => setNewResourceDescription(event.target.value)} placeholder="说明这个资源包含什么，以及智能体什么时候应该使用。" />
                    </label>
                    <div className="task-form-row two-columns">
                      <label>
                        项目角色
                        <select value={newResourceRole} onChange={(event) => setNewResourceRole(event.target.value as ProjectResourceRole)}>
                          {ROLES.map((item) => <option key={item} value={item}>{RESOURCE_ROLE_LABELS[item]}</option>)}
                        </select>
                      </label>
                      <label>
                        项目备注
                        <input value={newResourceNote} onChange={(event) => setNewResourceNote(event.target.value)} placeholder="可选的项目内使用说明" />
                      </label>
                    </div>
                  </div>
                  <div className="task-modal-actions">
                    <button className="secondary" onClick={() => setCreateResourceOpen(false)} type="button">取消</button>
                    <button disabled={createAndAttachResource.isPending || !newResourceName.trim() || !newResourceLocator.trim()} type="submit">创建并附加</button>
                  </div>
                </form>
              </div>
            )}
          </section>}
          {activeTab === "issues" && <section className="project-issues project-tab-panel-wide" aria-label="项目任务">
            {issues.error && <ErrorNotice error={issues.error} />}
            {agents.error && <ErrorNotice error={agents.error} />}
            <IssueStatusBoard
              layout="list"
              agents={agentList}
              emptyMessage={issues.isSuccess ? "暂无关联任务。" : null}
              issues={projectIssues}
              orgId={orgId}
              projects={project.data ? [project.data] : []}
              showProject={false}
            />
          </section>}
          </TertiaryPageViewport>
        </>
      )}
      </TertiaryPageShell>
    </OrgWorkspace>
  );
}
