import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type FormEvent, type PropsWithChildren } from "react";
import { Link, Navigate, NavLink, useParams } from "react-router-dom";
import { agentsApi } from "../api/agents";
import { organizationsApi } from "../api/organizations";
import { projectsApi } from "../api/projects";
import type { Agent } from "../api/types";
import { Badge } from "../components/Badge";
import { ErrorNotice } from "../components/ErrorNotice";

export function OrganizationPage() {
  const { orgId = "" } = useParams();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const queryClient = useQueryClient();
  const organization = useQuery({
    queryKey: ["organization", orgId],
    queryFn: () => organizationsApi.get(orgId),
  });
  useEffect(() => {
    if (organization.data) {
      setName(organization.data.name);
      setDescription(organization.data.description ?? "");
    }
  }, [organization.data]);
  const update = useMutation({
    mutationFn: () =>
      organizationsApi.update(orgId, {
        name: name.trim(),
        description: description.trim() || null,
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
          <NavLink className="local-nav-primary" to={`/orgs/${orgId}/structure`}>组织架构</NavLink>
          <NavLink className="local-nav-primary" to={`/orgs/${orgId}/heartbeat-runs`}>心跳</NavLink>
          <NavLink className="local-nav-primary" to={`/orgs/${orgId}/goals`}>目标</NavLink>
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
                {project.name}
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
