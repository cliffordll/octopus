from __future__ import annotations

import argparse
import mimetypes
from pathlib import Path
from typing import Any

from ..client import ApiClient

STATUSES = (
    "backlog",
    "todo",
    "in_progress",
    "in_review",
    "done",
    "blocked",
    "cancelled",
)
PRIORITIES = ("critical", "high", "medium", "low")
DECISIONS = ("approve", "request_changes", "blocked", "needs_followup")


def configure(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("issue", help="Manage issues")
    actions = parser.add_subparsers(dest="issue_action", required=True)

    list_parser = actions.add_parser("list", help="List issues")
    list_parser.add_argument("--org-id", required=True)
    list_parser.add_argument("--status", choices=STATUSES)
    list_parser.add_argument("--assignee-agent-id")
    list_parser.add_argument("--project-id")
    list_parser.add_argument("--goal-id")
    list_parser.add_argument("--origin-kind")
    list_parser.add_argument("--origin-id")
    list_parser.set_defaults(handler=list_issues)

    get_parser = actions.add_parser("get", help="Get issue details")
    get_parser.add_argument("issue_id")
    get_parser.set_defaults(handler=get_issue)

    execute_parser = actions.add_parser(
        "execute", help="Queue execution for an assigned issue"
    )
    execute_parser.add_argument("issue_id")
    execute_parser.set_defaults(handler=execute_issue)

    runs_parser = actions.add_parser("runs", help="List heartbeat runs for an issue")
    runs_parser.add_argument("issue_id")
    runs_parser.set_defaults(handler=list_issue_runs)

    create_parser = actions.add_parser("create", help="Create an issue")
    create_parser.add_argument("--org-id", required=True)
    create_parser.add_argument("--title", required=True)
    create_parser.add_argument("--description")
    create_parser.add_argument("--status", choices=STATUSES)
    create_parser.add_argument("--priority", choices=PRIORITIES)
    create_parser.add_argument("--project-id")
    create_parser.add_argument("--goal-id")
    create_parser.add_argument("--parent-id")
    create_parser.add_argument("--assignee-agent-id")
    create_parser.add_argument("--assignee-user-id")
    create_parser.add_argument("--reviewer-agent-id")
    create_parser.add_argument("--reviewer-user-id")
    create_parser.add_argument("--origin-kind")
    create_parser.add_argument("--origin-id")
    create_parser.add_argument("--request-depth", type=int)
    create_parser.set_defaults(handler=create_issue)

    update_parser = actions.add_parser("update", help="Update an issue")
    update_parser.add_argument("issue_id")
    update_parser.add_argument("--title")
    update_parser.add_argument("--description")
    update_parser.add_argument("--status", choices=STATUSES)
    update_parser.add_argument("--priority", choices=PRIORITIES)
    update_parser.add_argument("--project-id")
    update_parser.add_argument("--goal-id")
    update_parser.add_argument("--parent-id")
    update_parser.add_argument("--assignee-agent-id")
    update_parser.add_argument("--assignee-user-id")
    update_parser.add_argument("--reviewer-agent-id")
    update_parser.add_argument("--reviewer-user-id")
    update_parser.set_defaults(handler=update_issue)

    comment_list = actions.add_parser("comment-list", help="List issue comments")
    comment_list.add_argument("issue_id")
    comment_list.set_defaults(handler=list_comments)

    comment_add = actions.add_parser(
        "comment", aliases=["comment-add"], help="Add an issue comment"
    )
    comment_add.add_argument("issue_id")
    comment_add.add_argument("--body", required=True)
    comment_add.set_defaults(handler=add_comment)

    review_parser = actions.add_parser("review", help="Record an issue review decision")
    review_parser.add_argument("issue_id")
    review_parser.add_argument("--decision", required=True, choices=DECISIONS)
    review_parser.add_argument("--note")
    review_parser.set_defaults(handler=review_issue)

    attachment_list = actions.add_parser("attachments", help="List issue attachments")
    attachment_list.add_argument("issue_id")
    attachment_list.set_defaults(handler=list_attachments)

    attachment_upload = actions.add_parser(
        "attachment-upload", help="Upload an issue attachment"
    )
    attachment_upload.add_argument("--org-id", required=True)
    attachment_upload.add_argument("issue_id")
    attachment_upload.add_argument("--file", required=True)
    attachment_upload.add_argument("--usage", default="attachment")
    attachment_upload.add_argument("--issue-comment-id")
    attachment_upload.set_defaults(handler=upload_attachment)

    attachment_delete = actions.add_parser(
        "attachment-delete", help="Delete an attachment"
    )
    attachment_delete.add_argument("attachment_id")
    attachment_delete.set_defaults(handler=delete_attachment)


def list_issues(args: argparse.Namespace, client: ApiClient) -> Any:
    params = {
        key: value
        for key, value in {
            "status": args.status,
            "assigneeAgentId": args.assignee_agent_id,
            "projectId": args.project_id,
            "goalId": args.goal_id,
            "originKind": args.origin_kind,
            "originId": args.origin_id,
        }.items()
        if value is not None
    }
    return client.request("GET", f"/api/orgs/{args.org_id}/issues", params=params)


def get_issue(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", f"/api/issues/{args.issue_id}")


def execute_issue(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("POST", f"/api/issues/{args.issue_id}/execute", json={})


def list_issue_runs(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", f"/api/issues/{args.issue_id}/heartbeat-runs")


def create_issue(args: argparse.Namespace, client: ApiClient) -> Any:
    payload = {
        key: value
        for key, value in {
            "title": args.title,
            "description": args.description,
            "status": args.status,
            "priority": args.priority,
            "projectId": args.project_id,
            "goalId": args.goal_id,
            "parentId": args.parent_id,
            "assigneeAgentId": args.assignee_agent_id,
            "assigneeUserId": args.assignee_user_id,
            "reviewerAgentId": args.reviewer_agent_id,
            "reviewerUserId": args.reviewer_user_id,
            "originKind": args.origin_kind,
            "originId": args.origin_id,
            "requestDepth": args.request_depth,
        }.items()
        if value is not None
    }
    return client.request("POST", f"/api/orgs/{args.org_id}/issues", json=payload)


def update_issue(args: argparse.Namespace, client: ApiClient) -> Any:
    payload = {
        key: value
        for key, value in {
            "title": args.title,
            "description": args.description,
            "status": args.status,
            "priority": args.priority,
            "projectId": args.project_id,
            "goalId": args.goal_id,
            "parentId": args.parent_id,
            "assigneeAgentId": args.assignee_agent_id,
            "assigneeUserId": args.assignee_user_id,
            "reviewerAgentId": args.reviewer_agent_id,
            "reviewerUserId": args.reviewer_user_id,
        }.items()
        if value is not None
    }
    if not payload:
        raise ValueError("At least one update field is required.")
    return client.request("PATCH", f"/api/issues/{args.issue_id}", json=payload)


def list_comments(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", f"/api/issues/{args.issue_id}/comments")


def add_comment(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request(
        "POST", f"/api/issues/{args.issue_id}/comments", json={"body": args.body}
    )


def review_issue(args: argparse.Namespace, client: ApiClient) -> Any:
    payload: dict[str, str] = {"decision": args.decision}
    if args.note is not None:
        payload["note"] = args.note
    return client.request(
        "POST", f"/api/issues/{args.issue_id}/review-decision", json=payload
    )


def list_attachments(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", f"/api/issues/{args.issue_id}/attachments")


def upload_attachment(args: argparse.Namespace, client: ApiClient) -> Any:
    file_path = Path(args.file)
    content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    data = {"usage": args.usage}
    if args.issue_comment_id is not None:
        data["issueCommentId"] = args.issue_comment_id
    with file_path.open("rb") as handle:
        return client.request(
            "POST",
            f"/api/orgs/{args.org_id}/issues/{args.issue_id}/attachments",
            data=data,
            files={"file": (file_path.name, handle, content_type)},
        )


def delete_attachment(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("DELETE", f"/api/attachments/{args.attachment_id}")
