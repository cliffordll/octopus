from __future__ import annotations

import argparse
from typing import Any

from ..client import ApiClient

LEVELS = ("organization", "team", "agent", "task")
STATUSES = ("planned", "active", "achieved", "cancelled")


def configure(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("goal", help="Manage goals")
    actions = parser.add_subparsers(dest="goal_action", required=True)

    list_parser = actions.add_parser("list", help="List goals")
    list_parser.add_argument("--org-id", required=True)
    list_parser.set_defaults(handler=list_goals)

    get_parser = actions.add_parser("get", help="Get goal details")
    get_parser.add_argument("goal_id")
    get_parser.set_defaults(handler=get_goal)

    dependencies_parser = actions.add_parser(
        "dependencies", help="Get goal dependencies"
    )
    dependencies_parser.add_argument("goal_id")
    dependencies_parser.set_defaults(handler=get_dependencies)

    create_parser = actions.add_parser("create", help="Create a goal")
    create_parser.add_argument("--org-id", required=True)
    create_parser.add_argument("--title", required=True)
    create_parser.add_argument("--description")
    create_parser.add_argument("--level", choices=LEVELS)
    create_parser.add_argument("--status", choices=STATUSES)
    create_parser.add_argument("--parent-id")
    create_parser.add_argument("--owner-agent-id")
    create_parser.set_defaults(handler=create_goal)

    update_parser = actions.add_parser("update", help="Update a goal")
    update_parser.add_argument("goal_id")
    update_parser.add_argument("--title")
    update_parser.add_argument("--description")
    update_parser.add_argument("--level", choices=LEVELS)
    update_parser.add_argument("--status", choices=STATUSES)
    update_parser.add_argument("--parent-id")
    update_parser.add_argument("--owner-agent-id")
    update_parser.set_defaults(handler=update_goal)

    delete_parser = actions.add_parser("delete", help="Delete a goal")
    delete_parser.add_argument("goal_id")
    delete_parser.set_defaults(handler=delete_goal)


def list_goals(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", f"/api/orgs/{args.org_id}/goals")


def get_goal(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", f"/api/goals/{args.goal_id}")


def get_dependencies(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", f"/api/goals/{args.goal_id}/dependencies")


def create_goal(args: argparse.Namespace, client: ApiClient) -> Any:
    payload = _payload(args)
    return client.request("POST", f"/api/orgs/{args.org_id}/goals", json=payload)


def update_goal(args: argparse.Namespace, client: ApiClient) -> Any:
    payload = _payload(args)
    if not payload:
        raise ValueError("At least one update field is required.")
    return client.request("PATCH", f"/api/goals/{args.goal_id}", json=payload)


def delete_goal(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("DELETE", f"/api/goals/{args.goal_id}")


def _payload(args: argparse.Namespace) -> dict[str, Any]:
    return {
        key: value
        for key, value in {
            "title": getattr(args, "title", None),
            "description": getattr(args, "description", None),
            "level": getattr(args, "level", None),
            "status": getattr(args, "status", None),
            "parentId": getattr(args, "parent_id", None),
            "ownerAgentId": getattr(args, "owner_agent_id", None),
        }.items()
        if value is not None
    }
