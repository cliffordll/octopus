import { useEffect, useState, type CSSProperties, type ReactNode } from "react";
import { FilePreview } from "./FilePreview";
import { ResizableSplitPane } from "./ResizableSplitPane";

export type FileContextColumn<T extends object> = {
  key: string;
  label: string;
  priority?: 0 | 1 | 2 | 3;
  render: (item: T, depth: number) => ReactNode;
  sortValue: (item: T) => string;
  width: string;
};

type Direction = "asc" | "desc";

function flatten<T extends object>(nodes: T[], getChildren: (item: T) => T[] | undefined, depth = 0): Array<{ depth: number; item: T }> {
  return nodes.flatMap((item) => [
    { depth, item },
    ...flatten(getChildren(item) ?? [], getChildren, depth + 1),
  ]);
}

export function FileContextBrowser<T extends object>({
  actions,
  className = "",
  columns,
  count,
  defaultLeftWidth = 720,
  detail,
  detailStatus,
  detailTitle,
  getChildren,
  getId,
  isSelectable,
  maxLeftWidth = 900,
  minLeftWidth = 420,
  nodes,
  rowLabel,
  rowTitle,
  showToolbar = true,
  sortGroup,
  storageKey,
  title,
  withChildren,
}: {
  actions?: (selected: T | undefined) => ReactNode;
  className?: string;
  columns: Array<FileContextColumn<T>>;
  count?: ReactNode;
  defaultLeftWidth?: number;
  detail: (selected: T | undefined) => ReactNode;
  detailStatus?: (selected: T | undefined) => ReactNode;
  detailTitle: (selected: T | undefined) => ReactNode;
  getChildren: (item: T) => T[] | undefined;
  getId: (item: T) => string;
  isSelectable: (item: T) => boolean;
  maxLeftWidth?: number;
  minLeftWidth?: number;
  nodes: T[];
  rowLabel: (item: T) => string;
  rowTitle?: (item: T) => string | undefined;
  showToolbar?: boolean;
  sortGroup?: (item: T) => string;
  storageKey?: string;
  title: ReactNode;
  withChildren: (item: T, children: T[]) => T;
}) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [sortDirection, setSortDirection] = useState<Direction>("asc");
  const [sortKey, setSortKey] = useState(columns[0]?.key ?? "");
  const flatNodes = flatten(nodes, getChildren);
  const selected = flatNodes.find(({ item }) => getId(item) === selectedId)?.item;

  useEffect(() => {
    if (selectedId && flatNodes.some(({ item }) => getId(item) === selectedId && isSelectable(item))) return;
    setSelectedId(flatNodes.find(({ item }) => isSelectable(item)) ? getId(flatNodes.find(({ item }) => isSelectable(item))!.item) : null);
  }, [nodes, selectedId]);

  const activeColumn = columns.find((column) => column.key === sortKey) ?? columns[0];
  function sortTree(items: T[]): T[] {
    if (!activeColumn) return items;
    return [...items]
      .sort((left, right) => {
        const groupResult = sortGroup?.(left).localeCompare(sortGroup(right), "zh-CN", { numeric: true, sensitivity: "base" }) ?? 0;
        if (groupResult !== 0) return groupResult;
        const result = activeColumn.sortValue(left).localeCompare(activeColumn.sortValue(right), "zh-CN", { numeric: true, sensitivity: "base" });
        return sortDirection === "asc" ? result : -result;
      })
      .map((item) => {
        const children = getChildren(item);
        return children ? withChildren(item, sortTree(children)) : item;
      });
  }

  function changeSort(nextKey: string) {
    if (nextKey === sortKey) {
      setSortDirection((current) => current === "asc" ? "desc" : "asc");
      return;
    }
    setSortKey(nextKey);
    setSortDirection("asc");
  }

  const templateFor = (maxPriority: number) => columns.filter((column) => (column.priority ?? 0) <= maxPriority).map((column) => column.width).join(" ");
  const gridStyle = {
    "--file-context-columns": templateFor(3),
    "--file-context-columns-wide": templateFor(2),
    "--file-context-columns-compact": templateFor(1),
    "--file-context-columns-minimal": templateFor(0),
  } as CSSProperties;

  const table = (
    <section className="file-context-table-panel" aria-label={typeof title === "string" ? title : "文件上下文"} style={gridStyle}>
      {showToolbar && <header className="file-context-table-toolbar"><h3>{title}</h3>{count !== undefined && <span>{count}</span>}</header>}
      <div className="file-context-table-scroll">
        <div className="file-context-columns" role="row">
          {columns.map((column) => (
            <button
              aria-label={`按${column.label}排序`}
              aria-pressed={sortKey === column.key}
              className={`file-context-priority-${column.priority ?? 0}`}
              key={column.key}
              onClick={() => changeSort(column.key)}
              type="button"
            >
              {column.label} <span>{sortKey === column.key ? (sortDirection === "asc" ? "↑" : "↓") : ""}</span>
            </button>
          ))}
        </div>
        <div className="file-context-tree" role="tree">
          {flatten(sortTree(nodes), getChildren).map(({ depth, item }) => {
            const selectable = isSelectable(item);
            const content = columns.map((column) => (
              <span className={`file-context-cell file-context-priority-${column.priority ?? 0}`} key={column.key}>{column.render(item, depth)}</span>
            ));
            if (!selectable) {
              return <div aria-expanded="true" className="file-context-row branch" key={getId(item)} role="treeitem" title={rowTitle?.(item)}>{content}</div>;
            }
            return (
              <button
                aria-label={rowLabel(item)}
                className={`file-context-row leaf${selectedId === getId(item) ? " selected" : ""}`}
                key={getId(item)}
                onClick={() => setSelectedId(getId(item))}
                role="treeitem"
                title={rowTitle?.(item)}
                type="button"
              >
                {content}
              </button>
            );
          })}
        </div>
      </div>
    </section>
  );

  return (
    <ResizableSplitPane className={`file-context-browser${className ? ` ${className}` : ""}`} defaultWidth={defaultLeftWidth} maxWidth={maxLeftWidth} minWidth={minLeftWidth} storageKey={storageKey}>
      {table}
      <FilePreview actions={actions?.(selected)} className="file-context-preview" status={detailStatus?.(selected)} title={detailTitle(selected)}>
        {detail(selected)}
      </FilePreview>
    </ResizableSplitPane>
  );
}
