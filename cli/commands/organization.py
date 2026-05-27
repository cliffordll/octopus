from __future__ import annotations

import argparse
from typing import Any

from ..client import ApiClient


def configure(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("organization", aliases=["org"], help="Manage organizations")
    actions = parser.add_subparsers(dest="organization_action", required=True)

    list_parser = actions.add_parser("list", help="List organizations")
    list_parser.set_defaults(handler=list_organizations)

    get_parser = actions.add_parser("get", help="Get an organization")
    get_parser.add_argument("org_id")
    get_parser.set_defaults(handler=get_organization)

    create_parser = actions.add_parser("create", help="Create an organization")
    create_parser.add_argument("--name", required=True)
    create_parser.add_argument("--description")
    create_parser.set_defaults(handler=create_organization)

    update_parser = actions.add_parser("update", help="Update an organization")
    update_parser.add_argument("org_id")
    update_parser.add_argument("--name")
    update_parser.add_argument("--description")
    update_parser.set_defaults(handler=update_organization)


def list_organizations(_: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", "/api/orgs")


def get_organization(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", f"/api/orgs/{args.org_id}")


def create_organization(args: argparse.Namespace, client: ApiClient) -> Any:
    payload: dict[str, object] = {"name": args.name}
    if args.description is not None:
        payload["description"] = args.description
    return client.request("POST", "/api/orgs", json=payload)


def update_organization(args: argparse.Namespace, client: ApiClient) -> Any:
    payload = {
        key: value
        for key, value in {"name": args.name, "description": args.description}.items()
        if value is not None
    }
    if not payload:
        raise ValueError("At least one update field is required.")
    return client.request("PATCH", f"/api/orgs/{args.org_id}", json=payload)
