from __future__ import annotations

import argparse
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
    list_parser.set_defaults(handler=list_issues)

    get_parser = actions.add_parser("get", help="Get issue details")
    get_parser.add_argument("issue_id")
    get_parser.set_defaults(handler=get_issue)

    create_parser = actions.add_parser("create", help="Create an issue")
    create_parser.add_argument("--org-id", required=True)
    create_parser.add_argument("--title", required=True)
    create_parser.add_argument("--description")
    create_parser.add_argument("--status", choices=STATUSES)
    create_parser.add_argument("--priority", choices=PRIORITIES)
    create_parser.set_defaults(handler=create_issue)

    update_parser = actions.add_parser("update", help="Update an issue")
    update_parser.add_argument("issue_id")
    update_parser.add_argument("--title")
    update_parser.add_argument("--description")
    update_parser.add_argument("--status", choices=STATUSES)
    update_parser.add_argument("--priority", choices=PRIORITIES)
    update_parser.set_defaults(handler=update_issue)

    comment_list = actions.add_parser("comment-list", help="List issue comments")
    comment_list.add_argument("issue_id")
    comment_list.set_defaults(handler=list_comments)

    comment_add = actions.add_parser("comment-add", help="Add an issue comment")
    comment_add.add_argument("issue_id")
    comment_add.add_argument("--body", required=True)
    comment_add.set_defaults(handler=add_comment)

    review_parser = actions.add_parser("review", help="Record an issue review decision")
    review_parser.add_argument("issue_id")
    review_parser.add_argument("--decision", required=True, choices=DECISIONS)
    review_parser.add_argument("--note")
    review_parser.set_defaults(handler=review_issue)


def list_issues(args: argparse.Namespace, client: ApiClient) -> Any:
    params = {
        key: value
        for key, value in {
            "status": args.status,
            "assigneeAgentId": args.assignee_agent_id,
        }.items()
        if value is not None
    }
    return client.request("GET", f"/api/orgs/{args.org_id}/issues", params=params)


def get_issue(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", f"/api/issues/{args.issue_id}")


def create_issue(args: argparse.Namespace, client: ApiClient) -> Any:
    payload = {
        key: value
        for key, value in {
            "title": args.title,
            "description": args.description,
            "status": args.status,
            "priority": args.priority,
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
