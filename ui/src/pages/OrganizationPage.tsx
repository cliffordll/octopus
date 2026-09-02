import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type FormEvent, type PropsWithChildren } from "react";
import { Link, Navigate, NavLink, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { accessApi, type OrganizationHierarchyMember } from "../api/access";
import { organizationSkillsApi } from "../api/organizationSkills";
import { organizationsApi } from "../api/organizations";
import { projectsApi } from "../api/projects";
import type { OrganizationResource, OrganizationSkillFileInventoryEntry, OrganizationSkillListItem, OrganizationWorkspaceFileDetail, OrganizationWorkspaceFileEntry } from "../api/types";
import { Badge } from "../components/Badge";
import { ErrorNotice } from "../components/ErrorNotice";
import { FileBrowser } from "../components/FileBrowser";
import { MemberAccessSettings } from "../components/MemberAccessSettings";
import { OrganizationCostPanel } from "../components/OrganizationCostPanel";
import { SidebarIcon } from "../components/SidebarIcon";
import { TertiaryPageFrame, TertiaryPageHeader, TertiaryPageShell, TertiaryPageViewport } from "../components/TertiaryPageShell";
import { sourceLabel } from "../utils/display";

export function OrganizationPage() {
  const { orgId = "" } = useParams();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [budgetMonthlyDollars, setBudgetMonthlyDollars] = useState("");
  const [brandColor, setBrandColor] = useState("");
  const [requireBoardApprovalForNewAgents, setRequireBoardApprovalForNewAgents] = useState(false);
  const [defaultChatIssueCreationMode, setDefaultChatIssueCreationMode] = useState("manual_approval");
  const queryClient = useQueryClient();
  const organization = useQuery({
    queryKey: ["organization", orgId],
    queryFn: () => organizationsApi.get(orgId),
  });
  useEffect(() => {
    if (organization.data) {
      setName(organization.data.name);
      setDescription(organization.data.description ?? "");
      setBudgetMonthlyDollars(String(((organization.data.budgetMonthlyCents ?? 0) / 100).toFixed(2)));
      setBrandColor(organization.data.brandColor ?? "");
      setRequireBoardApprovalForNewAgents(Boolean(organization.data.requireBoardApprovalForNewAgents));
      setDefaultChatIssueCreationMode(organization.data.defaultChatIssueCreationMode ?? "manual_approval");
    }
  }, [organization.data]);
  const update = useMutation({
    mutationFn: () =>
      organizationsApi.update(orgId, {
        name: name.trim(),
        description: description.trim() || null,
        budgetMonthlyCents: budgetMonthlyDollars.trim() ? Math.round(Number(budgetMonthlyDollars) * 100) : undefined,
        brandColor: brandColor.trim() || null,
        requireBoardApprovalForNewAgents,
        defaultChatIssueCreationMode,
      }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["organization", orgId] }),
  });
  const archive = useMutation({
    mutationFn: () => organizationsApi.archive(orgId),
    onSuccess: (updated) => {
      queryClient.setQueryData(["organization", orgId], updated);
      void queryClient.invalidateQueries({ queryKey: ["organizations"] });
      navigate("/organizations");
    },
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    update.mutate();
  }
  if (organization.error) return <ErrorNotice error={organization.error} />;
  return (
    <div className="org-content organization-settings tertiary-page-content">
      <TertiaryPageShell>
      <TertiaryPageHeader eyebrow="Organization Settings" title="组织设置" />
      <TertiaryPageViewport>
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
            月度预算（美元）
            <input
              min="0"
              step="0.01"
              type="number"
              value={budgetMonthlyDollars}
              onChange={(event) => setBudgetMonthlyDollars(event.target.value)}
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
              <option value="manual_approval">手动确认</option>
              <option value="auto_create">自动创建</option>
            </select>
          </label>
          {update.error && <ErrorNotice error={update.error} />}
          {archive.error && <ErrorNotice error={archive.error} />}
          <div className="form-actions">
            <button type="submit">保存组织</button>
            <button
              className="danger"
              disabled={organization.data?.status === "archived" || archive.isPending}
              type="button"
              onClick={() => archive.mutate()}
            >
              归档组织
            </button>
          </div>
      </form>
      </TertiaryPageViewport>
      </TertiaryPageShell>
    </div>
  );
}

export function OrganizationCostsPage() {
  const { orgId = "" } = useParams();
  return (
    <OrgWorkspace contentClassName="org-content-full tertiary-page-contained organization-fullscreen-detail organization-costs-content" orgId={orgId}>
      <TertiaryPageHeader
        eyebrow="Organization Costs"
        supporting="按智能体、服务商、计费方和项目查看运行成本。"
        title="成本"
      />
      <OrganizationCostPanel orgId={orgId} />
    </OrgWorkspace>
  );
}

export function OrganizationMembersPage() {
  const { orgId = "" } = useParams();
  return (
    <OrgWorkspace contentClassName="org-content-full organization-members-content" orgId={orgId}>
      <MemberAccessSettings orgId={orgId} />
    </OrgWorkspace>
  );
}

export function OrganizationIndexPage() {
  const { orgId = "" } = useParams();
  return <Navigate replace to={`/orgs/${orgId}/structure`} />;
}

const ORG_CARD_WIDTH = 210;
const ORG_CARD_HEIGHT = 132;
const ORG_GAP_X = 34;
const ORG_GAP_Y = 82;
const ORG_PADDING = 56;
const ORG_CANVAS_PADDING = 64;

interface OrganizationNode {
  member: OrganizationHierarchyMember;
  children: OrganizationNode[];
}

interface LayoutNode {
  member: OrganizationHierarchyMember;
  x: number;
  y: number;
  children: LayoutNode[];
}

function buildOrganizationTree(members: OrganizationHierarchyMember[]): OrganizationNode[] {
  const nodes = new Map(members.map((member) => [member.id, { member, children: [] as OrganizationNode[] }]));
  const roots: OrganizationNode[] = [];
  for (const node of nodes.values()) {
    const parentId = node.member.reportsTo;
    const parent = parentId ? nodes.get(parentId) : undefined;
    if (parent && parent.member.id !== node.member.id) {
      parent.children.push(node);
    } else {
      roots.push(node);
    }
  }
  const sortNodes = (items: OrganizationNode[]) => {
    items.sort((left, right) => left.member.displayName.localeCompare(right.member.displayName));
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
    member: node.member,
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

function fitOrganizationChart(viewport: HTMLDivElement, bounds: { width: number; height: number }): number {
  const width = viewport.clientWidth || 800;
  const height = viewport.clientHeight || 560;
  const availableWidth = Math.max(width - 40, 1);
  const availableHeight = Math.max(height - 40, 1);
  return Math.min(
    Math.max(Math.min(availableWidth / bounds.width, availableHeight / bounds.height), 0.35),
    1,
  );
}

export function OrganizationStructurePage() {
  const { orgId = "" } = useParams();
  const viewportRef = useRef<HTMLDivElement>(null);
  const centeredRef = useRef(false);
  const [zoom, setZoom] = useState(1);
  const [viewportSize, setViewportSize] = useState({ width: 800, height: 560 });
  const [adjusting, setAdjusting] = useState(false);
  const [editingMemberId, setEditingMemberId] = useState<string | null>(null);
  const [managerId, setManagerId] = useState("");
  const queryClient = useQueryClient();
  const hierarchy = useQuery({
    queryKey: ["organization-hierarchy", orgId],
    queryFn: () => accessApi.hierarchy(orgId),
  });
  const memberList = Array.isArray(hierarchy.data) ? hierarchy.data : [];
  const memberNameById = new Map(memberList.map((member) => [member.id, member.displayName]));
  const organizationTree = useMemo(() => buildOrganizationTree(memberList), [memberList]);
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
  const canvasWidth = Math.max(viewportSize.width, bounds.width * zoom + ORG_CANVAS_PADDING * 2);
  const canvasHeight = Math.max(viewportSize.height, bounds.height * zoom + ORG_CANVAS_PADDING * 2);
  const canvasOffset = {
    x: Math.max(ORG_CANVAS_PADDING, (canvasWidth - bounds.width * zoom) / 2),
    y: Math.max(ORG_CANVAS_PADDING, (canvasHeight - bounds.height * zoom) / 2),
  };

  useEffect(() => {
    if (!viewportRef.current) return;
    const viewport = viewportRef.current;
    const measure = () => {
      setViewportSize({
        width: viewport.clientWidth || 800,
        height: viewport.clientHeight || 560,
      });
    };
    measure();
    if (typeof ResizeObserver !== "undefined") {
      const observer = new ResizeObserver(measure);
      observer.observe(viewport);
      return () => observer.disconnect();
    }
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);

  useEffect(() => {
    if (!viewportRef.current || nodes.length === 0 || centeredRef.current) return;
    const viewport = viewportRef.current;
    requestAnimationFrame(() => {
      viewport.scrollLeft = Math.max(0, (viewport.scrollWidth - viewport.clientWidth) / 2);
      viewport.scrollTop = 0;
      centeredRef.current = true;
    });
  }, [canvasWidth, nodes.length]);

  const updateManager = useMutation({
    mutationFn: () => {
      if (!editingMemberId) throw new Error("请选择需要调整的成员");
      return accessApi.updateManager(orgId, editingMemberId, managerId || null);
    },
    onSuccess: () => {
      setEditingMemberId(null);
      setManagerId("");
      void queryClient.invalidateQueries({ queryKey: ["organization-hierarchy", orgId] });
      void queryClient.invalidateQueries({ queryKey: ["agents", orgId] });
    },
  });
  const editingMember = memberList.find((member) => member.id === editingMemberId) ?? null;
  const excludedManagerIds = useMemo(() => {
    if (!editingMemberId) return new Set<string>();
    const excluded = new Set<string>([editingMemberId]);
    let changed = true;
    while (changed) {
      changed = false;
      for (const member of memberList) {
        if (member.reportsTo && excluded.has(member.reportsTo) && !excluded.has(member.id)) {
          excluded.add(member.id);
          changed = true;
        }
      }
    }
    return excluded;
  }, [editingMemberId, memberList]);

  function openManagerEditor(member: OrganizationHierarchyMember) {
    setEditingMemberId(member.id);
    setManagerId(member.reportsTo ?? "");
  }

  function fitChart() {
    if (!viewportRef.current) return;
    const viewport = viewportRef.current;
    setZoom(fitOrganizationChart(viewport, bounds));
    requestAnimationFrame(() => {
      viewport.scrollLeft = Math.max(0, (viewport.scrollWidth - viewport.clientWidth) / 2);
      viewport.scrollTop = Math.max(0, (viewport.scrollHeight - viewport.clientHeight) / 2);
    });
  }

  return (
    <OrgWorkspace contentClassName="org-content-full tertiary-page-contained organization-structure-content" orgId={orgId}>
      <TertiaryPageHeader
        actions={memberList.length > 0 ? (
          <div className="org-chart-controls org-page-actions">
            <button
              className={adjusting ? "primary small-button" : "secondary small-button"}
              type="button"
              onClick={() => {
                setAdjusting((value) => !value);
                setEditingMemberId(null);
              }}
            >
              {adjusting ? "完成调整" : "调整架构"}
            </button>
            <button className="secondary small-button" type="button" onClick={() => setZoom((value) => Math.min(value * 1.2, 1.8))}>+</button>
            <button className="secondary small-button" type="button" onClick={() => setZoom((value) => Math.max(value * 0.8, 0.35))}>-</button>
            <button className="secondary small-button" type="button" onClick={fitChart}>Fit</button>
          </div>
        ) : undefined}
        eyebrow="Organization"
        supporting="Human 与 Agent 共用一套汇报关系。可缩放或左右滚动查看完整架构。"
        title="组织架构"
        variant="canvas"
      />
      {hierarchy.error && <ErrorNotice error={hierarchy.error} />}
      {hierarchy.isSuccess && memberList.length === 0 ? (
        <section className="panel organization-empty-state">
          <p className="muted">暂无组织成员。邀请 Human 或创建智能体以建立组织架构。</p>
          <Link className="button" to={`/orgs/${orgId}/agents/new`}>新建智能体</Link>
        </section>
      ) : (
        <section aria-label="组织关系画布" className="organization-chart" ref={viewportRef}>
          <div
            className="organization-chart-canvas"
            data-testid="organization-chart-canvas"
            style={{ height: canvasHeight, width: canvasWidth }}
          >
            <svg
              aria-hidden
              className="organization-chart-edges"
              style={{ height: canvasHeight, width: canvasWidth }}
            >
              <g transform={`translate(${canvasOffset.x}, ${canvasOffset.y}) scale(${zoom})`}>
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
                      key={`${parent.member.id}-${child.member.id}`}
                    />
                  );
                })}
              </g>
            </svg>
            <div
              className="organization-chart-layer"
              style={{
                height: bounds.height,
                left: canvasOffset.x,
                top: canvasOffset.y,
                transform: `scale(${zoom})`,
                width: bounds.width,
              }}
            >
              {nodes.map(({ member, x, y }) => (
                <article
                  aria-label={`${member.displayName} ${member.reportsTo ? `向 ${memberNameById.get(member.reportsTo) ?? "未知成员"} 汇报` : "组织负责人"}`}
                  className={`organization-chart-card ${adjusting ? "adjusting" : ""}`}
                  key={member.id}
                  style={{ left: x, top: y }}
                >
                  <div className={`organization-chart-avatar ${member.principalType}`}>{member.displayName.slice(0, 1).toUpperCase()}</div>
                  <div className="organization-chart-copy">
                    {member.principalType === "agent" ? (
                      <Link to={`/orgs/${orgId}/agents/${member.principalId}`}>{member.displayName}</Link>
                    ) : (
                      <strong>{member.displayName}</strong>
                    )}
                    <span>{member.principalType === "agent" ? "Agent" : "Human"} · {member.role}</span>
                    <small>{member.reportsTo ? `向 ${memberNameById.get(member.reportsTo) ?? "未知成员"} 汇报` : "组织负责人"}</small>
                  </div>
                  <Badge>{member.status === "active" ? "有效" : member.status}</Badge>
                  {adjusting && member.role !== "owner" ? (
                    <button className="organization-chart-manager-button" type="button" onClick={() => openManagerEditor(member)}>
                      调整上级
                    </button>
                  ) : null}
                </article>
              ))}
            </div>
          </div>
        </section>
      )}
      {editingMember ? (
        <div className="modal-backdrop" role="presentation">
          <form
            aria-label="调整上级"
            className="modal-card organization-manager-dialog"
            onSubmit={(event) => {
              event.preventDefault();
              updateManager.mutate();
            }}
          >
            <div>
              <p className="eyebrow">Reporting line</p>
              <h2>调整 {editingMember.displayName} 的上级</h2>
              <p className="muted">Human 与 Agent 都可以作为上级。系统会阻止循环汇报关系。</p>
            </div>
            <label>
              直属上级
              <select value={managerId} onChange={(event) => setManagerId(event.target.value)} required>
                <option value="" disabled>请选择上级</option>
                {memberList
                  .filter((member) => member.status === "active" && !excludedManagerIds.has(member.id))
                  .map((member) => (
                    <option key={member.id} value={member.id}>
                      {member.displayName}（{member.principalType === "agent" ? "Agent" : "Human"}）
                    </option>
                  ))}
              </select>
            </label>
            {updateManager.error && <ErrorNotice error={updateManager.error} />}
            <div className="modal-actions">
              <button className="secondary" type="button" onClick={() => setEditingMemberId(null)}>取消</button>
              <button disabled={updateManager.isPending || !managerId} type="submit">保存调整</button>
            </div>
          </form>
        </div>
      ) : null}
    </OrgWorkspace>
  );
}

const RESOURCE_KINDS: OrganizationResource["kind"][] = ["file", "directory", "url", "connector_object"];

function organizationResourceKindLabel(kind: OrganizationResource["kind"]): string {
  const labels: Record<OrganizationResource["kind"], string> = {
    file: "文件",
    directory: "目录",
    url: "链接",
    connector_object: "连接器对象",
  };
  return labels[kind];
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
  const resourceGroups = RESOURCE_KINDS.map((kind) => ({
    kind,
    rows: resourceRows.filter((resource) => resource.kind === kind),
  })).filter((group) => group.rows.length > 0);

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
    <OrgWorkspace contentClassName="org-content-full" orgId={orgId}>
      <TertiaryPageHeader
        actions={<div className="org-resource-actions">
          <button className="org-primary-action" type="button" onClick={openCreateResourceDialog}>添加资源</button>
          <Link className="button secondary small-button" to={`/orgs/${orgId}/workspaces`}>浏览工作区</Link>
        </div>}
        eyebrow="Resources"
        supporting="维护组织内可复用的代码库、文件、链接和连接器对象。资源在这里统一登记，再由项目按角色说明进行引用。"
        title="资源"
      />
      {resources.error && <ErrorNotice error={resources.error} />}
      <section className="panel org-resource-catalog-card" aria-label="资源列表">
        {resources.isSuccess && resourceRows.length === 0 ? (
          <div className="org-resource-empty" aria-label="No resources" />
        ) : (
          <div className="org-resource-groups">
            {resourceGroups.map((group) => (
              <section className="org-resource-group" key={group.kind} aria-labelledby={`resource-group-${group.kind}`}>
                <h2 className="org-resource-group-heading" id={`resource-group-${group.kind}`}>
                  {organizationResourceKindLabel(group.kind)} · {group.rows.length}
                </h2>
                <div className="org-resource-grid">
                  {group.rows.map((resource) => (
                    <article className="org-resource-card" key={resource.id}>
                      <div className="org-resource-card-header">
                        <span className={`org-resource-kind-icon org-resource-kind-${resource.kind}`} aria-hidden="true">
                          {organizationResourceKindIcon(resource.kind)}
                        </span>
                        <h3 title={resource.name}>{resource.name}</h3>
                      </div>
                      <p className="org-resource-locator" title={resource.locator}>{resource.locator}</p>
                      {resource.description && <p className="org-resource-description" title={resource.description}>{resource.description}</p>}
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
              </section>
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

function encodeSkillFileRoute(path: string): string {
  return path.split("/").map((segment) => encodeURIComponent(segment)).join("/");
}

const DEFAULT_SKILL_MARKDOWN = "Use this skill when it is relevant to the current task.";

type SkillFileTreeNode = {
  children: Map<string, SkillFileTreeNode>;
  files: OrganizationSkillFileInventoryEntry[];
  name: string;
  path: string;
};

function createSkillFileTreeNode(name: string, path: string): SkillFileTreeNode {
  return { children: new Map(), files: [], name, path };
}

function buildSkillFileTree(files: OrganizationSkillFileInventoryEntry[]): SkillFileTreeNode {
  const root = createSkillFileTreeNode("", "");
  for (const file of [...files].sort((a, b) => a.path.localeCompare(b.path))) {
    const parts = file.path.split("/").filter(Boolean);
    if (parts.length <= 1) {
      root.files.push(file);
      continue;
    }
    let node = root;
    for (const segment of parts.slice(0, -1)) {
      const path = node.path ? `${node.path}/${segment}` : segment;
      let child = node.children.get(segment);
      if (!child) {
        child = createSkillFileTreeNode(segment, path);
        node.children.set(segment, child);
      }
      node = child;
    }
    node.files.push(file);
  }
  return root;
}

function skillFileDirectoryAncestors(path: string): string[] {
  const parts = path.split("/").filter(Boolean);
  if (parts.length <= 1) return [];
  return parts.slice(0, -1).map((_, index) => parts.slice(0, index + 1).join("/"));
}

function skillFileTreeCount(node: SkillFileTreeNode): number {
  let count = node.files.length;
  for (const child of node.children.values()) count += skillFileTreeCount(child);
  return count;
}

function SkillFileTree({
  expandedDirs,
  files,
  onSelect,
  onToggle,
  selectedPath,
}: {
  expandedDirs: Set<string>;
  files: OrganizationSkillFileInventoryEntry[];
  onSelect: (path: string) => void;
  onToggle: (path: string) => void;
  selectedPath: string;
}) {
  const tree = buildSkillFileTree(files);
  function renderFile(file: OrganizationSkillFileInventoryEntry, level: number) {
    return (
      <button
        className={`organization-skill-file-button ${selectedPath === file.path ? "selected" : ""}`}
        key={file.path}
        onClick={() => onSelect(file.path)}
        style={{ "--skill-file-depth": level } as React.CSSProperties}
        type="button"
      >
        <span className="organization-skill-file-label">
          <span className="organization-skill-file-icon" aria-hidden="true">F</span>
          <span>{file.path.split("/").at(-1) ?? file.path}</span>
        </span>
      </button>
    );
  }
  function renderNode(node: SkillFileTreeNode, level = 0) {
    const directories = Array.from(node.children.values()).sort((a, b) => a.name.localeCompare(b.name));
    return (
      <>
        {node.files.map((file) => renderFile(file, level))}
        {directories.map((directory) => {
          const expanded = expandedDirs.has(directory.path);
          return (
            <div className="organization-skill-directory" key={directory.path} style={{ "--skill-file-depth": level } as React.CSSProperties}>
              <button
                aria-expanded={expanded}
                className="organization-skill-directory-button"
                onClick={() => onToggle(directory.path)}
                type="button"
              >
                <span className="organization-skill-file-label">
                  <span className="organization-skill-directory-icon" aria-hidden="true">D</span>
                  <span>{directory.name}</span>
                </span>
                <small>{skillFileTreeCount(directory)}</small>
                <span className="organization-skill-directory-toggle" aria-hidden="true">{expanded ? "v" : ">"}</span>
              </button>
              {expanded && <div className="organization-skill-directory-children">{renderNode(directory, level + 1)}</div>}
            </div>
          );
        })}
      </>
    );
  }
  return <div className="organization-skill-file-tree">{renderNode(tree)}</div>;
}

function organizationSkillString(skill: OrganizationSkillListItem, key: keyof OrganizationSkillListItem): string {
  const value = skill[key];
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

function normalizedOrganizationSkillSource(value: string): string {
  return value.trim().toLowerCase().replaceAll("-", "_");
}

function organizationSkillSourceCandidates(skill: OrganizationSkillListItem): string[] {
  const sourceKind = typeof skill.metadata?.sourceKind === "string" ? skill.metadata.sourceKind : "";
  return [
    sourceKind
    || "",
    organizationSkillString(skill, "sourceBadge"),
    organizationSkillString(skill, "sourceLocator"),
    organizationSkillString(skill, "sourcePath"),
    organizationSkillString(skill, "sourceLabel"),
  ]
    .map(normalizedOrganizationSkillSource)
    .filter(Boolean);
}

function organizationSkillSourceKind(skill: OrganizationSkillListItem): string {
  return organizationSkillSourceCandidates(skill)[0] ?? "";
}

function isBuiltInOrganizationSkill(skill: OrganizationSkillListItem): boolean {
  const sourceKind = organizationSkillSourceKind(skill);
  return sourceKind === "built_in"
    || sourceKind === "octopus_bundled"
    || sourceKind === "system_bundled"
    || sourceKind === "octopus_bundled"
    || sourceKind.includes("bundled")
    || skill.sourceBadge === "built-in"
    || skill.sourceBadge === "bundled";
}

function isCommunityOrganizationSkill(skill: OrganizationSkillListItem): boolean {
  return organizationSkillSourceCandidates(skill).some((sourceKind) => (
    sourceKind === "community"
    || sourceKind === "community_preset"
    || sourceKind.includes("/community/")
    || sourceKind.includes("\\community\\")
  ));
}

function organizationSkillSourceText(value: string | null | undefined, builtIn: boolean, fallback = "built-in"): string {
  if (builtIn) return "内置";
  if (!value) return sourceLabel(fallback);
  if (normalizedOrganizationSkillSource(value) === "community_preset") return "社区";
  return sourceLabel(value);
}


function organizationSkillSections(skills: OrganizationSkillListItem[]) {
  return [
    { label: "内置技能列表", rows: skills.filter(isBuiltInOrganizationSkill), title: "built-in" },
    { label: "社区技能列表", rows: skills.filter(isCommunityOrganizationSkill), title: "community" },
    {
      label: "本地技能列表",
      title: "local",
      rows: skills.filter((skill) => !isBuiltInOrganizationSkill(skill) && !isCommunityOrganizationSkill(skill)),
    },
  ];
}

export function OrganizationSkillsPage() {
  const params = useParams();
  const orgId = params.orgId ?? "";
  const skillId = params.skillId ?? "";
  const routeFilePath = params["*"] ?? "";
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const skills = useQuery({
    queryKey: ["organization-skills", orgId],
    queryFn: () => organizationSkillsApi.list(orgId),
  });
  const skillRows = Array.isArray(skills.data) ? skills.data : [];
  const [skillFilter, setSkillFilter] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [scanOpen, setScanOpen] = useState(false);
  const [expandedSkillDirs, setExpandedSkillDirs] = useState<Record<string, string[]>>({});
  const [selectedPathBySkill, setSelectedPathBySkill] = useState<Record<string, string>>({});
  const selectedSkill = skillRows.find((skill) => skill.id === skillId) ?? skillRows[0];
  const filteredSkillRows = skillRows.filter((skill) => {
    const filter = skillFilter.trim().toLowerCase();
    if (!filter) return true;
    return [skill.name, skill.slug, skill.description, skill.sourceLabel, skill.sourceBadge]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(filter));
  });
  const [newName, setNewName] = useState("");
  const [newSlug, setNewSlug] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [newMarkdown, setNewMarkdown] = useState(DEFAULT_SKILL_MARKDOWN);
  const [importSourcePath, setImportSourcePath] = useState("");
  const [importSlug, setImportSlug] = useState("");
  const [importName, setImportName] = useState("");
  const [importDescription, setImportDescription] = useState("");
  const [importOverwrite, setImportOverwrite] = useState(false);
  const [scanRootPath, setScanRootPath] = useState("");
  const [scanImportDiscovered, setScanImportDiscovered] = useState(false);
  const [scanOverwrite, setScanOverwrite] = useState(false);
  const [draftContent, setDraftContent] = useState("");
  const selectedPath = selectedSkill ? (routeFilePath || selectedPathBySkill[selectedSkill.id] || skillFilePath(selectedSkill)) : "SKILL.md";
  const filteredSkillSections = organizationSkillSections(filteredSkillRows);
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

  useEffect(() => {
    if (!selectedSkill) return;
    const ancestors = skillFileDirectoryAncestors(selectedPath);
    if (ancestors.length === 0) return;
    setExpandedSkillDirs((current) => {
      const existing = new Set(current[selectedSkill.id] ?? []);
      let changed = false;
      for (const ancestor of ancestors) {
        if (!existing.has(ancestor)) {
          existing.add(ancestor);
          changed = true;
        }
      }
      return changed ? { ...current, [selectedSkill.id]: Array.from(existing) } : current;
    });
  }, [selectedPath, selectedSkill]);

  useEffect(() => {
    if (!skills.isSuccess || skillId || !selectedSkill) return;
    navigate(`/orgs/${orgId}/skills/${selectedSkill.id}`, { replace: true });
  }, [navigate, orgId, selectedSkill, skillId, skills.isSuccess]);

  useEffect(() => {
    if (!skills.isSuccess || !selectedSkill || routeFilePath) return;
    const defaultPath = selectedPathBySkill[selectedSkill.id] ?? skillFilePath(selectedSkill);
    navigate(`/orgs/${orgId}/skills/${selectedSkill.id}/files/${encodeSkillFileRoute(defaultPath)}`, { replace: true });
  }, [navigate, orgId, routeFilePath, selectedPathBySkill, selectedSkill, skills.isSuccess]);

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
      setNewMarkdown(DEFAULT_SKILL_MARKDOWN);
      setCreateOpen(false);
      navigate(`/orgs/${orgId}/skills/${skill.id}`);
      void queryClient.invalidateQueries({ queryKey: ["organization-skills", orgId] });
    },
  });
  const importSkill = useMutation({
    mutationFn: () => organizationSkillsApi.import(orgId, {
      sourcePath: importSourcePath.trim(),
      slug: importSlug.trim() || null,
      name: importName.trim() || null,
      description: importDescription.trim() || null,
      overwrite: importOverwrite,
    }),
    onSuccess: (skill) => {
      setImportSourcePath("");
      setImportSlug("");
      setImportName("");
      setImportDescription("");
      setImportOverwrite(false);
      setImportOpen(false);
      navigate(`/orgs/${orgId}/skills/${skill.id}`);
      void queryClient.invalidateQueries({ queryKey: ["organization-skills", orgId] });
    },
  });
  const scanLocalSkills = useMutation({
    mutationFn: () => organizationSkillsApi.scanLocal(orgId, {
      rootPath: scanRootPath.trim(),
      importDiscovered: scanImportDiscovered,
      overwrite: scanOverwrite,
    }),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ["organization-skills", orgId] });
      if (result.imported[0]) {
        setScanOpen(false);
        navigate(`/orgs/${orgId}/skills/${result.imported[0].id}`);
      }
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
      navigate(`/orgs/${orgId}/skills`);
      void queryClient.invalidateQueries({ queryKey: ["organization-skills", orgId] });
    },
  });
  const installUpdate = useMutation({
    mutationFn: (skillId: string) => organizationSkillsApi.installUpdate(orgId, skillId),
    onSuccess: (skill) => {
      void queryClient.invalidateQueries({ queryKey: ["organization-skills", orgId] });
      void queryClient.invalidateQueries({ queryKey: ["organization-skill", orgId, skill.id] });
      void queryClient.invalidateQueries({ queryKey: ["organization-skill-update-status", orgId, skill.id] });
    },
  });

  function submitCreateSkill(event: FormEvent) {
    event.preventDefault();
    if (newName.trim()) createSkill.mutate();
  }

  function submitImportSkill(event: FormEvent) {
    event.preventDefault();
    if (importSourcePath.trim()) importSkill.mutate();
  }

  function submitScanLocalSkills(event: FormEvent) {
    event.preventDefault();
    if (scanRootPath.trim()) scanLocalSkills.mutate();
  }

  function toggleSkillDirectory(skillId: string, path: string) {
    setExpandedSkillDirs((current) => {
      const existing = new Set(current[skillId] ?? []);
      if (existing.has(path)) {
        existing.delete(path);
      } else {
        existing.add(path);
      }
      return { ...current, [skillId]: Array.from(existing) };
    });
  }

  function selectSkillFile(skillId: string, path: string) {
    setSelectedPathBySkill((current) => ({ ...current, [skillId]: path }));
    navigate(`/orgs/${orgId}/skills/${skillId}/files/${encodeSkillFileRoute(path)}`);
  }

  return (
    <OrgWorkspace contentClassName="org-content-full tertiary-page-contained organization-skills-content" orgId={orgId}>
      <TertiaryPageHeader
        eyebrow="Skills"
        supporting={`${skillRows.length} 个可用`}
        title="技能"
      />
      {skills.error && <ErrorNotice error={skills.error} />}
      <div className="organization-skills-shell">
        <aside className="organization-skills-sidebar">
          <div className="organization-skill-list-tools">
            <div className="skills-page-actions" role="group" aria-label="技能管理">
              <button className="org-primary-action" onClick={() => setCreateOpen(true)} type="button">创建技能</button>
              <button className="secondary small-button" onClick={() => setImportOpen(true)} type="button">导入</button>
              <button className="secondary small-button" onClick={() => setScanOpen(true)} type="button">扫描</button>
            </div>
          <label className="organization-skill-search">
            <span>搜索技能</span>
            <input
              aria-label="搜索技能"
              placeholder="筛选技能"
              value={skillFilter}
              onChange={(event) => setSkillFilter(event.target.value)}
            />
          </label>
          </div>
          <div className="organization-skill-list-panel">
            {skills.isLoading && <p className="muted">加载技能中...</p>}
            {filteredSkillSections.map((section) => (
              <section className="organization-skill-list-section" key={section.title}>
                <div className="organization-skill-list-section-heading">
                  <h2>{section.label}</h2>
                  <span>{section.rows.length}</span>
                </div>
                {section.rows.map((skill) => (
                  <button
                    className={`organization-skill-list-card ${selectedSkill?.id === skill.id ? "selected" : ""}`}
                    key={skill.id}
                    onClick={() => navigate(`/orgs/${orgId}/skills/${skill.id}/files/${encodeSkillFileRoute(skillFilePath(skill))}`)}
                    type="button"
                  >
                    <span className="organization-skill-list-card-title">
                      <strong>{skill.name}</strong>
                      <small>{organizationSkillSourceText(skill.sourceBadge, isBuiltInOrganizationSkill(skill))}</small>
                    </span>
                    <span className="organization-skill-list-card-meta">
                      <span>{skill.fileInventory.length} 文件</span>
                      <span>{skill.attachedAgentCount} 智能体</span>
                    </span>
                  </button>
                ))}
              </section>
            ))}
          </div>
        </aside>
        <section className="organization-skill-pane">
          {selectedSkill ? (
            <>
              <div className="organization-skill-overview">
                <div className="organization-skill-pane-header">
                  <div>
                    <div className="organization-skill-title-row">
                      <h2>{selectedSkill.name}</h2>
                      <Badge>{organizationSkillSourceText(selectedSkill.sourceBadge, isBuiltInOrganizationSkill(selectedSkill))}</Badge>
                      <Badge>{updateStatus.data?.hasUpdate ? "有更新" : "无更新"}</Badge>
                    </div>
                  </div>
                  <div className="row-actions">
                    <button className="secondary small-button" onClick={() => void updateStatus.refetch()} type="button">检查更新</button>
                    <button
                      className="secondary small-button"
                      disabled={installUpdate.isPending || !updateStatus.data?.hasUpdate}
                      onClick={() => installUpdate.mutate(selectedSkill.id)}
                      type="button"
                    >
                      安装更新
                    </button>
                    <button
                      className="danger small-button"
                      disabled={deleteSkill.isPending || !selectedSkill.editable}
                      onClick={() => deleteSkill.mutate(selectedSkill.id)}
                      type="button"
                    >
                      删除
                    </button>
                  </div>
                </div>
                <div className="organization-skill-info-grid">
                  <div className="organization-skill-info-grid-full">
                    <span>来源路径</span>
                    <strong title={selectedSkill.sourcePath ?? "未设置"}>{selectedSkill.sourcePath ?? "未设置"}</strong>
                  </div>
                  <div>
                    <span>工作区编辑路径</span>
                    <strong title={selectedSkill.workspaceEditPath ?? "只读或未设置"}>{selectedSkill.workspaceEditPath ?? "只读或未设置"}</strong>
                  </div>
                  <div>
                    <span>兼容性</span>
                    <strong>{selectedSkill.compatibility}</strong>
                  </div>
                </div>
              </div>
              <div className="organization-skill-body">
                {skillDetail.error && <ErrorNotice error={skillDetail.error} />}
                {skillFile.error && <ErrorNotice error={skillFile.error} />}
                {updateStatus.error && <ErrorNotice error={updateStatus.error} />}
                {installUpdate.error && <ErrorNotice error={installUpdate.error} />}
                <FileBrowser
                  className="organization-skill-content-layout"
                  fileTitle={selectedPath}
                  fileStatus={skillFile.data?.editable ? "可编辑" : "只读"}
                  sidebarCount={selectedSkill.fileInventory.length}
                  sidebar={(
                    <SkillFileTree
                      expandedDirs={new Set(expandedSkillDirs[selectedSkill.id] ?? [])}
                      files={selectedSkill.fileInventory}
                      selectedPath={selectedPath}
                      onSelect={(path) => selectSkillFile(selectedSkill.id, path)}
                      onToggle={(path) => toggleSkillDirectory(selectedSkill.id, path)}
                    />
                  )}
                  actions={(
                    <button
                      disabled={!selectedSkill.editable || !skillFile.data?.editable || saveFile.isPending}
                      onClick={() => saveFile.mutate()}
                      type="button"
                    >
                      保存
                    </button>
                  )}
                >
                  <textarea
                    aria-label={selectedPath}
                    className="skill-yaml-textarea organization-skill-editor"
                    readOnly={!selectedSkill.editable || !skillFile.data?.editable}
                    value={draftContent}
                    onChange={(event) => setDraftContent(event.target.value)}
                  />
                  {saveFile.error && <ErrorNotice error={saveFile.error} />}
                </FileBrowser>
              </div>
            </>
          ) : (
            <div className="organization-skill-overview"><p className="muted">暂无组织技能。</p></div>
          )}
        </section>
      </div>
      {createOpen && (
        <div className="modal-backdrop" role="presentation">
          <form className="panel form task-modal skill-create-dialog" onSubmit={submitCreateSkill}>
            <div className="task-modal-header">
            <div>
                <h2>添加技能</h2>
                <p className="muted">创建一个组织级本地技能。</p>
              </div>
              <button className="secondary small-button" onClick={() => setCreateOpen(false)} type="button">取消</button>
            </div>
            <label>名称<input value={newName} onChange={(event) => setNewName(event.target.value)} required /></label>
            <label>Short name<input value={newSlug} onChange={(event) => setNewSlug(event.target.value)} placeholder="incident-response" /></label>
            <label>描述<input value={newDescription} onChange={(event) => setNewDescription(event.target.value)} /></label>
            <label>技能内容<textarea className="skill-yaml-textarea" value={newMarkdown} onChange={(event) => setNewMarkdown(event.target.value)} /></label>
            {createSkill.error && <ErrorNotice error={createSkill.error} />}
            <div className="task-modal-actions">
              <button className="secondary" onClick={() => setCreateOpen(false)} type="button">取消</button>
              <button disabled={createSkill.isPending || !newName.trim()} type="submit">创建技能</button>
            </div>
          </form>
        </div>
      )}
      {importOpen && (
        <div className="modal-backdrop" role="presentation">
          <form className="panel form task-modal skill-create-dialog" onSubmit={submitImportSkill}>
            <div className="task-modal-header">
              <div>
                <h2>导入技能</h2>
                <p className="muted">从本地技能目录导入到当前组织。</p>
              </div>
              <button className="secondary small-button" onClick={() => setImportOpen(false)} type="button">取消</button>
            </div>
            <label>来源路径<input value={importSourcePath} onChange={(event) => setImportSourcePath(event.target.value)} required /></label>
            <label>Short name<input value={importSlug} onChange={(event) => setImportSlug(event.target.value)} placeholder="incident-response" /></label>
            <label>名称<input value={importName} onChange={(event) => setImportName(event.target.value)} /></label>
            <label>描述<input value={importDescription} onChange={(event) => setImportDescription(event.target.value)} /></label>
            <label className="checkbox-row"><input checked={importOverwrite} onChange={(event) => setImportOverwrite(event.target.checked)} type="checkbox" /> 覆盖同名技能</label>
            {importSkill.error && <ErrorNotice error={importSkill.error} />}
            <div className="task-modal-actions">
              <button className="secondary" onClick={() => setImportOpen(false)} type="button">取消</button>
              <button disabled={importSkill.isPending || !importSourcePath.trim()} type="submit">导入技能</button>
            </div>
          </form>
        </div>
      )}
      {scanOpen && (
        <div className="modal-backdrop" role="presentation">
          <form className="panel form task-modal skill-create-dialog" onSubmit={submitScanLocalSkills}>
            <div className="task-modal-header">
              <div>
                <h2>扫描本地技能</h2>
                <p className="muted">扫描目录下的技能，可选择直接导入发现项。</p>
              </div>
              <button className="secondary small-button" onClick={() => setScanOpen(false)} type="button">取消</button>
            </div>
            <label>根路径<input value={scanRootPath} onChange={(event) => setScanRootPath(event.target.value)} required /></label>
            <label className="checkbox-row"><input checked={scanImportDiscovered} onChange={(event) => setScanImportDiscovered(event.target.checked)} type="checkbox" /> 扫描后导入</label>
            <label className="checkbox-row"><input checked={scanOverwrite} onChange={(event) => setScanOverwrite(event.target.checked)} type="checkbox" /> 覆盖同名技能</label>
            {scanLocalSkills.data && (
              <div className="organization-skill-scan-result">
                <p>{scanLocalSkills.data.candidates.length} 个候选，已导入 {scanLocalSkills.data.imported.length} 个。</p>
                {scanLocalSkills.data.candidates.map((candidate) => (
                  <span key={candidate.sourcePath}>{candidate.name} · {candidate.alreadyImported ? "已存在" : candidate.sourcePath}</span>
                ))}
              </div>
            )}
            {scanLocalSkills.error && <ErrorNotice error={scanLocalSkills.error} />}
            <div className="task-modal-actions">
              <button className="secondary" onClick={() => setScanOpen(false)} type="button">取消</button>
              <button disabled={scanLocalSkills.isPending || !scanRootPath.trim()} type="submit">扫描</button>
            </div>
          </form>
        </div>
      )}
    </OrgWorkspace>
  );
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

function displayWorkspaceFileFormat(path: string | null, detail: OrganizationWorkspaceFileDetail | undefined): string {
  if (detail?.previewKind === "image" && detail.contentType) {
    const subtype = detail.contentType.split("/").at(-1) ?? "image";
    return subtype === "svg+xml" ? "svg" : subtype;
  }
  if (detail?.contentType === "application/pdf") return "pdf";
  return fileFormat(path);
}

function workspaceIconClass(icon: string | undefined, fallback: "file" | "folder"): string {
  const normalized = icon?.toLowerCase();
  if (normalized === "{}") return "workspace-tree-icon-json";
  if (normalized === "⚙") return "workspace-tree-icon-config";
  if (normalized && /^[a-z0-9_-]+$/.test(normalized)) return `workspace-tree-icon-${normalized}`;
  return `workspace-tree-icon-${fallback}`;
}

function workspaceEntryLabel(entry: OrganizationWorkspaceFileEntry): string {
  const name = entry.name || entry.path.split("/").at(-1) || entry.path;
  return name;
}

function workspaceHeaderPath(path: string | null): string {
  if (!path) return "未选择文件";
  const parts = path.split("/").filter(Boolean);
  if (parts.length <= 1) return path;
  return `${parts.at(-1)} · ${parts.slice(0, -1).join(" / ")}`;
}

function sortWorkspaceEntries(entries: OrganizationWorkspaceFileEntry[]): OrganizationWorkspaceFileEntry[] {
  return [...entries].sort((left, right) => {
    if (left.isDirectory !== right.isDirectory) return left.isDirectory ? -1 : 1;
    const leftKey = left.name || left.path;
    const rightKey = right.name || right.path;
    return leftKey.localeCompare(rightKey, undefined, {
      numeric: true,
      sensitivity: "base",
    });
  });
}

function WorkspaceTreeNode({
  entry,
  expandedParents,
  orgId,
  onSelect,
  selectedPath,
  depth = 0,
}: {
  entry: OrganizationWorkspaceFileEntry;
  expandedParents: Set<string>;
  orgId: string;
  onSelect: (path: string) => void;
  selectedPath: string | null;
  depth?: number;
}) {
  const [expanded, setExpanded] = useState(expandedParents.has(entry.path));
  const children = useQuery({
    queryKey: ["organization-workspace-files", orgId, entry.path],
    queryFn: () => organizationsApi.workspaceFiles(orgId, entry.path),
    enabled: Boolean(entry.isDirectory && expanded),
  });
  useEffect(() => {
    if (expandedParents.has(entry.path)) setExpanded(true);
  }, [entry.path, expandedParents]);
  const icon = entry.isDirectory ? "F" : undefined;
  const label = workspaceEntryLabel(entry);
  if (entry.isDirectory) {
    const childEntries = children.data?.entries ? sortWorkspaceEntries(children.data.entries) : undefined;
    return (
      <li>
        <button
          aria-expanded={expanded}
          className="workspace-tree-row workspace-tree-directory"
          onClick={() => setExpanded((value) => !value)}
          style={{ paddingLeft: `${depth * 14 + 8}px` }}
          type="button"
        >
          <span aria-hidden="true" className={`workspace-tree-icon ${workspaceIconClass(icon, "folder")}`}>
            {icon ?? "F"}
          </span>
          <span className="workspace-tree-label">{label}</span>
          <span aria-hidden="true" className="workspace-tree-chevron">{expanded ? "⌄" : "›"}</span>
        </button>
        {expanded && children.isLoading && <p className="muted workspace-tree-hint">加载中...</p>}
        {expanded && children.error && <ErrorNotice error={children.error} />}
        {expanded && children.data?.message && children.data.entries.length === 0 && (
          <p className="muted workspace-tree-hint">{children.data.message}</p>
        )}
        {expanded && childEntries && childEntries.length > 0 && (
          <ul className="workspace-tree-list">
            {childEntries.map((child) => (
              <WorkspaceTreeNode
                depth={depth + 1}
                entry={child}
                expandedParents={expandedParents}
                orgId={orgId}
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
        style={{ paddingLeft: `${depth * 14 + 8}px` }}
        type="button"
      >
        <span aria-hidden="true" className={`workspace-tree-icon ${workspaceIconClass(icon, "file")}`}>
          {icon ?? "·"}
        </span>
        <span className="workspace-tree-label">{label}</span>
      </button>
    </li>
  );
}

export function OrganizationWorkspacesPage() {
  const { orgId = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedPath = searchParams.get("path")?.trim() || null;
  const [selectedPath, setSelectedPath] = useState<string | null>(requestedPath);
  const queryClient = useQueryClient();
  const projects = useQuery({
    queryKey: ["projects", orgId],
    queryFn: () => projectsApi.list(orgId),
  });
  const rootFiles = useQuery({
    queryKey: ["organization-workspace-files", orgId, ""],
    queryFn: () => organizationsApi.workspaceFiles(orgId, ""),
  });
  const selectedFile = useQuery({
    queryKey: ["organization-workspace-file", orgId, selectedPath],
    queryFn: () => organizationsApi.workspaceFile(orgId, selectedPath ?? ""),
    enabled: Boolean(selectedPath),
  });
  const workspaceTree = rootFiles.data?.entries ?? [];
  const sortedWorkspaceTree = useMemo(() => sortWorkspaceEntries(workspaceTree), [workspaceTree]);
  const expandedParents = useMemo(() => parentDirectories(selectedPath), [selectedPath]);

  useEffect(() => {
    setSelectedPath(requestedPath);
  }, [requestedPath]);

  useEffect(() => {
    if (selectedPath) return;
    const firstFile = sortedWorkspaceTree.find((entry) => !entry.isDirectory);
    if (firstFile && !firstFile.isDirectory) {
      setSelectedPath(firstFile.path);
      const next = new URLSearchParams(searchParams);
      next.set("path", firstFile.path);
      setSearchParams(next, { replace: true });
    }
  }, [searchParams, selectedPath, setSearchParams, sortedWorkspaceTree]);

  function selectFile(path: string) {
    setSelectedPath(path);
    const next = new URLSearchParams(searchParams);
    next.set("path", path);
    setSearchParams(next, { replace: true });
  }

  function refreshWorkspace() {
    void queryClient.invalidateQueries({ queryKey: ["organization-workspace-files", orgId] });
    void queryClient.invalidateQueries({ queryKey: ["organization-workspace-file", orgId] });
  }

  const selectedDetail = selectedFile.data as OrganizationWorkspaceFileDetail | undefined;

  return (
    <OrgWorkspace contentClassName="org-content-full tertiary-page-contained organization-fullscreen-detail organization-workspaces-content" orgId={orgId}>
      <TertiaryPageHeader
        actions={<button className="org-primary-action" onClick={refreshWorkspace} type="button">刷新</button>}
        eyebrow="Workspaces"
        supporting="查看组织文件、运行产物和智能体配置。"
        title="工作区"
      />
      {projects.error && <ErrorNotice error={projects.error} />}
      {rootFiles.error && <ErrorNotice error={rootFiles.error} />}
      {selectedFile.error && <ErrorNotice error={selectedFile.error} />}
      <FileBrowser
        actions={(
          <>
            {selectedPath && <span className="workspace-format-pill">{displayWorkspaceFileFormat(selectedPath, selectedDetail)}</span>}
            <button disabled title="当前暂只支持工作区预览" type="button">保存</button>
          </>
        )}
        className="workspace-shell-layout"
        fileStatus={selectedPath ? "只读" : "从左侧选择文件"}
        fileTitle={workspaceHeaderPath(selectedPath)}
        framed
        sidebarCount={sortedWorkspaceTree.length}
        sidebarWidth={300}
        treeTestId="org-workspaces-files-card"
        viewerTestId="org-workspaces-editor-card"
        sidebar={(
          <div className="workspace-files-scroll">
            {rootFiles.isLoading && <p className="muted">加载工作区中...</p>}
            {rootFiles.data?.message && <p className="muted">{rootFiles.data.message}</p>}
            <ul className="workspace-tree-list">
              {sortedWorkspaceTree.map((entry) => (
                <WorkspaceTreeNode
                  entry={entry}
                  expandedParents={expandedParents}
                  orgId={orgId}
                  key={entry.path}
                  onSelect={selectFile}
                  selectedPath={selectedPath}
                />
              ))}
            </ul>
          </div>
        )}
      >
        {!selectedPath ? (
          <p className="muted">从左侧选择文件查看内容。</p>
        ) : selectedFile.isLoading ? (
          <p className="muted">加载文件中...</p>
        ) : selectedDetail?.previewKind === "image" && selectedDetail.contentPath ? (
          <div className="workspace-image-preview">
            <img alt={selectedPath} src={selectedDetail.contentPath} />
          </div>
        ) : selectedDetail?.previewKind === "binary" ? (
          <p className="muted">{selectedDetail.message ?? "二进制文件暂不预览。"}</p>
        ) : (
          <textarea
            aria-label="工作区文件内容"
            className="workspace-text-editor"
            readOnly
            spellCheck={false}
            value={selectedDetail?.content ?? ""}
          />
        )}
      </FileBrowser>
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
      <h2>组织</h2>
      <nav className="local-nav" aria-label="组织导航">
        <section className="local-nav-section">
          <h2>组织管理</h2>
          <NavLink className="local-nav-primary" to={`/orgs/${orgId}/structure`}>
            <span aria-hidden="true" className="context-entry-icon"><SidebarIcon name="organization" /></span>
            <span>组织架构</span>
          </NavLink>
          <NavLink className="local-nav-primary" to={`/orgs/${orgId}/members`}>
            <span aria-hidden="true" className="context-entry-icon"><SidebarIcon name="members" /></span>
            <span>成员</span>
          </NavLink>
          <NavLink className="local-nav-primary" to={`/orgs/${orgId}/heartbeat-runs`}>
            <span aria-hidden="true" className="context-entry-icon"><SidebarIcon name="heartbeat" /></span>
            <span>心跳</span>
          </NavLink>
          <NavLink className="local-nav-primary" to={`/orgs/${orgId}/costs`}>
            <span aria-hidden="true" className="context-entry-icon"><SidebarIcon name="costs" /></span>
            <span>成本</span>
          </NavLink>
          <NavLink className="local-nav-primary" to={`/orgs/${orgId}/resources`}>
            <span aria-hidden="true" className="context-entry-icon"><SidebarIcon name="resources" /></span>
            <span>资源</span>
          </NavLink>
          <NavLink className="local-nav-primary" to={`/orgs/${orgId}/workspaces`}>
            <span aria-hidden="true" className="context-entry-icon"><SidebarIcon name="workspaces" /></span>
            <span>工作区</span>
          </NavLink>
          <NavLink className="local-nav-primary" to={`/orgs/${orgId}/goals`}>
            <span aria-hidden="true" className="context-entry-icon"><SidebarIcon name="goals" /></span>
            <span>目标</span>
          </NavLink>
          <NavLink className="local-nav-primary" to={`/orgs/${orgId}/skills`}>
            <span aria-hidden="true" className="context-entry-icon"><SidebarIcon name="skills" /></span>
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
                  <SidebarIcon name="projects" />
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

export function OrgWorkspace({ children, contentClassName = "", orgId }: PropsWithChildren<{ contentClassName?: string; orgId: string }>) {
  const isFullBleed = contentClassName.split(" ").includes("org-content-full");
  const isContained = contentClassName.split(" ").includes("tertiary-page-contained");
  return (
    <div className="org-workspace">
      <OrgNavigation orgId={orgId} />
      <div className={`org-content ${contentClassName}${isFullBleed ? " tertiary-page-content" : ""}`}>
        {isFullBleed
          ? <TertiaryPageFrame contained={isContained}>{children}</TertiaryPageFrame>
          : <div className="tertiary-detail-frame">{children}</div>}
      </div>
    </div>
  );
}
