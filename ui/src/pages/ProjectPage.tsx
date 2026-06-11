import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { Link, NavLink, useNavigate, useParams } from "react-router-dom";
import { agentsApi } from "../api/agents";
import { issuesApi } from "../api/issues";
import { organizationsApi } from "../api/organizations";
import { projectsApi } from "../api/projects";
import type { OrganizationResource, ProjectCodebase, ProjectResourceRole, ProjectStatus, ProjectWorkspace } from "../api/types";
import { Badge } from "../components/Badge";
import { ErrorNotice } from "../components/ErrorNotice";
import { IssueStatusBoard } from "../components/IssueStatusBoard";
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
const WORKSPACE_POLICY_MODES = ["shared_workspace", "isolated_workspace", "operator_branch"] as const;

type WorkspacePolicyMode = (typeof WORKSPACE_POLICY_MODES)[number];

const WORKSPACE_POLICY_OPTIONS: Array<{
  description: string;
  label: string;
  mode: WorkspacePolicyMode;
}> = [
  {
    mode: "shared_workspace",
    label: "共享工作区",
    description: "多个任务复用项目主工作区，适合常规项目协作。",
  },
  {
    mode: "isolated_workspace",
    label: "独立工作区",
    description: "每个任务准备独立执行目录，适合需要隔离改动的任务。",
  },
  {
    mode: "operator_branch",
    label: "操作分支",
    description: "按任务派生分支或工作区，适合需要保留任务分支痕迹的场景。",
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
    throw new Error("执行工作区策略必须是 JSON 对象。");
  }
  return parsed as Record<string, unknown>;
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

function joinWorkspacePath(root: string | null | undefined, child: string): string {
  const base = root?.trim();
  if (!base) return "未设置";
  return `${base.replace(/[\\/]+$/, "")}/${child}`;
}

function projectHasLocalWorkspace(workspaces: ProjectWorkspace[]): boolean {
  return workspaces.some((workspace) => Boolean(workspace.cwd?.trim()));
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

function ProjectCodebasePanel({ codebase, workspaces }: { codebase?: ProjectCodebase; workspaces: ProjectWorkspace[] }) {
  const hasLocalWorkspace = projectHasLocalWorkspace(workspaces);
  const usesOrgWorkspaceFallback = !hasLocalWorkspace;
  const orgWorkspaceRoot = codebase?.managedFolder ?? codebase?.effectiveLocalFolder ?? null;
  const effectiveCwd = hasLocalWorkspace
    ? codebase?.effectiveLocalFolder ?? codebase?.localFolder
    : orgWorkspaceRoot;
  return (
    <section className="project-runtime-section" aria-label="项目运行环境">
      <div className="project-section-heading">
        <div>
          <p className="eyebrow">PROJECT RUNTIME</p>
          <h2>项目运行环境</h2>
          <p className="muted">代码库、执行目录和任务产物目录会影响智能体运行时读取和写入的位置。</p>
        </div>
      </div>
      <div className="project-runtime-grid">
        <article className="project-runtime-card">
          <div className="project-workspace-card-heading">
            <h3>代码库</h3>
            {codebase?.configured ? <Badge>已配置</Badge> : <Badge>未配置</Badge>}
          </div>
          <dl className="project-workspace-properties project-runtime-properties">
            <div><dt>来源</dt><dd title={codebase?.origin ?? "未设置"}>{codebase?.origin ?? "未设置"}</dd></div>
            <div><dt>仓库</dt><dd title={nullableText(codebase?.repoUrl)}>{nullableText(codebase?.repoUrl)}</dd></div>
            <div><dt>分支</dt><dd title={nullableText(codebase?.repoRef ?? codebase?.defaultRef)}>{nullableText(codebase?.repoRef ?? codebase?.defaultRef)}</dd></div>
            <div><dt>执行目录</dt><dd title={nullableText(effectiveCwd)}>{nullableText(effectiveCwd)}</dd></div>
            <div><dt>产物目录</dt><dd title={joinWorkspacePath(orgWorkspaceRoot, "artifacts")}>{joinWorkspacePath(orgWorkspaceRoot, "artifacts")}</dd></div>
          </dl>
          {usesOrgWorkspaceFallback && (
            <div className="project-workspace-fallback compact">
              <strong>将使用组织共享工作区</strong>
              <span>当前项目没有可用的本地项目工作区；任务运行会 fallback 到组织共享工作区。</span>
            </div>
          )}
        </article>
        <article className="project-runtime-card">
          <div className="project-workspace-card-heading">
            <h3>工作区</h3>
            <Badge>{workspaces.length}</Badge>
          </div>
          <div className="project-workspace-list compact">
            {workspaces.length === 0 && (
              <p className="project-workspace-empty">暂无项目工作区。任务运行时会使用组织共享工作区。</p>
            )}
            {workspaces.map((workspace) => {
              const workspaceCwdValue = workspace.cwd?.trim() ? workspace.cwd : "未设置本地 cwd，运行时使用组织共享工作区";
              return (
                <div className="project-workspace-item compact" key={workspace.id}>
                  <div>
                    <strong>{workspace.name}</strong>
                    <span title={workspaceCwdValue}>{workspaceCwdValue}</span>
                  </div>
                  <div className="project-workspace-badges">
                    {workspace.isPrimary && <Badge>主工作区</Badge>}
                    <Badge>{workspace.sourceType}</Badge>
                    {!workspace.cwd?.trim() && <Badge>组织工作区 fallback</Badge>}
                    {workspace.sharedWorkspaceKey && <Badge>{workspace.sharedWorkspaceKey}</Badge>}
                  </div>
                </div>
              );
            })}
          </div>
        </article>
      </div>
    </section>
  );
}
export function ProjectPage() {
  const { orgId = "", projectId = "", tab = "configuration" } = useParams();
  const activeTab = ["configuration", "resources", "issues", "budget"].includes(tab) ? tab : "configuration";
  const [projectName, setProjectName] = useState("");
  const [description, setDescription] = useState("");
  const [status, setStatus] = useState<ProjectStatus>("backlog");
  const [leadAgentId, setLeadAgentId] = useState("");
  const [targetDate, setTargetDate] = useState("");
  const [goalIds, setGoalIds] = useState("");
  const [workspacePolicy, setWorkspacePolicy] = useState("");
  const [workspacePolicyMode, setWorkspacePolicyMode] = useState<WorkspacePolicyMode>("shared_workspace");
  const [workspacePolicyError, setWorkspacePolicyError] = useState("");
  const [workspaceName, setWorkspaceName] = useState("");
  const [workspaceCwd, setWorkspaceCwd] = useState("");
  const [workspaceRepoUrl, setWorkspaceRepoUrl] = useState("");
  const [workspaceRepoRef, setWorkspaceRepoRef] = useState("");
  const [attachCatalogOpen, setAttachCatalogOpen] = useState(false);
  const [createResourceOpen, setCreateResourceOpen] = useState(false);
  const [newResourceName, setNewResourceName] = useState("");
  const [newResourceKind, setNewResourceKind] = useState<OrganizationResource["kind"]>("directory");
  const [newResourceLocator, setNewResourceLocator] = useState("");
  const [newResourceDescription, setNewResourceDescription] = useState("");
  const [newResourceRole, setNewResourceRole] = useState<ProjectResourceRole>("reference");
  const [newResourceNote, setNewResourceNote] = useState("");
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
    enabled: activeTab === "issues",
  });
  const agents = useQuery({
    queryKey: ["agents", orgId],
    queryFn: () => agentsApi.list(orgId),
    enabled: activeTab === "configuration" || activeTab === "issues",
  });
  useEffect(() => {
    if (project.data) {
      setProjectName(project.data.name);
      setDescription(project.data.description ?? "");
      setStatus(project.data.status);
      setLeadAgentId(project.data.leadAgentId ?? "");
      setTargetDate(project.data.targetDate ?? "");
      setGoalIds((project.data.goalIds ?? (project.data.goalId ? [project.data.goalId] : [])).join(","));
      const policyMode = workspacePolicyModeFromPolicy(project.data.executionWorkspacePolicy);
      setWorkspacePolicyMode(policyMode);
      setWorkspacePolicy(formatJson(project.data.executionWorkspacePolicy) || workspacePolicyForMode("", policyMode));
      setWorkspacePolicyError("");
    }
  }, [project.data]);
  const update = useMutation({
    mutationFn: () => {
      const executionWorkspacePolicy = parseJsonObject(workspacePolicy || workspacePolicyForMode("", workspacePolicyMode));
      return projectsApi.update(projectId, {
        description: description.trim() || null,
        name: projectName.trim() || project.data?.name,
        status,
        leadAgentId: leadAgentId || null,
        targetDate: targetDate || null,
        goalIds: goalIds
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
        executionWorkspacePolicy,
      });
    },
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["project", projectId] }),
    onError: (error) => {
      if (error instanceof Error) setWorkspacePolicyError(error.message);
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
      isPrimary: true,
    }),
    onSuccess: () => {
      setWorkspaceName("");
      setWorkspaceCwd("");
      setWorkspaceRepoUrl("");
      setWorkspaceRepoRef("");
      invalidateProject();
    },
  });
  const setPrimaryWorkspace = useMutation({
    mutationFn: (workspaceId: string) => projectsApi.updateWorkspace(projectId, workspaceId, { isPrimary: true }),
    onSuccess: invalidateProject,
  });
  const removeWorkspace = useMutation({
    mutationFn: (workspaceId: string) => projectsApi.removeWorkspace(projectId, workspaceId),
    onSuccess: invalidateProject,
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
    setWorkspacePolicyError("");
    update.mutate();
  }
  function selectWorkspacePolicyMode(mode: WorkspacePolicyMode) {
    setWorkspacePolicyMode(mode);
    setWorkspacePolicy(workspacePolicyForMode(workspacePolicy, mode));
    setWorkspacePolicyError("");
  }
  function editWorkspacePolicy(value: string) {
    setWorkspacePolicy(value);
    try {
      setWorkspacePolicyMode(workspacePolicyModeFromPolicy(parseJsonObject(value)));
      setWorkspacePolicyError("");
    } catch {
      setWorkspacePolicyError("执行工作区策略必须是 JSON 对象。");
    }
  }
  function submitInlineResource(event: FormEvent) {
    event.preventDefault();
    if (newResourceName.trim() && newResourceLocator.trim()) createAndAttachResource.mutate();
  }
  function submitWorkspace() {
    if (workspaceName.trim()) createWorkspace.mutate();
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
    <OrgWorkspace contentClassName="org-content-full" orgId={orgId}>
      <div className="project-detail-shell">
      <header className="page-header project-detail-header">
        <div className="project-header-identity">
          <span className="project-avatar-lg" style={{ background: project.data?.color ?? "#6366f1" }}>
            {(project.data?.name ?? "P").slice(0, 1).toUpperCase()}
          </span>
          <div className="project-detail-title">
            <Link className="back-link" to={`/orgs/${orgId}/projects`}>返回项目列表</Link>
            <div className="project-heading-row">
              <h1>{project.data?.name ?? "载入中..."}</h1>
            </div>
            {project.data && (
              <div className="project-header-meta">
                <Badge>{project.data.urlKey}</Badge>
              </div>
            )}
            {project.data?.description && <p className="muted">{project.data.description}</p>}
          </div>
        </div>
        {project.data && (
          <div className="project-header-actions">
            <Link className="button secondary" to={`/orgs/${orgId}/chats`}>聊天</Link>
            <button className="danger" disabled={removeProject.isPending} onClick={() => removeProject.mutate()} type="button">删除项目</button>
          </div>
        )}
      </header>
      {project.data && (
        <>
          {project.data.pauseReason === "budget" && (
            <div className="project-budget-stop">
              <span />
              因预算硬限制暂停
            </div>
          )}
          <nav aria-label="项目详情导航" className="detail-tabs">
            <NavLink to={`/orgs/${orgId}/projects/${projectId}/configuration`}>配置</NavLink>
            <NavLink to={`/orgs/${orgId}/projects/${projectId}/resources`}>资源</NavLink>
            <NavLink to={`/orgs/${orgId}/projects/${projectId}/issues`}>任务</NavLink>
            <NavLink to={`/orgs/${orgId}/projects/${projectId}/budget`}>预算</NavLink>
          </nav>
          {activeTab === "budget" && (
            <section className="project-properties-card project-tab-panel" aria-label="项目预算">
              <div className="project-config-sections">
                <section className="project-config-section">
                  <div className="project-section-heading">
                    <p className="eyebrow">Budget</p>
                    <h2>预算</h2>
                    <p className="muted">项目预算由组织成本治理和预算策略驱动；当前页面展示项目级治理状态。</p>
                  </div>
                  <div className="project-property-list">
                    <div className="project-property-row">
                      <span>预算状态</span>
                      <strong>{project.data.pauseReason === "budget" ? "已触发硬限制" : "未触发硬限制"}</strong>
                    </div>
                    <div className="project-property-row">
                      <span>暂停原因</span>
                      <strong>{project.data.pauseReason ?? "无"}</strong>
                    </div>
                    <div className="project-property-row">
                      <span>暂停时间</span>
                      <strong>{formatDateTime(project.data.pausedAt)}</strong>
                    </div>
                  </div>
                </section>
              </div>
            </section>
          )}
          {activeTab === "configuration" && <form className="project-properties-card project-tab-panel" onSubmit={save}>
            <div className="project-config-sections">
              <section className="project-config-section">
                <div className="project-section-heading">
                  <p className="eyebrow">BASIC INFORMATION</p>
                  <h2>基础信息</h2>
                  <p className="muted">项目名称、状态、负责人、目标日期和关联目标。</p>
                </div>
                <div className="project-property-list">
                  <label className="project-property-row">
                    <span>项目名称</span>
                    <input value={projectName} onChange={(event) => setProjectName(event.target.value)} required />
                  </label>
                  <label className="project-property-row project-property-row-start">
                    <span>描述</span>
                    <textarea value={description} onChange={(event) => setDescription(event.target.value)} />
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
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="project-property-row">
                    <span>目标日期</span>
                    <input type="date" value={targetDate} onChange={(event) => setTargetDate(event.target.value)} />
                  </label>
                  <label className="project-property-row">
                    <span>目标 ID</span>
                    <input value={goalIds} onChange={(event) => setGoalIds(event.target.value)} />
                  </label>
                  <div className="project-property-row project-property-row-readonly-start">
                    <span>URL 标识</span>
                    <strong>{project.data.urlKey}</strong>
                  </div>
                  <div className="project-property-row">
                    <span>当前负责人</span>
                    <strong>{project.data.leadAgentId ?? "未设置"}</strong>
                  </div>
                  <div className="project-property-row">
                    <span>目标</span>
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
                </div>
              </section>
              <section className="project-config-section">
                <div className="project-section-heading">
                  <p className="eyebrow">WORKSPACE POLICY</p>
                  <h2>执行工作区策略</h2>
                  <p className="muted">选择任务执行时使用共享工作区、独立工作区或操作分支。</p>
                </div>
                <div className="workspace-policy-config">
                  <fieldset className="workspace-policy-options">
                    <legend>选择任务执行时使用的工作区方式</legend>
                    {WORKSPACE_POLICY_OPTIONS.map((option) => (
                      <label
                        className={`workspace-policy-option ${workspacePolicyMode === option.mode ? "selected" : ""}`}
                        key={option.mode}
                      >
                        <input
                          checked={workspacePolicyMode === option.mode}
                          name="workspace-policy-mode"
                          onChange={() => selectWorkspacePolicyMode(option.mode)}
                          type="radio"
                          value={option.mode}
                        />
                        <span>
                          <strong>{option.label}</strong>
                          <small>{option.description}</small>
                        </span>
                      </label>
                    ))}
                  </fieldset>
                  <details className="workspace-policy-advanced">
                    <summary>高级配置 JSON</summary>
                    <label>
                      execution_workspace_policy
                      <textarea
                        aria-label="execution_workspace_policy JSON"
                        className="config-editor"
                        value={workspacePolicy}
                        onChange={(event) => editWorkspacePolicy(event.target.value)}
                        placeholder='{"enabled":true,"defaultMode":"shared_workspace"}'
                      />
                    </label>
                  </details>
                </div>
              </section>
              <ProjectCodebasePanel codebase={project.data.codebase} workspaces={project.data.workspaces ?? []} />
              <section className="project-config-section project-workspace-manager" aria-label="项目工作区管理">
              <div className="project-section-heading">
                <div>
                  <p className="eyebrow">PROJECT WORKSPACES</p>
                  <h2>项目工作区</h2>
                  <p className="muted">项目专属 cwd 会优先用于任务执行；未配置或不可用时 fallback 到组织共享工作区。</p>
                </div>
              </div>
              <div className="project-workspace-create-grid">
                <label>
                  名称
                  <input
                    aria-label="项目工作区名称"
                    value={workspaceName}
                    onChange={(event) => setWorkspaceName(event.target.value)}
                    placeholder="主工作区"
                  />
                </label>
                <label>
                  本地 cwd
                  <input
                    aria-label="项目工作区本地 cwd"
                    value={workspaceCwd}
                    onChange={(event) => setWorkspaceCwd(event.target.value)}
                    placeholder="D:/coding/project"
                  />
                </label>
                <label>
                  仓库 URL
                  <input
                    aria-label="项目工作区仓库 URL"
                    value={workspaceRepoUrl}
                    onChange={(event) => setWorkspaceRepoUrl(event.target.value)}
                    placeholder="https://github.com/acme/project.git"
                  />
                </label>
                <label>
                  分支
                  <input
                    aria-label="项目工作区分支"
                    value={workspaceRepoRef}
                    onChange={(event) => setWorkspaceRepoRef(event.target.value)}
                    placeholder="main"
                  />
                </label>
                <button
                  className="project-workspace-create-button"
                  disabled={!workspaceName.trim() || createWorkspace.isPending}
                  onClick={submitWorkspace}
                  type="button"
                >
                  新增主工作区
                </button>
              </div>
              <div className="project-workspace-list">
                {(project.data.workspaces ?? []).map((workspace) => (
                  <div className="project-workspace-item" key={workspace.id}>
                    <div className="project-workspace-main">
                      <div className="project-workspace-name-row">
                        <strong>{workspace.name}</strong>
                        <div className="project-workspace-badges">
                          {workspace.isPrimary && <Badge>主工作区</Badge>}
                          <Badge>{workspace.sourceType}</Badge>
                          {workspace.sharedWorkspaceKey && <Badge>{workspace.sharedWorkspaceKey}</Badge>}
                        </div>
                      </div>
                      <span title={workspace.cwd?.trim() ? workspace.cwd : "未设置本地 cwd，运行时使用组织共享工作区"}>
                        {workspace.cwd?.trim() ? workspace.cwd : "未设置本地 cwd，运行时使用组织共享工作区"}
                      </span>
                      {(workspace.repoUrl || workspace.repoRef || workspace.defaultRef) && (
                        <small
                          className="project-workspace-repo-line"
                          title={[workspace.repoUrl, workspace.repoRef ?? workspace.defaultRef].filter(Boolean).join(" · ")}
                        >
                          {[workspace.repoUrl, workspace.repoRef ?? workspace.defaultRef].filter(Boolean).join(" · ")}
                        </small>
                      )}
                    </div>
                    <div className="project-workspace-actions">
                      <button
                        className="secondary small-button"
                        disabled={workspace.isPrimary || setPrimaryWorkspace.isPending}
                        onClick={() => setPrimaryWorkspace.mutate(workspace.id)}
                        type="button"
                      >
                        设为主工作区
                      </button>
                      <button
                        className="danger small-button"
                        disabled={removeWorkspace.isPending}
                        onClick={() => removeWorkspace.mutate(workspace.id)}
                        type="button"
                      >
                        删除工作区
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </section>
            </div>
            {workspacePolicyError && <p className="error-notice">{workspacePolicyError}</p>}
            {update.error && <ErrorNotice error={update.error} />}
            {createWorkspace.error && <ErrorNotice error={createWorkspace.error} />}
            {setPrimaryWorkspace.error && <ErrorNotice error={setPrimaryWorkspace.error} />}
            {removeWorkspace.error && <ErrorNotice error={removeWorkspace.error} />}
            {removeProject.error && <ErrorNotice error={removeProject.error} />}
            <div className="project-property-actions">
              <button type="submit">保存项目</button>
            </div>
          </form>}
          {activeTab === "resources" && <section className="project-resources project-tab-panel-wide">
            <div className="project-resource-hero-card">
              <div className="project-resource-hero-top">
                <div>
                  <p className="eyebrow">PROJECT RESOURCES</p>
                  <h2>资源</h2>
                  <p className="muted">选择智能体在当前项目中实际使用的仓库、文档、URL 和连接器对象。组织资源目录保持统一维护，这里只决定项目范围内需要加载的资源。</p>
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
                              </button>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                  <button className="small-button" onClick={() => setCreateResourceOpen(true)} type="button">新增资源</button>
                  <Link className="button secondary small-button" to={`/orgs/${orgId}/resources`}>组织资源目录</Link>
                </div>
              </div>
              <div className="project-resource-summary">
                <div className="summary-metric">
                  <span>已附加</span>
                  <strong>{attachedResources.length}</strong>
                  <small>当前项目可见资源</small>
                </div>
                <div className="summary-metric">
                  <span>工作集</span>
                  <strong>{roleCount(attachedResources, "working_set")}</strong>
                  <small>智能体需要主动操作的资源</small>
                </div>
                <div className="summary-metric">
                  <span>参考资料</span>
                  <strong>{roleCount(attachedResources, "reference")}</strong>
                  <small>辅助理解背景与决策</small>
                </div>
              </div>
            </div>
            {resources.error && <ErrorNotice error={resources.error} />}
            {updateResource.error && <ErrorNotice error={updateResource.error} />}
            {addResource.error && <ErrorNotice error={addResource.error} />}
            {createAndAttachResource.error && <ErrorNotice error={createAndAttachResource.error} />}
            {organizationResources.error && <ErrorNotice error={organizationResources.error} />}
            <div className="project-resource-attached-card">
              <div className="project-resource-attached-heading">
                <div>
                  <p className="eyebrow">ATTACHED RESOURCES</p>
                  <h3>已附加资源</h3>
                  <p className="muted">角色和备注只作用于当前项目，不会修改组织资源目录。</p>
                </div>
              </div>
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
                </article>
                ))}
                {resources.isSuccess && attachedResources.length === 0 && <p className="project-resource-empty muted">暂无关联资源。</p>}
              </div>
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
          {activeTab === "issues" && <section className="panel project-issues project-tab-panel-wide">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">PROJECT ISSUES</p>
                <h2>任务</h2>
                <p className="muted">按状态展示当前项目关联的任务。</p>
              </div>
            </div>
            {issues.error && <ErrorNotice error={issues.error} />}
            {agents.error && <ErrorNotice error={agents.error} />}
            <div className="project-issues-body">
              {issues.isSuccess && projectIssues.length === 0 && <p className="muted">暂无关联任务。</p>}
              <IssueStatusBoard
                agents={agentList}
                issues={projectIssues}
                orgId={orgId}
                projects={project.data ? [project.data] : []}
                showProject={false}
              />
            </div>
          </section>}
        </>
      )}
      </div>
    </OrgWorkspace>
  );
}
