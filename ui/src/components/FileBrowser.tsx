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
  sidebarActions?: ReactNode;
  sidebarCount?: ReactNode;
  sidebarLabel?: string;
  sidebarTitle?: ReactNode;
  sidebarWidth?: number;
  treeTestId?: string;
  viewerLabel?: string;
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
  sidebarActions,
  sidebarCount,
  sidebarLabel,
  sidebarTitle = "文件",
  sidebarWidth = 188,
  treeTestId,
  viewerLabel,
  viewerTestId,
}: FileBrowserProps) {
  return (
    <div
      className={`file-browser${framed ? " framed" : ""}${className ? ` ${className}` : ""}`}
      style={{ "--file-browser-sidebar-width": `${sidebarWidth}px` } as CSSProperties}
    >
      <aside aria-label={sidebarLabel} className="file-browser-sidebar" data-testid={treeTestId}>
        <div className="file-browser-sidebar-header">
          <div className="file-browser-sidebar-heading">
            <h3>{sidebarTitle}</h3>
            {sidebarCount !== undefined && <span>{sidebarCount}</span>}
          </div>
          {sidebarActions && <div className="file-browser-sidebar-actions">{sidebarActions}</div>}
        </div>
        <div className="file-browser-sidebar-body">{sidebar}</div>
      </aside>
      <FilePreview actions={actions} ariaLabel={viewerLabel} className="file-browser-viewer" status={fileStatus} testId={viewerTestId} title={fileTitle}>
        {children}
      </FilePreview>
    </div>
  );
}
