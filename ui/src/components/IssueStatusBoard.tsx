import { Link } from "react-router-dom";
import type { Agent, IssueListItem, IssueStatus, ProjectDetail } from "../api/types";
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

function issueOwner(issue: IssueListItem, agentNameById: Map<string, string>): string {
  if (issue.assigneeAgentId) return agentNameById.get(issue.assigneeAgentId) ?? issue.assigneeAgentId;
  if (issue.assigneeUserId) return issue.assigneeUserId;
  return "未分配";
}

function issueProject(issue: IssueListItem, projectNameById: Map<string, string>): string {
  if (!issue.projectId) return "未关联";
  return projectNameById.get(issue.projectId) ?? issue.projectId;
}

export function IssueStatusBoard({
  agents = [],
  issues,
  orgId,
  projects = [],
  showProject = true,
}: {
  agents?: Agent[];
  issues: IssueListItem[];
  orgId: string;
  projects?: Array<Pick<ProjectDetail, "id" | "name">>;
  showProject?: boolean;
}) {
  const groupedIssues = issuesByStatus(issues);
  const activeIssueCount = issues.filter((issue) => !["done", "cancelled"].includes(issue.status)).length;
  const agentNameById = new Map(agents.map((agent) => [agent.id, agent.name]));
  const projectNameById = new Map(projects.map((project) => [project.id, project.name]));

  return (
    <>
      <div className="project-issue-status-summary">
        <div className="summary-metric"><span>总数</span><strong>{issues.length}</strong></div>
        <div className="summary-metric"><span>活跃</span><strong>{activeIssueCount}</strong></div>
        <div className="summary-metric"><span>阻塞</span><strong>{groupedIssues.blocked.length}</strong></div>
        <div className="summary-metric"><span>已完成</span><strong>{groupedIssues.done.length}</strong></div>
      </div>
      <div className="project-issue-status-groups">
        {ISSUE_STATUSES.map((issueStatus) => (
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
              <div className="project-issue-status-list">
                {groupedIssues[issueStatus].map((issue) => (
                  <Link
                    aria-label={issue.title}
                    className="project-issue-status-row"
                    key={issue.id}
                    to={`/orgs/${orgId}/issues/${issue.id}`}
                  >
                    <div className="project-issue-card-topline">
                      <span className="identifier">{issue.identifier ?? "-"}</span>
                      <Badge>阶段：{statusLabel(issue.status)}</Badge>
                      <Badge>优先级：{priorityLabel(issue.priority)}</Badge>
                    </div>
                    <span className="project-issue-title">{issue.title}</span>
                    <dl className="project-issue-card-meta">
                      <div><dt>创建时间</dt><dd>{issueCreatedAt(issue)}</dd></div>
                      <div><dt>归属</dt><dd>{issueOwner(issue, agentNameById)}</dd></div>
                      {showProject && <div><dt>项目</dt><dd>{issueProject(issue, projectNameById)}</dd></div>}
                    </dl>
                    <span className="project-issue-card-action">查看详情 / 执行输出</span>
                  </Link>
                ))}
              </div>
            )}
          </section>
        ))}
      </div>
    </>
  );
}
