import { Link } from "react-router-dom";
import type { Agent, IssueListItem, IssueStatus, ProjectDetail } from "../api/types";
import type { OrganizationHierarchyMember } from "../api/access";
import { Badge } from "./Badge";
import { formatDateTime, priorityLabel, statusLabel } from "../utils/display";

const ISSUE_STATUSES: IssueStatus[] = ["backlog", "todo", "in_progress", "in_review", "done", "blocked", "cancelled"];

type IssueWithCreatedAt = IssueListItem & { createdAt?: string | null };

function issueStatusLabel(status: IssueStatus): string {
  return statusLabel(status);
}

function issuesByStatus(issues: IssueListItem[]): Record<IssueStatus, IssueListItem[]> {
  const grouped: Record<IssueStatus, IssueListItem[]> = {
    backlog: [],
    todo: [],
    in_progress: [],
    in_review: [],
    done: [],
    blocked: [],
    cancelled: [],
  };
  for (const issue of issues) {
    grouped[issue.status]?.push(issue);
  }
  return grouped;
}

function issueCreatedAt(issue: IssueListItem): string {
  return formatDateTime((issue as IssueWithCreatedAt).createdAt || issue.updatedAt);
}

function issueOwner(
  issue: IssueListItem,
  agentNameById: Map<string, string>,
  userNameById: Map<string, string>,
): string {
  if (issue.assigneeAgentId) return agentNameById.get(issue.assigneeAgentId) ?? issue.assigneeAgentId;
  if (issue.assigneeUserId) return userNameById.get(issue.assigneeUserId) ?? issue.assigneeUserId;
  return "未分配";
}

function issueProject(issue: IssueListItem, projectNameById: Map<string, string>): string {
  if (!issue.projectId) return "未关联";
  return projectNameById.get(issue.projectId) ?? issue.projectId;
}

function issueParent(issue: IssueListItem, issueById: Map<string, IssueListItem>): string {
  if (!issue.parentId) return "—";
  const parent = issueById.get(issue.parentId);
  if (!parent) return issue.parentId;
  return `${parent.identifier ?? "-"} ${parent.title}`;
}

export function IssueStatusBoard({
  agents = [],
  emptyMessage = "暂无任务。",
  issues,
  layout = "board",
  members = [],
  orgId,
  projects = [],
  showAssignee = true,
  showProject = true,
}: {
  agents?: Agent[];
  emptyMessage?: string | null;
  issues: IssueListItem[];
  layout?: "board" | "list";
  members?: OrganizationHierarchyMember[];
  orgId: string;
  projects?: Array<Pick<ProjectDetail, "id" | "name">>;
  showAssignee?: boolean;
  showProject?: boolean;
}) {
  const groupedIssues = issuesByStatus(issues);
  const visibleStatuses = ISSUE_STATUSES.filter((status) => layout === "board" || groupedIssues[status].length > 0);
  const activeIssueCount = issues.filter((issue) => !["done", "cancelled"].includes(issue.status)).length;
  const agentNameById = new Map(agents.map((agent) => [agent.id, agent.name]));
  const userNameById = new Map(
    members
      .filter((member) => member.principalType === "user")
      .map((member) => [member.principalId, member.displayName]),
  );
  const projectNameById = new Map(projects.map((project) => [project.id, project.name]));
  const issueById = new Map(issues.map((issue) => [issue.id, issue]));
  const showParent = layout === "list" && issues.some((issue) => Boolean(issue.parentId));
  const listColumnClasses = [
    showProject ? "has-project" : "",
    showParent ? "has-parent" : "",
    showAssignee ? "" : "hide-assignee",
  ].filter(Boolean).join(" ");

  return (
    <>
      <div className="project-issue-status-summary project-summary-toolbar">
        <div aria-label="任务摘要" className="project-compact-summary" role="group">
          <span className="project-summary-chip"><strong>{issues.length}</strong> 总数</span>
          <span className="project-summary-chip"><strong>{activeIssueCount}</strong> 活跃</span>
          <span className="project-summary-chip"><strong>{groupedIssues.blocked.length}</strong> 阻塞</span>
          <span className="project-summary-chip"><strong>{groupedIssues.done.length}</strong> 已完成</span>
        </div>
      </div>
      {layout === "list" && issues.length > 0 && (
        <div aria-hidden="true" className={`project-issue-list-columns ${listColumnClasses}`.trim()}>
          <span>任务编号 标题</span>
          {showProject && <span>项目</span>}
          {showParent && <span>父任务</span>}
          {showAssignee && <span>执行者</span>}
          <span>优先级</span>
          <span>更新时间</span>
        </div>
      )}
      {issues.length === 0 ? (
        emptyMessage && <p className="issues-view-empty muted">{emptyMessage}</p>
      ) : (
        <div className={`project-issue-status-groups${layout === "list" ? " project-issue-grouped-list" : ""}`}>
          {visibleStatuses.map((issueStatus) => (
            <section className="project-issue-status-group" key={issueStatus}>
              <div className="project-issue-status-heading">
                <div>
                  <span className={`status-dot status-${issueStatus}`} />
                  <h3>{issueStatusLabel(issueStatus)}</h3>
                </div>
                <Badge>{groupedIssues[issueStatus].length}</Badge>
              </div>
              {groupedIssues[issueStatus].length === 0 ? (
                <p className="muted">暂无任务。</p>
              ) : (
                <div className={`project-issue-status-list ${listColumnClasses}`.trim()}>
                  {groupedIssues[issueStatus].map((issue) => (
                  <Link
                    aria-label={issue.title}
                    className="project-issue-status-row"
                    key={issue.id}
                    to={`/orgs/${orgId}/issues/${issue.id}`}
                  >
                    {layout === "list" ? (
                      <>
                        <span className="project-issue-list-title" title={issue.title}>
                          <span className="identifier">{issue.identifier ?? "-"}</span>
                          <span className="project-issue-title">{issue.title}</span>
                        </span>
                        {showProject && (
                          <span className="project-issue-list-project" title={`项目：${issueProject(issue, projectNameById)}`}>
                            {issueProject(issue, projectNameById)}
                          </span>
                        )}
                        {showParent && (
                          <span className="project-issue-list-parent" title={`父任务：${issueParent(issue, issueById)}`}>
                            {issueParent(issue, issueById)}
                          </span>
                        )}
                        {showAssignee && (
                          <span className="project-issue-list-owner" title={`负责人：${issueOwner(issue, agentNameById, userNameById)}`}>
                            {issueOwner(issue, agentNameById, userNameById)}
                          </span>
                        )}
                        <span className="project-issue-list-priority" title="优先级">
                          <Badge>{priorityLabel(issue.priority)}</Badge>
                        </span>
                        <time className="project-issue-list-updated" dateTime={issue.updatedAt} title={`更新时间：${formatDateTime(issue.updatedAt)}`}>
                          {formatDateTime(issue.updatedAt)}
                        </time>
                      </>
                    ) : (
                      <>
                        <div className="project-issue-card-topline">
                          <span className="identifier">{issue.identifier ?? "-"}</span>
                          <Badge>阶段：{statusLabel(issue.status)}</Badge>
                          <Badge>优先级：{priorityLabel(issue.priority)}</Badge>
                        </div>
                        <span className="project-issue-title">{issue.title}</span>
                        <dl className="project-issue-card-meta">
                          <div><dt>创建时间</dt><dd>{issueCreatedAt(issue)}</dd></div>
                          <div><dt>归属</dt><dd>{issueOwner(issue, agentNameById, userNameById)}</dd></div>
                          {showProject && <div><dt>项目</dt><dd>{issueProject(issue, projectNameById)}</dd></div>}
                        </dl>
                        <span className="project-issue-card-action">查看详情 / 执行输出</span>
                      </>
                    )}
                  </Link>
                  ))}
                </div>
              )}
            </section>
          ))}
        </div>
      )}
    </>
  );
}
