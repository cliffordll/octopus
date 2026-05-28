from __future__ import annotations

import argparse
from typing import Any

from ..client import ApiClient


def _add_policy_arguments(parser: argparse.ArgumentParser) -> None:
    approval = parser.add_mutually_exclusive_group()
    approval.add_argument(
        "--require-board-approval-for-new-agents",
        dest="require_board_approval_for_new_agents",
        action="store_true",
        default=None,
    )
    approval.add_argument(
        "--no-require-board-approval-for-new-agents",
        dest="require_board_approval_for_new_agents",
        action="store_false",
    )
    parser.add_argument("--default-chat-issue-creation-mode")


def configure(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "organization", aliases=["org"], help="Manage organizations"
    )
    actions = parser.add_subparsers(dest="organization_action", required=True)

    list_parser = actions.add_parser("list", help="List organizations")
    list_parser.set_defaults(handler=list_organizations)

    get_parser = actions.add_parser("get", help="Get an organization")
    get_parser.add_argument("org_id")
    get_parser.set_defaults(handler=get_organization)

    create_parser = actions.add_parser("create", help="Create an organization")
    create_parser.add_argument("--name", required=True)
    create_parser.add_argument("--description")
    create_parser.add_argument("--budget-monthly-cents", type=int)
    create_parser.add_argument("--brand-color")
    _add_policy_arguments(create_parser)
    create_parser.set_defaults(handler=create_organization)

    update_parser = actions.add_parser("update", help="Update an organization")
    update_parser.add_argument("org_id")
    update_parser.add_argument("--name")
    update_parser.add_argument("--description")
    update_parser.add_argument("--budget-monthly-cents", type=int)
    update_parser.add_argument("--brand-color")
    _add_policy_arguments(update_parser)
    update_parser.set_defaults(handler=update_organization)


def list_organizations(_: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", "/api/orgs")


def get_organization(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", f"/api/orgs/{args.org_id}")


def create_organization(args: argparse.Namespace, client: ApiClient) -> Any:
    payload: dict[str, object] = {"name": args.name}
    if args.description is not None:
        payload["description"] = args.description
    if args.budget_monthly_cents is not None:
        payload["budgetMonthlyCents"] = args.budget_monthly_cents
    if args.brand_color is not None:
        payload["brandColor"] = args.brand_color
    if args.require_board_approval_for_new_agents is not None:
        payload["requireBoardApprovalForNewAgents"] = (
            args.require_board_approval_for_new_agents
        )
    if args.default_chat_issue_creation_mode is not None:
        payload["defaultChatIssueCreationMode"] = args.default_chat_issue_creation_mode
    return client.request("POST", "/api/orgs", json=payload)


def update_organization(args: argparse.Namespace, client: ApiClient) -> Any:
    payload = {
        key: value
        for key, value in {
            "name": args.name,
            "description": args.description,
            "budgetMonthlyCents": args.budget_monthly_cents,
            "brandColor": args.brand_color,
            "requireBoardApprovalForNewAgents": args.require_board_approval_for_new_agents,
            "defaultChatIssueCreationMode": args.default_chat_issue_creation_mode,
        }.items()
        if value is not None
    }
    if not payload:
        raise ValueError("At least one update field is required.")
    return client.request("PATCH", f"/api/orgs/{args.org_id}", json=payload)
