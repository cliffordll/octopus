from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
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


def _add_work_product_declaration_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--work-product", action="append", dest="work_products")
    parser.add_argument(
        "--primary-work-product", action="append", dest="primary_work_products"
    )


def _work_product_declarations(args: argparse.Namespace) -> list[dict[str, Any]]:
    declarations: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in args.work_products or []:
        if path not in seen:
            declarations.append({"path": path, "isPrimary": False})
            seen.add(path)
    for path in args.primary_work_products or []:
        for item in declarations:
            if item["path"] == path:
                item["isPrimary"] = True
                break
        else:
            declarations.append({"path": path, "isPrimary": True})
    return declarations


def _add_work_product_declarations(
    payload: dict[str, Any], args: argparse.Namespace
) -> dict[str, Any]:
    declarations = _work_product_declarations(args)
    if declarations:
        payload["workProductDeclarations"] = declarations
    return payload


def configure(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("issue", help="Manage issues")
    actions = parser.add_subparsers(dest="issue_action", required=True)

    list_parser = actions.add_parser("list", help="List issues")
    list_parser.add_argument("--org-id", required=True)
    list_parser.add_argument("--status", choices=STATUSES)
    list_parser.add_argument("--assignee-agent-id")
    list_parser.add_argument("--project-id")
    list_parser.add_argument("--goal-id")
    list_parser.add_argument("--parent-id")
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

    checkout_parser = actions.add_parser(
        "checkout", help="Checkout an issue for an agent"
    )
    checkout_parser.add_argument("issue_id")
    checkout_parser.add_argument("--agent-id")
    checkout_parser.add_argument(
        "--expected-status", action="append", dest="expected_statuses"
    )
    checkout_parser.set_defaults(handler=checkout_issue)

    heartbeat_context_parser = actions.add_parser(
        "heartbeat-context", help="Get issue heartbeat context"
    )
    heartbeat_context_parser.add_argument("issue_id")
    heartbeat_context_parser.set_defaults(handler=get_issue_heartbeat_context)

    children_parser = actions.add_parser(
        "children", help="List child issues and outputs"
    )
    children_parser.add_argument("issue_id")
    children_parser.add_argument("--include-work-products", action="store_true")
    children_parser.set_defaults(handler=list_issue_children)

    create_children_parser = actions.add_parser(
        "create-children",
        help="Atomically create the complete delegated child issue set",
    )
    create_children_parser.add_argument("issue_id")
    children_source = create_children_parser.add_mutually_exclusive_group(required=True)
    children_source.add_argument(
        "--children-json",
        help="JSON array of child issue objects",
    )
    children_source.add_argument(
        "--children-file",
        type=Path,
        help="UTF-8 JSON file containing the child issue array",
    )
    create_children_parser.add_argument(
        "--parent-output-required",
        action="store_true",
        help=(
            "Require the parent to produce and declare its own final output; "
            "by default child outputs are final"
        ),
    )
    create_children_parser.add_argument(
        "--closeout-policy-file",
        type=Path,
        help="UTF-8 JSON file containing an advanced closeout policy object",
    )
    create_children_parser.set_defaults(handler=create_issue_children)

    retry_child_parser = actions.add_parser(
        "retry-child", help="Retry a blocked child issue"
    )
    retry_child_parser.add_argument("issue_id")
    retry_child_parser.set_defaults(handler=retry_child_issue)

    replace_child_parser = actions.add_parser(
        "replace-child", help="Create a replacement child issue"
    )
    replace_child_parser.add_argument("issue_id")
    replace_child_parser.add_argument("--title")
    replace_child_parser.add_argument("--description")
    replace_child_parser.add_argument("--assignee-agent-id")
    replace_child_parser.set_defaults(handler=replace_child_issue)

    accept_incomplete_parser = actions.add_parser(
        "accept-incomplete", help="Allow incomplete parent delivery"
    )
    accept_incomplete_parser.add_argument("issue_id")
    accept_incomplete_parser.add_argument(
        "--child", action="append", dest="child_issue_ids"
    )
    accept_incomplete_parser.add_argument(
        "--child-issue-id", action="append", dest="child_issue_ids"
    )
    accept_incomplete_parser.add_argument("--reason", required=True)
    accept_incomplete_parser.set_defaults(handler=accept_incomplete_issue)

    create_parser = actions.add_parser("create", help="Create an issue")
    create_parser.add_argument("--org-id", required=True)
    create_parser.add_argument("--title", required=True)
    create_parser.add_argument("--description")
    create_parser.add_argument("--body")
    create_parser.add_argument("--status", choices=STATUSES)
    create_parser.add_argument("--priority", choices=PRIORITIES)
    create_parser.add_argument("--project-id")
    create_parser.add_argument("--goal-id")
    create_parser.add_argument("--parent-id")
    create_parser.add_argument("--assignee-agent-id")
    create_parser.add_argument("--assignee-user-id")
    create_parser.add_argument("--reviewer-agent-id")
    create_parser.add_argument("--reviewer-user-id")
    create_parser.add_argument("--created-by-agent-id")
    create_parser.add_argument("--created-by-user-id")
    create_parser.add_argument("--origin-kind")
    create_parser.add_argument("--origin-id")
    create_parser.add_argument("--request-depth", type=int)
    create_parser.set_defaults(handler=create_issue)

    update_parser = actions.add_parser("update", help="Update an issue")
    update_parser.add_argument("issue_id")
    update_parser.add_argument("--org-id")
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
    comment_add.add_argument("--org-id")
    comment_add.add_argument("--body", required=True)
    comment_add.add_argument("--request-id")
    _add_work_product_declaration_args(comment_add)
    comment_add.set_defaults(handler=add_comment)

    review_parser = actions.add_parser("review", help="Record an issue review decision")
    review_parser.add_argument("issue_id")
    review_parser.add_argument("--decision", required=True, choices=DECISIONS)
    review_parser.add_argument("--comment")
    review_parser.add_argument("--note")
    review_parser.set_defaults(handler=review_issue)

    done_parser = actions.add_parser("done", help="Mark an issue done")
    done_parser.add_argument("issue_id")
    done_comment = done_parser.add_mutually_exclusive_group(required=True)
    done_comment.add_argument("--comment")
    done_comment.add_argument(
        "--comment-file",
        type=Path,
        help="UTF-8 file containing the completion comment",
    )
    _add_work_product_declaration_args(done_parser)
    done_parser.set_defaults(handler=done_issue)

    block_parser = actions.add_parser("block", help="Mark an issue blocked")
    block_parser.add_argument("issue_id")
    block_parser.add_argument("--comment", required=True)
    _add_work_product_declaration_args(block_parser)
    block_parser.set_defaults(handler=block_issue)

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
            "parentId": args.parent_id,
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
    return client.request("GET", f"/api/issues/{args.issue_id}/runs")


def checkout_issue(args: argparse.Namespace, client: ApiClient) -> Any:
    agent_id = args.agent_id or os.environ.get("OCTOPUS_AGENT_ID")
    if not agent_id:
        raise ValueError("--agent-id is required when OCTOPUS_AGENT_ID is not set.")
    expected_statuses = args.expected_statuses or ["todo", "in_progress"]
    return client.request(
        "POST",
        f"/api/issues/{args.issue_id}/checkout",
        json={
            "agentId": agent_id,
            "expectedStatuses": expected_statuses,
        },
    )


def get_issue_heartbeat_context(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", f"/api/issues/{args.issue_id}/heartbeat-context")


def list_issue_children(args: argparse.Namespace, client: ApiClient) -> Any:
    params = {"includeWorkProducts": "true"} if args.include_work_products else None
    return client.request("GET", f"/api/issues/{args.issue_id}/children", params=params)


def create_issue_children(args: argparse.Namespace, client: ApiClient) -> Any:
    source = "--children-json"
    raw_children = args.children_json
    if args.children_file is not None:
        source = f"--children-file {args.children_file}"
        try:
            raw_children = args.children_file.read_text(encoding="utf-8-sig")
        except OSError as exc:
            raise ValueError(f"Unable to read {source}: {exc}") from exc
    try:
        children = json.loads(raw_children)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{source} must contain valid JSON") from exc
    if not isinstance(children, list) or not children:
        raise ValueError(f"{source} must contain a non-empty JSON array")
    if args.closeout_policy_file is not None and args.parent_output_required:
        raise ValueError(
            "--closeout-policy-file cannot be combined with --parent-output-required"
        )
    closeout_policy: object = {"version": 1, "mode": "child_outputs_are_final"}
    if args.parent_output_required:
        closeout_policy = {
            "version": 1,
            "mode": "parent_output_required",
            "requirements": {
                "minimumOutputs": 1,
                "primaryOutputRequired": True,
            },
        }
    elif args.closeout_policy_file is not None:
        try:
            raw_policy = args.closeout_policy_file.read_text(encoding="utf-8-sig")
        except OSError as exc:
            raise ValueError(
                f"Unable to read --closeout-policy-file "
                f"{args.closeout_policy_file}: {exc}"
            ) from exc
        try:
            closeout_policy = json.loads(raw_policy)
        except json.JSONDecodeError as exc:
            raise ValueError("--closeout-policy-file must contain valid JSON") from exc
        if not isinstance(closeout_policy, dict):
            raise ValueError("--closeout-policy-file must contain a JSON object")
    return client.request(
        "POST",
        f"/api/issues/{args.issue_id}/children/batch",
        json={
            "children": children,
            "closeoutPolicy": closeout_policy,
        },
    )


def retry_child_issue(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("POST", f"/api/issues/{args.issue_id}/retry-child", json={})


def replace_child_issue(args: argparse.Namespace, client: ApiClient) -> Any:
    payload = {
        key: value
        for key, value in {
            "title": args.title,
            "description": args.description,
            "assigneeAgentId": args.assignee_agent_id,
        }.items()
        if value is not None
    }
    return client.request(
        "POST", f"/api/issues/{args.issue_id}/replace-child", json=payload
    )


def accept_incomplete_issue(args: argparse.Namespace, client: ApiClient) -> Any:
    payload: dict[str, Any] = {"reason": args.reason}
    if args.child_issue_ids:
        payload["childIssueIds"] = args.child_issue_ids
    return client.request(
        "POST",
        f"/api/issues/{args.issue_id}/accept-incomplete",
        json=payload,
    )


def create_issue(args: argparse.Namespace, client: ApiClient) -> Any:
    payload = {
        key: value
        for key, value in {
            "title": args.title,
            "description": args.description
            if args.description is not None
            else args.body,
            "status": args.status,
            "priority": args.priority,
            "projectId": args.project_id,
            "goalId": args.goal_id,
            "parentId": args.parent_id,
            "assigneeAgentId": args.assignee_agent_id,
            "assigneeUserId": args.assignee_user_id,
            "reviewerAgentId": args.reviewer_agent_id,
            "reviewerUserId": args.reviewer_user_id,
            "createdByAgentId": args.created_by_agent_id,
            "createdByUserId": args.created_by_user_id,
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
    request_id = args.request_id
    if request_id is None:
        run_id = os.environ.get("OCTOPUS_RUN_ID", "").strip()
        if run_id:
            digest = hashlib.sha256(
                f"{run_id}\0{args.issue_id}\0{args.body}".encode()
            ).hexdigest()
            request_id = f"run-comment:{digest}"
    payload = _add_work_product_declarations(
        {
            "body": args.body,
            **({"requestId": request_id} if request_id else {}),
        },
        args,
    )
    return client.request("POST", f"/api/issues/{args.issue_id}/comments", json=payload)


def review_issue(args: argparse.Namespace, client: ApiClient) -> Any:
    payload: dict[str, str] = {"decision": args.decision}
    note = args.comment if args.comment is not None else args.note
    if note is not None:
        payload["note"] = note
    return client.request(
        "POST", f"/api/issues/{args.issue_id}/review-decision", json=payload
    )


def done_issue(args: argparse.Namespace, client: ApiClient) -> Any:
    comment = args.comment
    if args.comment_file is not None:
        try:
            comment = args.comment_file.read_text(encoding="utf-8-sig")
        except OSError as exc:
            raise ValueError(
                f"Unable to read --comment-file {args.comment_file}: {exc}"
            ) from exc
    assert comment is not None
    payload = _add_work_product_declarations(
        {"status": "done", "comment": comment}, args
    )
    return client.request(
        "PATCH",
        f"/api/issues/{args.issue_id}",
        json=payload,
    )


def block_issue(args: argparse.Namespace, client: ApiClient) -> Any:
    payload = _add_work_product_declarations(
        {"status": "blocked", "comment": args.comment}, args
    )
    return client.request(
        "PATCH",
        f"/api/issues/{args.issue_id}",
        json=payload,
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
