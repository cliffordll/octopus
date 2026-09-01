import type { CSSProperties } from "react";
import { Link } from "react-router-dom";
import type { Agent, IssueListItem, IssueWorkProduct, WorkspaceFileTreeNode } from "../api/types";
import { formatDateTime } from "../utils/display";
import { Badge } from "./Badge";
import { FileContextBrowser, type FileContextColumn } from "./FileContextBrowser";

function normalizePath(value: string): string {
  return value.replaceAll("\\", "/").replace(/^\.\//, "").replace(/^\/+|\/+$/g, "");
}

function compactTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("zh-CN", { day: "2-digit", hour: "2-digit", hour12: false, minute: "2-digit", month: "2-digit" }).format(date);
}

function fileSize(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${Math.round(size / 102.4) / 10} KB`;
  return `${Math.round(size / 1024 / 102.4) / 10} MB`;
}

function productType(type: string): string {
  const labels: Record<string, string> = { artifact: "文件产物", commit: "代码提交", document: "文档", preview: "预览", report: "报告" };
  return labels[type] ?? type;
}

function countFiles(nodes: WorkspaceFileTreeNode[]): number {
  return nodes.reduce((count, node) => count + (node.type === "file" ? 1 : countFiles(node.children ?? [])), 0);
}

export function ProjectWorkspaceExplorer({
  agents,
  issues,
  nodes,
  orgId,
  productsByPath,
}: {
  agents: Agent[];
  issues: Map<string, IssueListItem>;
  nodes: WorkspaceFileTreeNode[];
  orgId: string;
  productsByPath: Map<string, IssueWorkProduct[]>;
}) {
  const agentNames = new Map(agents.map((agent) => [agent.id, agent.name]));
  const productsFor = (node: WorkspaceFileTreeNode) => node.type === "file" ? productsByPath.get(normalizePath(node.path)) ?? [] : [];
  const productFor = (node: WorkspaceFileTreeNode) => productsFor(node)[0];
  const issueFor = (node: WorkspaceFileTreeNode) => {
    const product = productFor(node);
    return product ? issues.get(product.issueId) : undefined;
  };
  const assigneeFor = (node: WorkspaceFileTreeNode) => {
    const issue = issueFor(node);
    if (issue?.assigneeAgentId) return agentNames.get(issue.assigneeAgentId) ?? issue.assigneeAgentId;
    if (issue?.assigneeUserId) return issue.assigneeUserId;
    return issue ? "未分配" : "";
  };
  const parentFor = (node: WorkspaceFileTreeNode) => {
    const parentId = issueFor(node)?.parentId;
    if (!parentId) return "";
    const parent = issues.get(parentId);
    return parent ? `${parent.identifier ?? ""} ${parent.title}`.trim() : parentId.slice(0, 8);
  };
  const taskFor = (node: WorkspaceFileTreeNode) => {
    const products = productsFor(node);
    const issue = issueFor(node);
    const label = issue ? `${issue.identifier ?? ""} ${issue.title}`.trim() : products.length > 0 ? "产物" : "";
    return `${label}${products.length > 1 ? ` +${products.length - 1}` : ""}`;
  };
  const textCell = (value: string, title?: string) => <span className="project-workspace-context-cell" title={title}>{value || "—"}</span>;
  const fileContextCell = (node: WorkspaceFileTreeNode, value: string, title?: string) => node.type === "file" ? textCell(value, title) : null;
  const issueCell = (node: WorkspaceFileTreeNode, issue: IssueListItem | undefined, extraCount = 0) => node.type === "file" ? (
    <span className="project-workspace-context-cell project-workspace-issue-cell" title={issue ? `${issue.identifier ?? ""} ${issue.title}`.trim() : undefined}>
      {issue?.identifier && <span className="project-workspace-issue-id">{issue.identifier}{extraCount > 0 ? ` +${extraCount}` : ""}</span>}
      <span className="project-workspace-issue-title">{issue?.title ?? issue?.identifier ?? "—"}</span>
    </span>
  ) : null;
  const hasParentTask = (items: WorkspaceFileTreeNode[]): boolean => items.some((node) => (
    Boolean(issueFor(node)?.parentId) || hasParentTask(node.children ?? [])
  ));
  const columns: Array<FileContextColumn<WorkspaceFileTreeNode>> = [
    {
      key: "name",
      label: "文件名",
      priority: 0,
      render: (node, depth) => (
        <span className="project-workspace-name-cell" style={{ "--depth": depth } as CSSProperties}>
          <span className={`project-workspace-node-icon ${node.type}`} aria-hidden="true">{node.type === "directory" ? "D" : "F"}</span>
          <span>{node.name}</span>
        </span>
      ),
      sortValue: (node) => node.name,
      width: "minmax(190px, 1fr)",
    },
    { key: "modifiedAt", label: "更新时间", priority: 3, render: (node) => fileContextCell(node, compactTime(node.modifiedAt)), sortValue: (node) => node.modifiedAt ?? "", width: "108px" },
    { key: "task", label: "任务编号 标题", priority: 0, render: (node) => issueCell(node, issueFor(node), Math.max(0, productsFor(node).length - 1)), sortValue: taskFor, width: "150px" },
    { key: "assignee", label: "执行者", priority: 1, render: (node) => fileContextCell(node, assigneeFor(node)), sortValue: assigneeFor, width: "100px" },
  ];
  if (hasParentTask(nodes)) columns.push({ key: "parent", label: "父任务", priority: 2, render: (node) => {
      const parentId = issueFor(node)?.parentId;
      return parentId ? issueCell(node, issues.get(parentId)) : fileContextCell(node, "");
    }, sortValue: parentFor, width: "130px" });

  return (
    <FileContextBrowser
      actions={(selected) => {
        const issue = selected ? issueFor(selected) : undefined;
        return issue ? <Link className="button secondary small-button" to={`/orgs/${orgId}/issues/${issue.id}`}>查看任务</Link> : undefined;
      }}
      className="project-workspace-explorer"
      columns={columns}
      count={countFiles(nodes)}
      detail={(selected) => {
        if (!selected) return <p className="muted">从左侧选择文件查看详情。</p>;
        const product = productFor(selected);
        const issue = issueFor(selected);
        if (product?.contentPath && product.contentType?.startsWith("image/")) {
          return <img className="project-workspace-content-image" alt={product.title || selected.name} src={product.contentPath} />;
        }
        if (product?.contentPath) {
          return <iframe className="project-workspace-content-frame" src={product.contentPath} title={`${product.title || selected.name} 内容`} />;
        }
        return (
          <div className="project-workspace-file-detail">
            <p className="project-workspace-file-path">{selected.path}</p>
            {!product && <p className="muted">该文件尚未登记为任务产物，当前只能查看文件详情。</p>}
            <dl>
              <div><dt>大小</dt><dd>{typeof selected.size === "number" ? fileSize(selected.size) : "—"}</dd></div>
              <div><dt>修改时间</dt><dd>{formatDateTime(selected.modifiedAt)}</dd></div>
              {product && issue && <>
                <div><dt>关联任务</dt><dd><Link to={`/orgs/${orgId}/issues/${issue.id}`}>{issue.identifier ? `${issue.identifier} · ` : ""}{issue.title}</Link></dd></div>
                <div><dt>执行者</dt><dd>{assigneeFor(selected) || "未分配"}</dd></div>
                <div><dt>父任务</dt><dd>{issue.parentId && issues.get(issue.parentId) ? `${issues.get(issue.parentId)!.identifier ?? issue.parentId.slice(0, 8)} · ${issues.get(issue.parentId)!.title}` : parentFor(selected) || "—"}</dd></div>
                <div><dt>产物</dt><dd>{product.title || product.summary || "—"}</dd></div>
                <div><dt>类型</dt><dd><Badge>{productType(product.type)}</Badge></dd></div>
                <div><dt>状态</dt><dd><Badge>{product.status}</Badge></dd></div>
              </>}
            </dl>
          </div>
        );
      }}
      detailStatus={(selected) => selected ? `${issueFor(selected)?.identifier ?? "未登记"} · ${assigneeFor(selected) || "未分配"} · 只读` : undefined}
      detailTitle={(selected) => selected?.name ?? "未选择文件"}
      getChildren={(node) => node.children}
      getId={(node) => node.path}
      isSelectable={(node) => node.type === "file"}
      nodes={nodes}
      rowLabel={(node) => node.name}
      rowTitle={(node) => node.path}
      showToolbar={false}
      sortGroup={(node) => node.type === "directory" ? "0" : "1"}
      storageKey="project-workspace-explorer-width"
      title="文件与任务"
      withChildren={(node, children) => ({ ...node, children })}
    />
  );
}
