from __future__ import annotations

import argparse
import json
from typing import Any

from ..client import ApiClient

STATUSES = ("pending", "revision_requested", "approved", "rejected", "cancelled")
TYPES = (
    "hire_agent",
    "approve_ceo_strategy",
    "budget_override_required",
    "chat_issue_creation",
    "chat_operation",
)


def configure(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("approval", help="Manage approvals")
    actions = parser.add_subparsers(dest="approval_action", required=True)

    list_parser = actions.add_parser("list", help="List approvals")
    list_parser.add_argument("--org-id", required=True)
    list_parser.add_argument("--status", choices=STATUSES)
    list_parser.set_defaults(handler=list_approvals)

    get_parser = actions.add_parser("get", help="Get approval details")
    get_parser.add_argument("approval_id")
    get_parser.set_defaults(handler=get_approval)

    create_parser = actions.add_parser("create", help="Create an approval")
    create_parser.add_argument("--org-id", required=True)
    create_parser.add_argument("--type", dest="approval_type", required=True, choices=TYPES)
    create_parser.add_argument("--payload", required=True)
    create_parser.set_defaults(handler=create_approval)

    for name, handler in (
        ("approve", approve),
        ("reject", reject),
        ("request-revision", request_revision),
    ):
        decision = actions.add_parser(name)
        decision.add_argument("approval_id")
        decision.add_argument("--note")
        decision.set_defaults(handler=handler)

    resubmit_parser = actions.add_parser("resubmit")
    resubmit_parser.add_argument("approval_id")
    resubmit_parser.add_argument("--payload")
    resubmit_parser.set_defaults(handler=resubmit)


def _json_object(value: str) -> dict[str, Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("Payload must be a JSON object.")
    return parsed


def list_approvals(args: argparse.Namespace, client: ApiClient) -> Any:
    params = {"status": args.status} if args.status else None
    return client.request("GET", f"/api/orgs/{args.org_id}/approvals", params=params)


def get_approval(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", f"/api/approvals/{args.approval_id}")


def create_approval(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request(
        "POST",
        f"/api/orgs/{args.org_id}/approvals",
        json={"type": args.approval_type, "payload": _json_object(args.payload)},
    )


def _decision(args: argparse.Namespace, client: ApiClient, action: str) -> Any:
    payload = {"decisionNote": args.note} if args.note else {}
    return client.request("POST", f"/api/approvals/{args.approval_id}/{action}", json=payload)


def approve(args: argparse.Namespace, client: ApiClient) -> Any:
    return _decision(args, client, "approve")


def reject(args: argparse.Namespace, client: ApiClient) -> Any:
    return _decision(args, client, "reject")


def request_revision(args: argparse.Namespace, client: ApiClient) -> Any:
    return _decision(args, client, "request-revision")


def resubmit(args: argparse.Namespace, client: ApiClient) -> Any:
    payload = {"payload": _json_object(args.payload)} if args.payload else {}
    return client.request("POST", f"/api/approvals/{args.approval_id}/resubmit", json=payload)
