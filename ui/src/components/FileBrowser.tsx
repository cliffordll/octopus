import type { CSSProperties, ReactNode } from "react";
import { FilePreview } from "./FilePreview";

type FileBrowserProps = {
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  fileStatus?: ReactNode;
  fileTitle: ReactNode;
  framed?: boolean;
  sidebar: ReactNode;
  sidebarCount?: ReactNode;
  sidebarTitle?: ReactNode;
  sidebarWidth?: number;
  treeTestId?: string;
  viewerTestId?: string;
};

export function FileBrowser({
  actions,
  children,
  className = "",
  fileStatus,
  fileTitle,
  framed = false,
  sidebar,
  sidebarCount,
  sidebarTitle = "文件",
  sidebarWidth = 188,
  treeTestId,
  viewerTestId,
}: FileBrowserProps) {
  return (
    <div
      className={`file-browser${framed ? " framed" : ""}${className ? ` ${className}` : ""}`}
      style={{ "--file-browser-sidebar-width": `${sidebarWidth}px` } as CSSProperties}
    >
      <aside className="file-browser-sidebar" data-testid={treeTestId}>
        <div className="file-browser-sidebar-header">
          <h3>{sidebarTitle}</h3>
          {sidebarCount !== undefined && <span>{sidebarCount}</span>}
        </div>
        <div className="file-browser-sidebar-body">{sidebar}</div>
      </aside>
      <FilePreview actions={actions} className="file-browser-viewer" status={fileStatus} testId={viewerTestId} title={fileTitle}>
        {children}
      </FilePreview>
    </div>
  );
}
