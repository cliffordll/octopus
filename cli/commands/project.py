from __future__ import annotations

import argparse
import json
from typing import Any

from ..client import ApiClient

STATUSES = ("backlog", "planned", "in_progress", "completed", "cancelled")
RESOURCE_ROLES = ("working_set", "reference", "tracking", "deliverable", "background")


def configure(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("project", help="Manage projects")
    actions = parser.add_subparsers(dest="project_action", required=True)

    list_parser = actions.add_parser("list", help="List projects")
    list_parser.add_argument("--org-id", required=True)
    list_parser.set_defaults(handler=list_projects)

    get_parser = actions.add_parser("get", help="Get project details")
    get_parser.add_argument("project_id")
    get_parser.set_defaults(handler=get_project)

    create_parser = actions.add_parser("create", help="Create a project")
    create_parser.add_argument("--org-id", required=True)
    create_parser.add_argument("--name", required=True)
    create_parser.add_argument("--description")
    create_parser.add_argument("--status", choices=STATUSES)
    create_parser.add_argument("--goal-id", action="append", dest="goal_ids")
    create_parser.add_argument("--lead-agent-id")
    create_parser.add_argument("--target-date")
    create_parser.add_argument("--execution-workspace-policy")
    create_parser.set_defaults(handler=create_project)

    update_parser = actions.add_parser("update", help="Update a project")
    update_parser.add_argument("project_id")
    update_parser.add_argument("--name")
    update_parser.add_argument("--description")
    update_parser.add_argument("--status", choices=STATUSES)
    update_parser.add_argument("--goal-id", action="append", dest="goal_ids")
    update_parser.add_argument("--lead-agent-id")
    update_parser.add_argument("--target-date")
    update_parser.add_argument("--execution-workspace-policy")
    update_parser.set_defaults(handler=update_project)

    delete_parser = actions.add_parser("delete", help="Delete a project")
    delete_parser.add_argument("project_id")
    delete_parser.set_defaults(handler=delete_project)

    resources_parser = actions.add_parser(
        "resource-list", help="List project resources"
    )
    resources_parser.add_argument("project_id")
    resources_parser.set_defaults(handler=list_resources)

    add_parser = actions.add_parser(
        "resource-add", help="Attach a resource to a project"
    )
    add_parser.add_argument("project_id")
    add_parser.add_argument("--resource-id", required=True)
    add_parser.add_argument("--role", choices=RESOURCE_ROLES)
    add_parser.add_argument("--note")
    add_parser.add_argument("--sort-order", type=int)
    add_parser.set_defaults(handler=add_resource)

    update_resource_parser = actions.add_parser(
        "resource-update", help="Update a project resource"
    )
    update_resource_parser.add_argument("project_id")
    update_resource_parser.add_argument("attachment_id")
    update_resource_parser.add_argument("--role", choices=RESOURCE_ROLES)
    update_resource_parser.add_argument("--note")
    update_resource_parser.add_argument("--sort-order", type=int)
    update_resource_parser.set_defaults(handler=update_resource)

    remove_parser = actions.add_parser(
        "resource-remove", help="Remove a project resource"
    )
    remove_parser.add_argument("project_id")
    remove_parser.add_argument("attachment_id")
    remove_parser.set_defaults(handler=remove_resource)


def list_projects(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", f"/api/orgs/{args.org_id}/projects")


def get_project(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", f"/api/projects/{args.project_id}")


def create_project(args: argparse.Namespace, client: ApiClient) -> Any:
    payload = {
        key: value
        for key, value in {
            "name": args.name,
            "description": args.description,
            "status": args.status,
            "goalIds": args.goal_ids,
            "leadAgentId": args.lead_agent_id,
            "targetDate": args.target_date,
        }.items()
        if value is not None
    }
    if args.execution_workspace_policy is not None:
        payload["executionWorkspacePolicy"] = _json_object(
            args.execution_workspace_policy
        )
    return client.request("POST", f"/api/orgs/{args.org_id}/projects", json=payload)


def update_project(args: argparse.Namespace, client: ApiClient) -> Any:
    payload = {
        key: value
        for key, value in {
            "name": args.name,
            "description": args.description,
            "status": args.status,
            "goalIds": args.goal_ids,
            "leadAgentId": args.lead_agent_id,
            "targetDate": args.target_date,
        }.items()
        if value is not None
    }
    if args.execution_workspace_policy is not None:
        payload["executionWorkspacePolicy"] = _json_object(
            args.execution_workspace_policy
        )
    if not payload:
        raise ValueError("At least one update field is required.")
    return client.request("PATCH", f"/api/projects/{args.project_id}", json=payload)


def delete_project(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("DELETE", f"/api/projects/{args.project_id}")


def list_resources(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", f"/api/projects/{args.project_id}/resources")


def add_resource(args: argparse.Namespace, client: ApiClient) -> Any:
    payload = {
        key: value
        for key, value in {
            "resourceId": args.resource_id,
            "role": args.role,
            "note": args.note,
            "sortOrder": args.sort_order,
        }.items()
        if value is not None
    }
    return client.request(
        "POST", f"/api/projects/{args.project_id}/resources", json=payload
    )


def update_resource(args: argparse.Namespace, client: ApiClient) -> Any:
    payload = {
        key: value
        for key, value in {
            "role": args.role,
            "note": args.note,
            "sortOrder": args.sort_order,
        }.items()
        if value is not None
    }
    if not payload:
        raise ValueError("At least one update field is required.")
    return client.request(
        "PATCH",
        f"/api/projects/{args.project_id}/resources/{args.attachment_id}",
        json=payload,
    )


def remove_resource(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request(
        "DELETE", f"/api/projects/{args.project_id}/resources/{args.attachment_id}"
    )


def _json_object(value: str) -> dict[str, Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("Value must be a JSON object.")
    return parsed
