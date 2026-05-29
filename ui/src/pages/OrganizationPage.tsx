import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type FormEvent, type PropsWithChildren } from "react";
import { Link, Navigate, NavLink, useParams, useSearchParams } from "react-router-dom";
import { agentsApi } from "../api/agents";
import { organizationSkillsApi } from "../api/organizationSkills";
import { organizationsApi } from "../api/organizations";
import { projectsApi } from "../api/projects";
import type { Agent, OrganizationResource, OrganizationSkillListItem, ProjectDetail, ProjectWorkspace } from "../api/types";
import { Badge } from "../components/Badge";
import { ErrorNotice } from "../components/ErrorNotice";

export function OrganizationPage() {
  const { orgId = "" } = useParams();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [budgetMonthlyCents, setBudgetMonthlyCents] = useState("");
  const [brandColor, setBrandColor] = useState("");
  const [requireBoardApprovalForNewAgents, setRequireBoardApprovalForNewAgents] = useState(false);
  const [defaultChatIssueCreationMode, setDefaultChatIssueCreationMode] = useState("disabled");
  const queryClient = useQueryClient();
  const organization = useQuery({
    queryKey: ["organization", orgId],
    queryFn: () => organizationsApi.get(orgId),
  });
  useEffect(() => {
    if (organization.data) {
      setName(organization.data.name);
      setDescription(organization.data.description ?? "");
      setBudgetMonthlyCents(String(organization.data.budgetMonthlyCents ?? ""));
      setBrandColor(organization.data.brandColor ?? "");
      setRequireBoardApprovalForNewAgents(Boolean(organization.data.requireBoardApprovalForNewAgents));
      setDefaultChatIssueCreationMode(organization.data.defaultChatIssueCreationMode ?? "disabled");
    }
  }, [organization.data]);
  const update = useMutation({
    mutationFn: () =>
      organizationsApi.update(orgId, {
        name: name.trim(),
        description: description.trim() || null,
        budgetMonthlyCents: budgetMonthlyCents.trim() ? Number(budgetMonthlyCents) : undefined,
        brandColor: brandColor.trim() || null,
        requireBoardApprovalForNewAgents,
        defaultChatIssueCreationMode,
      }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["organization", orgId] }),
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    update.mutate();
  }
  if (organization.error) return <ErrorNotice error={organization.error} />;
  return (
    <div className="org-content organization-settings">
      <header className="page-header">
        <div>
          <p className="eyebrow">Organization Settings</p>
          <h1>组织设置</h1>
        </div>
      </header>
      <form className="panel form narrow" onSubmit={submit}>
        <label>
          组织名称
          <input value={name} onChange={(event) => setName(event.target.value)} required />
        </label>
        <label>
          描述
          <textarea value={description} onChange={(event) => setDescription(event.target.value)} />
        </label>
        <label>
          月度预算（cents）
          <input
            min="0"
            type="number"
            value={budgetMonthlyCents}
            onChange={(event) => setBudgetMonthlyCents(event.target.value)}
          />
        </label>
        <label>
          品牌色
          <input value={brandColor} onChange={(event) => setBrandColor(event.target.value)} />
        </label>
        <label className="checkbox-row">
          <input
            checked={requireBoardApprovalForNewAgents}
            onChange={(event) => setRequireBoardApprovalForNewAgents(event.target.checked)}
            type="checkbox"
          />
          新建智能体需要审批
        </label>
        <label>
          默认聊天任务创建模式
          <select
            value={defaultChatIssueCreationMode}
            onChange={(event) => setDefaultChatIssueCreationMode(event.target.value)}
          >
            <option value="disabled">disabled</option>
            <option value="manual">manual</option>
            <option value="automatic">automatic</option>
          </select>
        </label>
        {update.error && <ErrorNotice error={update.error} />}
        <button type="submit">保存组织</button>
      </form>
    </div>
  );
}

export function OrganizationIndexPage() {
  const { orgId = "" } = useParams();
  return <Navigate replace to={`/orgs/${orgId}/structure`} />;
}

const ORG_CARD_WIDTH = 210;
const ORG_CARD_HEIGHT = 108;
const ORG_GAP_X = 34;
const ORG_GAP_Y = 82;
const ORG_PADDING = 56;

interface OrganizationNode {
  agent: Agent;
  children: OrganizationNode[];
}

interface LayoutNode {
  agent: Agent;
  x: number;
  y: number;
  children: LayoutNode[];
}

function buildOrganizationTree(agents: Agent[]): OrganizationNode[] {
  const nodes = new Map(agents.map((agent) => [agent.id, { agent, children: [] as OrganizationNode[] }]));
  const roots: OrganizationNode[] = [];
  for (const node of nodes.values()) {
    const parentId = node.agent.reportsTo;
    const parent = parentId ? nodes.get(parentId) : undefined;
    if (parent && parent.agent.id !== node.agent.id) {
      parent.children.push(node);
    } else {
      roots.push(node);
    }
  }
  const sortNodes = (items: OrganizationNode[]) => {
    items.sort((left, right) => left.agent.name.localeCompare(right.agent.name));
    items.forEach((item) => sortNodes(item.children));
  };
  sortNodes(roots);
  return roots;
}

function subtreeWidth(node: OrganizationNode): number {
  if (node.children.length === 0) return ORG_CARD_WIDTH;
  const childWidth = node.children.reduce((sum, child) => sum + subtreeWidth(child), 0);
  return Math.max(ORG_CARD_WIDTH, childWidth + (node.children.length - 1) * ORG_GAP_X);
}

function layoutNode(node: OrganizationNode, x: number, y: number): LayoutNode {
  const width = subtreeWidth(node);
  let childX = x + (width - node.children.reduce((sum, child) => sum + subtreeWidth(child), 0) - Math.max(0, node.children.length - 1) * ORG_GAP_X) / 2;
  const children = node.children.map((child) => {
    const childWidth = subtreeWidth(child);
    const result = layoutNode(child, childX, y + ORG_CARD_HEIGHT + ORG_GAP_Y);
    childX += childWidth + ORG_GAP_X;
    return result;
  });
  return {
    agent: node.agent,
    children,
    x: x + (width - ORG_CARD_WIDTH) / 2,
    y,
  };
}

function layoutForest(nodes: OrganizationNode[]): LayoutNode[] {
  let x = ORG_PADDING;
  return nodes.map((node) => {
    const width = subtreeWidth(node);
    const result = layoutNode(node, x, ORG_PADDING);
    x += width + ORG_GAP_X;
    return result;
  });
}

function flattenLayout(nodes: LayoutNode[]): LayoutNode[] {
  const result: LayoutNode[] = [];
  const walk = (node: LayoutNode) => {
    result.push(node);
    node.children.forEach(walk);
  };
  nodes.forEach(walk);
  return result;
}

function collectEdges(nodes: LayoutNode[]): Array<{ parent: LayoutNode; child: LayoutNode }> {
  const edges: Array<{ parent: LayoutNode; child: LayoutNode }> = [];
  const walk = (node: LayoutNode) => {
    for (const child of node.children) {
      edges.push({ parent: node, child });
      walk(child);
    }
  };
  nodes.forEach(walk);
  return edges;
}

export function OrganizationStructurePage() {
  const { orgId = "" } = useParams();
  const viewportRef = useRef<HTMLDivElement>(null);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const agents = useQuery({
    queryKey: ["agents", orgId],
    queryFn: () => agentsApi.list(orgId),
  });
  const agentList = Array.isArray(agents.data) ? agents.data : [];
  const agentNameById = new Map(agentList.map((agent) => [agent.id, agent.name]));
  const organizationTree = useMemo(() => buildOrganizationTree(agentList), [agentList]);
  const layout = useMemo(() => layoutForest(organizationTree), [organizationTree]);
  const nodes = useMemo(() => flattenLayout(layout), [layout]);
  const edges = useMemo(() => collectEdges(layout), [layout]);
  const bounds = useMemo(() => {
    if (nodes.length === 0) return { width: 800, height: 460 };
    return {
      width: Math.max(...nodes.map((node) => node.x + ORG_CARD_WIDTH)) + ORG_PADDING,
      height: Math.max(...nodes.map((node) => node.y + ORG_CARD_HEIGHT)) + ORG_PADDING,
    };
  }, [nodes]);

  useEffect(() => {
    if (!viewportRef.current || nodes.length === 0) return;
    const width = viewportRef.current.clientWidth || 800;
    const fitZoom = Math.min(Math.max((width - 40) / bounds.width, 0.45), 1);
    setZoom(fitZoom);
    setPan({ x: Math.max(20, (width - bounds.width * fitZoom) / 2), y: 20 });
  }, [bounds, nodes.length]);

  function fitChart() {
    if (!viewportRef.current) return;
    const width = viewportRef.current.clientWidth || 800;
    const fitZoom = Math.min(Math.max((width - 40) / bounds.width, 0.45), 1);
    setZoom(fitZoom);
    setPan({ x: Math.max(20, (width - bounds.width * fitZoom) / 2), y: 20 });
  }

  return (
    <OrgWorkspace orgId={orgId}>
      <header className="page-header">
        <div>
          <p className="eyebrow">Organization</p>
          <h1>组织架构</h1>
          <p className="muted">按上游组织图布局展示智能体汇报关系。</p>
        </div>
        {agentList.length > 0 && (
          <div className="org-chart-controls">
            <button type="button" onClick={() => setZoom((value) => Math.min(value * 1.2, 1.8))}>+</button>
            <button type="button" onClick={() => setZoom((value) => Math.max(value * 0.8, 0.35))}>-</button>
            <button type="button" onClick={fitChart}>Fit</button>
          </div>
        )}
      </header>
      {agents.error && <ErrorNotice error={agents.error} />}
      {agents.isSuccess && agentList.length === 0 ? (
        <section className="panel organization-empty-state">
          <p className="muted">暂无智能体。创建首个智能体以建立组织架构。</p>
          <Link className="button" to={`/orgs/${orgId}/agents/new`}>新建智能体</Link>
        </section>
      ) : (
        <section className="organization-chart" ref={viewportRef}>
          <svg aria-hidden className="organization-chart-edges">
            <g transform={`translate(${pan.x}, ${pan.y}) scale(${zoom})`}>
              {edges.map(({ parent, child }) => {
                const x1 = parent.x + ORG_CARD_WIDTH / 2;
                const y1 = parent.y + ORG_CARD_HEIGHT;
                const x2 = child.x + ORG_CARD_WIDTH / 2;
                const y2 = child.y;
                const midY = (y1 + y2) / 2;
                return (
                  <path
                    d={`M ${x1} ${y1} L ${x1} ${midY} L ${x2} ${midY} L ${x2} ${y2}`}
                    fill="none"
                    key={`${parent.agent.id}-${child.agent.id}`}
                  />
                );
              })}
            </g>
          </svg>
          <div
            className="organization-chart-layer"
            style={{
              height: bounds.height,
              transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
              width: bounds.width,
            }}
          >
            {nodes.map(({ agent, x, y }) => (
              <Link
                aria-label={`${agent.name} ${agent.reportsTo ? `向 ${agentNameById.get(agent.reportsTo) ?? "未知智能体"} 汇报` : "直属组织"}`}
                className="organization-chart-card"
                key={agent.id}
                style={{ left: x, top: y }}
                to={`/orgs/${orgId}/agents/${agent.id}`}
              >
                <div className="organization-chart-avatar">{agent.name.slice(0, 1).toUpperCase()}</div>
                <div className="organization-chart-copy">
                  <strong>{agent.name}</strong>
                  <span>{agent.title ?? agent.role}</span>
                  <small>{agent.agentRuntimeType ?? "runtime"}</small>
                  <small>{agent.reportsTo ? `向 ${agentNameById.get(agent.reportsTo) ?? "未知智能体"} 汇报` : "直属组织"}</small>
                </div>
                <Badge>{agent.status}</Badge>
              </Link>
            ))}
          </div>
        </section>
      )}
    </OrgWorkspace>
  );
}

const RESOURCE_KINDS: OrganizationResource["kind"][] = ["file", "directory", "url", "connector_object"];

function organizationResourceKindLabel(kind: OrganizationResource["kind"]): string {
  if (kind === "directory") return "目录";
  if (kind === "file") return "文件";
  if (kind === "connector_object") return "连接器对象";
  return "链接";
}

function organizationResourceKindIcon(kind: OrganizationResource["kind"]): string {
  if (kind === "directory") return "D";
  if (kind === "file") return "F";
  if (kind === "connector_object") return "C";
  return "U";
}

export function OrganizationResourcesPage() {
  const { orgId = "" } = useParams();
  const queryClient = useQueryClient();
  const resources = useQuery({
    queryKey: ["organization-resources", orgId],
    queryFn: () => organizationsApi.resources(orgId),
  });
  const [editing, setEditing] = useState<OrganizationResource | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [name, setName] = useState("");
  const [kind, setKind] = useState<OrganizationResource["kind"]>("url");
  const [locator, setLocator] = useState("");
  const [description, setDescription] = useState("");
  const [formError, setFormError] = useState("");
  const resourceRows = Array.isArray(resources.data) ? resources.data : [];

  function resetForm() {
    setEditing(null);
    setName("");
    setKind("url");
    setLocator("");
    setDescription("");
    setFormError("");
  }

  function openCreateResourceDialog() {
    resetForm();
    setDialogOpen(true);
  }

  function editResource(resource: OrganizationResource) {
    setEditing(resource);
    setName(resource.name);
    setKind(resource.kind);
    setLocator(resource.locator);
    setDescription(resource.description ?? "");
    setFormError("");
    setDialogOpen(true);
  }

  function closeResourceDialog() {
    setDialogOpen(false);
    resetForm();
  }

  const saveResource = useMutation({
    mutationFn: () => {
      const payload = {
        name: name.trim(),
        kind,
        locator: locator.trim(),
        description: description.trim() || null,
      };
      return editing
        ? organizationsApi.updateResource(orgId, editing.id, payload)
        : organizationsApi.createResource(orgId, payload);
    },
    onSuccess: () => {
      closeResourceDialog();
      void queryClient.invalidateQueries({ queryKey: ["organization-resources", orgId] });
    },
    onError: (error) => setFormError(error instanceof Error ? error.message : "保存资源失败"),
  });
  const deleteResource = useMutation({
    mutationFn: (resourceId: string) => organizationsApi.deleteResource(orgId, resourceId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["organization-resources", orgId] }),
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    setFormError("");
    if (name.trim() && locator.trim()) saveResource.mutate();
  }

  return (
    <OrgWorkspace orgId={orgId}>
      <section className="org-resource-hero">
        <div className="org-resource-hero-copy">
          <p className="org-resource-eyebrow">
            <span aria-hidden="true">R</span>
            组织资源目录
          </p>
          <h1>资源</h1>
          <p>
            维护组织内可复用的代码库、文件、链接和连接器对象。资源在这里统一登记，再由项目按角色说明进行引用。
          </p>
          <div className="org-resource-chip-row">
            <span>{resourceRows.length} 个目录项</span>
            <span>项目引用时补充角色和说明</span>
          </div>
          <div className="org-resource-actions">
            <button type="button" onClick={openCreateResourceDialog}>添加资源</button>
            <Link className="button secondary" to={`/orgs/${orgId}/workspaces`}>浏览工作区</Link>
          </div>
        </div>
        <aside className="org-resource-context-card">
          <p className="eyebrow">智能体运行上下文</p>
          <h2>先建目录，再按项目引用。</h2>
          <p>
            组织资源保持可复用。项目级引用只负责指向这些资源，并说明该项目希望智能体如何使用。
          </p>
        </aside>
      </section>
      {resources.error && <ErrorNotice error={resources.error} />}
      <section className="panel org-resource-catalog-card">
        <div className="panel-heading">
          <div>
            <h2>目录</h2>
            <p className="muted">使用稳定名称和明确定位符，便于智能体可靠引用资源。</p>
          </div>
          <Badge>{resourceRows.length}</Badge>
        </div>
        {resources.isSuccess && resourceRows.length === 0 ? (
          <div className="org-resource-empty" aria-label="No resources" />
        ) : (
          <div className="org-resource-grid">
            {resourceRows.map((resource) => (
              <article className="org-resource-card" key={resource.id}>
                <div className="org-resource-card-header">
                  <span className={`org-resource-kind-icon org-resource-kind-${resource.kind}`} aria-hidden="true">
                    {organizationResourceKindIcon(resource.kind)}
                  </span>
                  <div>
                    <h3>{resource.name}</h3>
                    <span>{organizationResourceKindLabel(resource.kind)}</span>
                  </div>
                </div>
                <p className="org-resource-locator">{resource.locator}</p>
                {resource.description && <p className="org-resource-description">{resource.description}</p>}
                <div className="org-resource-card-actions">
                  <button className="secondary small-button" onClick={() => editResource(resource)} type="button">
                    编辑
                  </button>
                  <button
                    className="danger small-button"
                    disabled={deleteResource.isPending}
                    onClick={() => deleteResource.mutate(resource.id)}
                    type="button"
                  >
                    删除
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
      {deleteResource.error && <ErrorNotice error={deleteResource.error} />}
      {dialogOpen && (
        <div className="modal-backdrop" role="presentation">
          <form className="panel form task-modal resource-dialog" onSubmit={submit}>
            <div className="task-modal-header">
              <div>
                <h2>{editing ? "编辑资源" : "添加资源"}</h2>
                <p className="muted">
                  {editing ? "更新这个组织级可复用资源。" : "为当前组织创建一个可复用资源目录项。"}
                </p>
              </div>
              <button className="secondary small-button" onClick={closeResourceDialog} type="button">取消</button>
            </div>
            <label>
              名称
              <input value={name} onChange={(event) => setName(event.target.value)} required />
            </label>
            <label>
              类型
              <select value={kind} onChange={(event) => setKind(event.target.value as OrganizationResource["kind"])}>
                {RESOURCE_KINDS.map((item) => (
                  <option key={item} value={item}>{organizationResourceKindLabel(item)}</option>
                ))}
              </select>
            </label>
            <label>
              定位符
              <input value={locator} onChange={(event) => setLocator(event.target.value)} required />
            </label>
            <label>
              描述
              <textarea value={description} onChange={(event) => setDescription(event.target.value)} />
            </label>
            {formError && <p className="error-notice">{formError}</p>}
            {saveResource.error && <ErrorNotice error={saveResource.error} />}
            <div className="task-modal-actions">
              <button className="secondary" onClick={closeResourceDialog} type="button">取消</button>
              <button disabled={saveResource.isPending} type="submit">{editing ? "保存修改" : "创建资源"}</button>
            </div>
          </form>
        </div>
      )}
    </OrgWorkspace>
  );
}

function skillFilePath(skill: OrganizationSkillListItem): string {
  return skill.fileInventory.find((file) => file.path === "SKILL.md")?.path ?? skill.fileInventory[0]?.path ?? "SKILL.md";
}

export function OrganizationSkillsPage() {
  const { orgId = "" } = useParams();
  const queryClient = useQueryClient();
  const skills = useQuery({
    queryKey: ["organization-skills", orgId],
    queryFn: () => organizationSkillsApi.list(orgId),
  });
  const skillRows = Array.isArray(skills.data) ? skills.data : [];
  const [selectedSkillId, setSelectedSkillId] = useState("");
  const selectedSkill = skillRows.find((skill) => skill.id === selectedSkillId) ?? skillRows[0];
  const [newName, setNewName] = useState("");
  const [newSlug, setNewSlug] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [newMarkdown, setNewMarkdown] = useState("");
  const [draftContent, setDraftContent] = useState("");
  const selectedPath = selectedSkill ? skillFilePath(selectedSkill) : "SKILL.md";
  const skillDetail = useQuery({
    queryKey: ["organization-skill", orgId, selectedSkill?.id],
    queryFn: () => organizationSkillsApi.get(orgId, selectedSkill!.id),
    enabled: Boolean(selectedSkill),
  });
  const skillFile = useQuery({
    queryKey: ["organization-skill-file", orgId, selectedSkill?.id, selectedPath],
    queryFn: () => organizationSkillsApi.readFile(orgId, selectedSkill!.id, selectedPath),
    enabled: Boolean(selectedSkill),
  });
  const updateStatus = useQuery({
    queryKey: ["organization-skill-update-status", orgId, selectedSkill?.id],
    queryFn: () => organizationSkillsApi.updateStatus(orgId, selectedSkill!.id),
    enabled: Boolean(selectedSkill),
  });

  useEffect(() => {
    if (skillFile.data) setDraftContent(skillFile.data.content);
  }, [skillFile.data]);

  const createSkill = useMutation({
    mutationFn: () => organizationSkillsApi.create(orgId, {
      name: newName.trim(),
      slug: newSlug.trim() || null,
      description: newDescription.trim() || null,
      markdown: newMarkdown.trim() || null,
    }),
    onSuccess: (skill) => {
      setNewName("");
      setNewSlug("");
      setNewDescription("");
      setNewMarkdown("");
      setSelectedSkillId(skill.id);
      void queryClient.invalidateQueries({ queryKey: ["organization-skills", orgId] });
    },
  });
  const saveFile = useMutation({
    mutationFn: () => organizationSkillsApi.updateFile(orgId, selectedSkill!.id, { path: selectedPath, content: draftContent }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["organization-skill-file", orgId, selectedSkill?.id, selectedPath] });
      void queryClient.invalidateQueries({ queryKey: ["organization-skills", orgId] });
    },
  });
  const deleteSkill = useMutation({
    mutationFn: (skillId: string) => organizationSkillsApi.delete(orgId, skillId),
    onSuccess: () => {
      setSelectedSkillId("");
      void queryClient.invalidateQueries({ queryKey: ["organization-skills", orgId] });
    },
  });

  return (
    <OrgWorkspace orgId={orgId}>
      <header className="page-header">
        <div>
          <p className="eyebrow">Organization</p>
          <h1>技能</h1>
        </div>
      </header>
      {skills.error && <ErrorNotice error={skills.error} />}
      <div className="organization-skills-layout">
        <aside className="panel organization-skill-list">
          <div className="panel-heading">
            <div>
              <h2>Skill 管理</h2>
              <p className="muted">组织技能库</p>
            </div>
            <Badge>{skillRows.length}</Badge>
          </div>
          <div className="agent-skill-tag-list">
            {skillRows.map((skill) => (
              <button
                className={`agent-skill-tag-main organization-skill-list-entry ${selectedSkill?.id === skill.id ? "selected" : ""}`}
                key={skill.id}
                onClick={() => setSelectedSkillId(skill.id)}
                type="button"
              >
                <span className="agent-skill-tag-title-row">
                  <code>{skill.name}</code>
                  <span className="agent-skill-enabled-pill enabled">{skill.sourceBadge}</span>
                </span>
                <span className="agent-skill-tag-description">{skill.description || "未填写描述"}</span>
                <span className="agent-skill-tag-facts">
                  <span><small>引用</small>{skill.attachedAgentCount}</span>
                  <span><small>状态</small>{skill.compatibility}</span>
                </span>
              </button>
            ))}
          </div>
        </aside>
        <section className="panel organization-skill-detail">
          {selectedSkill ? (
            <>
              <div className="panel-heading">
                <div>
                  <h2>{selectedSkill.name}</h2>
                  <p className="muted">{selectedSkill.sourceLabel ?? selectedSkill.slug}</p>
                </div>
                <div className="row-actions">
                  <Badge>{updateStatus.data?.hasUpdate ? "有更新" : "无更新"}</Badge>
                  <button className="danger small-button" disabled={deleteSkill.isPending} onClick={() => deleteSkill.mutate(selectedSkill.id)} type="button">删除</button>
                </div>
              </div>
              {skillDetail.error && <ErrorNotice error={skillDetail.error} />}
              {skillFile.error && <ErrorNotice error={skillFile.error} />}
              {updateStatus.error && <ErrorNotice error={updateStatus.error} />}
              <div className="agent-summary-grid">
                <div className="summary-metric"><span>Trust</span><strong>{selectedSkill.trustLevel}</strong></div>
                <div className="summary-metric"><span>Source</span><strong>{selectedSkill.sourceType}</strong></div>
                <div className="summary-metric"><span>Agents</span><strong>{skillDetail.data?.usedByAgents.length ?? selectedSkill.attachedAgentCount}</strong></div>
              </div>
              <label>
                {selectedPath}
                <textarea
                  className="skill-yaml-textarea organization-skill-editor"
                  readOnly={!skillFile.data?.editable}
                  value={draftContent}
                  onChange={(event) => setDraftContent(event.target.value)}
                />
              </label>
              <button disabled={!skillFile.data?.editable || saveFile.isPending} onClick={() => saveFile.mutate()} type="button">保存文件</button>
              {saveFile.error && <ErrorNotice error={saveFile.error} />}
            </>
          ) : (
            <p className="muted">暂无组织技能。</p>
          )}
        </section>
        <form className="panel form organization-skill-create" onSubmit={(event) => { event.preventDefault(); if (newName.trim()) createSkill.mutate(); }}>
          <div className="panel-heading">
            <div>
              <h2>创建技能</h2>
              <p className="muted">安装为组织级 skill。</p>
            </div>
          </div>
          <label>名称<input value={newName} onChange={(event) => setNewName(event.target.value)} required /></label>
          <label>Short name<input value={newSlug} onChange={(event) => setNewSlug(event.target.value)} placeholder="incident-response" /></label>
          <label>描述<input value={newDescription} onChange={(event) => setNewDescription(event.target.value)} /></label>
          <label>Skill 内容<textarea className="skill-yaml-textarea" value={newMarkdown} onChange={(event) => setNewMarkdown(event.target.value)} /></label>
          {createSkill.error && <ErrorNotice error={createSkill.error} />}
          <button disabled={createSkill.isPending || !newName.trim()} type="submit">创建技能</button>
        </form>
      </div>
    </OrgWorkspace>
  );
}

interface WorkspaceTreeEntry {
  children?: WorkspaceTreeEntry[];
  content?: string | null;
  detail?: string;
  icon?: string;
  isDirectory: boolean;
  path: string;
}

function jsonFile(path: string, value: unknown, detail?: string, icon = "{}"): WorkspaceTreeEntry {
  return {
    content: formatJson(value),
    detail,
    icon,
    isDirectory: false,
    path,
  };
}

function workspaceEntryLabel(entry: WorkspaceTreeEntry): string {
  return entry.path.split("/").at(-1) ?? entry.path;
}

function sortWorkspaceEntries(entries: WorkspaceTreeEntry[]): WorkspaceTreeEntry[] {
  return entries
    .map((entry) => ({
      ...entry,
      children: entry.children ? sortWorkspaceEntries(entry.children) : entry.children,
    }))
    .sort((left, right) =>
      workspaceEntryLabel(left).localeCompare(workspaceEntryLabel(right), undefined, {
        numeric: true,
        sensitivity: "base",
      }),
    );
}

function formatJson(value: unknown): string {
  if (value === null || value === undefined) return "{}";
  return JSON.stringify(value, null, 2);
}

function slugPath(value: string): string {
  return value.trim().toLowerCase().replace(/[^a-z0-9._-]+/g, "-").replace(/^-+|-+$/g, "") || "item";
}

function projectWorkspaces(project: ProjectDetail): ProjectWorkspace[] {
  if (project.workspaces && project.workspaces.length > 0) return project.workspaces;
  if (!project.codebase) return [];
  return [
    {
      id: `${project.id}-codebase-workspace`,
      orgId: project.orgId,
      projectId: project.id,
      name: project.name,
      sourceType: project.codebase.origin ?? "project",
      cwd: project.codebase.effectiveLocalFolder ?? project.codebase.localFolder ?? null,
      repoUrl: project.codebase.repoUrl ?? null,
      repoRef: project.codebase.repoRef ?? null,
      defaultRef: project.codebase.defaultRef ?? null,
      visibility: "project",
      setupCommand: null,
      cleanupCommand: null,
      remoteProvider: null,
      remoteWorkspaceRef: null,
      sharedWorkspaceKey: project.codebase.workspaceId ?? null,
      metadata: null,
      isPrimary: true,
      runtimeServices: [],
      createdAt: project.createdAt,
      updatedAt: project.updatedAt,
    },
  ];
}

function buildWorkspaceTree(projects: ProjectDetail[], agents: Agent[], requestedPath: string | null): WorkspaceTreeEntry[] {
  const projectChildren = projects.map((project) => ({
    children: [
      jsonFile(`projects/${slugPath(project.name)}/project.json`, project, "项目详情", "P"),
      jsonFile(`projects/${slugPath(project.name)}/workspace-policy.json`, project.executionWorkspacePolicy ?? {}, "执行策略", "⚙"),
      ...projectWorkspaces(project).map((workspace) =>
        jsonFile(`projects/${slugPath(project.name)}/workspaces/${slugPath(workspace.name)}.json`, workspace, workspace.cwd ?? undefined, "W"),
      ),
    ],
    detail: project.codebase?.effectiveLocalFolder ?? project.description ?? undefined,
    icon: "P",
    isDirectory: true,
    path: `projects/${slugPath(project.name)}`,
  }));
  const agentChildren = agents.map((agent) => ({
    children: [
      jsonFile(`agents/${slugPath(agent.name)}/config.json`, agent.agentRuntimeConfig ?? {}, agent.agentRuntimeType, "⚙"),
      jsonFile(`agents/${slugPath(agent.name)}/status.json`, {
        id: agent.id,
        name: agent.name,
        role: agent.role,
        status: agent.status,
        reportsTo: agent.reportsTo ?? null,
        lastHeartbeatAt: agent.lastHeartbeatAt,
      }, "智能体状态", "S"),
    ],
    detail: `${agent.agentRuntimeType} · ${agent.status}`,
    icon: "A",
    isDirectory: true,
    path: `agents/${slugPath(agent.name)}`,
  }));
  const skillFiles = agents
    .filter((agent) => Array.isArray(agent.desiredSkills) && agent.desiredSkills.length > 0)
    .map((agent) => jsonFile(`skills/${slugPath(agent.name)}.json`, agent.desiredSkills ?? [], agent.name, "K"));
  const entries: WorkspaceTreeEntry[] = [
    { children: [], detail: "运行产物", icon: "A", isDirectory: true, path: "artifacts" },
    { children: [], detail: "构建输出", icon: "D", isDirectory: true, path: "dist" },
    { children: [], detail: "上游兼容目录", icon: "M", isDirectory: true, path: "Microsoft" },
    {
      children: [
        jsonFile("node_mode/runtime.json", {
          agents: agents.map((agent) => ({ name: agent.name, runtime: agent.agentRuntimeType, status: agent.status })),
        }, "runtime", "N"),
      ],
      detail: "Node runtime mode",
      icon: "N",
      isDirectory: true,
      path: "node_mode",
    },
    { children: projectChildren, detail: `${projects.length} 个项目`, icon: "P", isDirectory: true, path: "plans" },
    { children: skillFiles, detail: `${skillFiles.length} 个技能声明`, icon: "K", isDirectory: true, path: "skills" },
    { children: projectChildren, detail: "项目源代码入口", icon: "S", isDirectory: true, path: "src" },
    { children: agentChildren, detail: `${agents.length} 个智能体`, icon: "A", isDirectory: true, path: "agents" },
  ];
  if (requestedPath && !findWorkspaceEntry(entries, requestedPath)) {
    entries.unshift({
      content: "当前 server 未提供组织工作区文件读取接口，暂不能加载该文件内容。",
      detail: "等待 server workspace file API",
      icon: fileFormat(requestedPath).slice(0, 1).toUpperCase(),
      isDirectory: false,
      path: requestedPath,
    });
  }
  return sortWorkspaceEntries(entries);
}

function findWorkspaceEntry(entries: WorkspaceTreeEntry[], path: string): WorkspaceTreeEntry | undefined {
  for (const entry of entries) {
    if (entry.path === path) return entry;
    const child = entry.children ? findWorkspaceEntry(entry.children, path) : undefined;
    if (child) return child;
  }
  return undefined;
}

function parentDirectories(path: string | null): Set<string> {
  if (!path) return new Set();
  const parts = path.split("/").filter(Boolean);
  return new Set(parts.slice(0, -1).map((_, index) => parts.slice(0, index + 1).join("/")));
}

function fileFormat(path: string | null): string {
  if (!path) return "text";
  const ext = path.split(".").pop()?.toLowerCase();
  if (!ext || ext === path) return "text";
  return ext === "md" ? "markdown" : ext;
}

function workspaceIconClass(icon: string | undefined, fallback: "file" | "folder"): string {
  const normalized = icon?.toLowerCase();
  if (normalized === "{}") return "workspace-tree-icon-json";
  if (normalized === "⚙") return "workspace-tree-icon-config";
  if (normalized && /^[a-z0-9_-]+$/.test(normalized)) return `workspace-tree-icon-${normalized}`;
  return `workspace-tree-icon-${fallback}`;
}

function WorkspaceTreeNode({
  entry,
  expandedParents,
  onSelect,
  selectedPath,
  depth = 0,
}: {
  entry: WorkspaceTreeEntry;
  expandedParents: Set<string>;
  onSelect: (path: string) => void;
  selectedPath: string | null;
  depth?: number;
}) {
  const [expanded, setExpanded] = useState(expandedParents.has(entry.path));
  useEffect(() => {
    if (expandedParents.has(entry.path)) setExpanded(true);
  }, [entry.path, expandedParents]);
  const label = entry.path.split("/").at(-1) ?? entry.path;
  if (entry.isDirectory) {
    return (
      <li>
        <button
          aria-expanded={expanded}
          className="workspace-tree-row workspace-tree-directory"
          onClick={() => setExpanded((value) => !value)}
          style={{ paddingLeft: `${depth * 14 + 8}px` }}
          type="button"
        >
          <span aria-hidden="true" className="workspace-tree-chevron">{expanded ? "⌄" : "›"}</span>
          <span aria-hidden="true" className={`workspace-tree-icon ${workspaceIconClass(entry.icon, "folder")}`}>
            {entry.icon ?? "F"}
          </span>
          <span className="workspace-tree-label">{label}</span>
          {entry.detail && <small>{entry.detail}</small>}
        </button>
        {expanded && entry.children && entry.children.length > 0 && (
          <ul className="workspace-tree-list">
            {entry.children.map((child) => (
              <WorkspaceTreeNode
                depth={depth + 1}
                entry={child}
                expandedParents={expandedParents}
                key={child.path}
                onSelect={onSelect}
                selectedPath={selectedPath}
              />
            ))}
          </ul>
        )}
      </li>
    );
  }
  return (
    <li>
      <button
        className={`workspace-tree-row workspace-tree-file ${selectedPath === entry.path ? "selected" : ""}`}
        onClick={() => onSelect(entry.path)}
        style={{ paddingLeft: `${depth * 14 + 28}px` }}
        type="button"
      >
        <span aria-hidden="true" className={`workspace-tree-icon ${workspaceIconClass(entry.icon, "file")}`}>
          {entry.icon ?? "·"}
        </span>
        <span className="workspace-tree-label">{label}</span>
        {entry.detail && <small>{entry.detail}</small>}
      </button>
    </li>
  );
}

export function OrganizationWorkspacesPage() {
  const { orgId = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedPath = searchParams.get("path")?.trim() || null;
  const [selectedPath, setSelectedPath] = useState<string | null>(requestedPath);
  const projects = useQuery({
    queryKey: ["projects", orgId],
    queryFn: () => projectsApi.list(orgId),
  });
  const agents = useQuery({
    queryKey: ["agents", orgId],
    queryFn: () => agentsApi.list(orgId),
  });
  const projectList = Array.isArray(projects.data) ? projects.data : [];
  const agentList = Array.isArray(agents.data) ? agents.data : [];
  const workspaceTree = useMemo(
    () => buildWorkspaceTree(projectList, agentList, requestedPath),
    [agentList, projectList, requestedPath],
  );
  const selectedEntry = selectedPath ? findWorkspaceEntry(workspaceTree, selectedPath) : undefined;
  const expandedParents = useMemo(() => parentDirectories(selectedPath), [selectedPath]);

  useEffect(() => {
    setSelectedPath(requestedPath);
  }, [requestedPath]);

  useEffect(() => {
    if (selectedPath) return;
    const firstFile = findWorkspaceEntry(workspaceTree, "package-lock.json")
      ?? workspaceTree.flatMap((entry) => entry.children ?? [entry]).find((entry) => !entry.isDirectory);
    if (firstFile && !firstFile.isDirectory) {
      setSelectedPath(firstFile.path);
      const next = new URLSearchParams(searchParams);
      next.set("path", firstFile.path);
      setSearchParams(next, { replace: true });
    }
  }, [searchParams, selectedPath, setSearchParams, workspaceTree]);

  function selectFile(path: string) {
    setSelectedPath(path);
    const next = new URLSearchParams(searchParams);
    next.set("path", path);
    setSearchParams(next, { replace: true });
  }

  return (
    <OrgWorkspace orgId={orgId}>
      <header className="page-header">
        <div>
          <p className="eyebrow">Organization</p>
          <h1>工作区</h1>
          <p className="muted">按上游工作区布局展示文件树和编辑区。</p>
        </div>
        <button disabled type="button">Refresh</button>
      </header>
      {projects.error && <ErrorNotice error={projects.error} />}
      {agents.error && <ErrorNotice error={agents.error} />}
      <div className="workspace-shell-layout">
        <section className="workspace-files-card" data-testid="org-workspaces-files-card">
          <div className="workspace-card-header">
            <div>
              <h2>Files</h2>
              <p>/</p>
            </div>
            <Badge>{workspaceTree.length}</Badge>
          </div>
          <div className="workspace-files-scroll">
            <ul className="workspace-tree-list">
              {workspaceTree.map((entry) => (
                <WorkspaceTreeNode
                  entry={entry}
                  expandedParents={expandedParents}
                  key={entry.path}
                  onSelect={selectFile}
                  selectedPath={selectedPath}
                />
              ))}
            </ul>
          </div>
        </section>
        <section className="workspace-editor-card" data-testid="org-workspaces-editor-card">
          <div className="workspace-card-header workspace-editor-header">
            <div>
              <h2>Editor</h2>
              <p>{selectedPath ?? "Select a file to edit"}</p>
            </div>
            <div className="workspace-editor-actions">
              {selectedPath && <span className="workspace-format-pill">{fileFormat(selectedPath)}</span>}
              <button disabled title="当前 server 未提供组织工作区文件保存接口" type="button">Save</button>
            </div>
          </div>
          <div className="workspace-editor-body">
            {!selectedPath ? (
              <p className="muted">Choose a file from the workspace tree to edit it.</p>
            ) : (
              <>
                {!selectedEntry && <p className="error-notice">未找到选中的工作区文件。</p>}
                <textarea
                  aria-label="工作区文件内容"
                  className="workspace-text-editor"
                  readOnly
                  spellCheck={false}
                  value={selectedEntry?.content ?? "当前 server 未提供组织工作区文件读取接口，暂不能加载该文件内容。"}
                />
              </>
            )}
          </div>
        </section>
      </div>
    </OrgWorkspace>
  );
}

export function OrgNavigation({ orgId }: { orgId: string }) {
  const projects = useQuery({
    queryKey: ["projects", orgId],
    queryFn: () => projectsApi.list(orgId),
  });
  const projectList = Array.isArray(projects.data) ? projects.data : [];
  return (
    <aside className="org-sidebar">
      <p className="org-sidebar-label">Organization</p>
      <nav className="local-nav" aria-label="组织导航">
        <section className="local-nav-section">
          <h2>组织</h2>
          <NavLink className="local-nav-primary" to={`/orgs/${orgId}/structure`}>
            <span aria-hidden="true" className="context-entry-icon">O</span>
            <span>组织架构</span>
          </NavLink>
          <NavLink className="local-nav-primary" to={`/orgs/${orgId}/heartbeat-runs`}>
            <span aria-hidden="true" className="context-entry-icon">H</span>
            <span>心跳</span>
          </NavLink>
          <NavLink className="local-nav-primary" to={`/orgs/${orgId}/resources`}>
            <span aria-hidden="true" className="context-entry-icon">R</span>
            <span>资源</span>
          </NavLink>
          <NavLink className="local-nav-primary" to={`/orgs/${orgId}/workspaces`}>
            <span aria-hidden="true" className="context-entry-icon">W</span>
            <span>工作区</span>
          </NavLink>
          <NavLink className="local-nav-primary" to={`/orgs/${orgId}/goals`}>
            <span aria-hidden="true" className="context-entry-icon">G</span>
            <span>目标</span>
          </NavLink>
          <NavLink className="local-nav-primary" to={`/orgs/${orgId}/skills`}>
            <span aria-hidden="true" className="context-entry-icon">K</span>
            <span>技能</span>
          </NavLink>
        </section>
        <section className="local-nav-section">
          <h2>项目</h2>
          {projects.error && <ErrorNotice error={projects.error} />}
          <div className="local-project-list">
            {projectList.map((project) => (
              <NavLink
                className="local-nav-project local-nav-project-prominent"
                key={project.id}
                to={`/orgs/${orgId}/projects/${project.id}`}
              >
                <span
                  aria-hidden="true"
                  className="context-entry-icon project-entry-icon"
                  style={{ background: project.color ?? undefined }}
                >
                  P
                </span>
                <span>{project.name}</span>
              </NavLink>
            ))}
            {projects.isSuccess && projectList.length === 0 && <p className="context-empty">暂无项目</p>}
          </div>
        </section>
      </nav>
    </aside>
  );
}

export function OrgWorkspace({ orgId, children }: PropsWithChildren<{ orgId: string }>) {
  return (
    <div className="org-workspace">
      <OrgNavigation orgId={orgId} />
      <div className="org-content">{children}</div>
    </div>
  );
}
