from __future__ import annotations

import argparse
import json
from pathlib import Path
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

    resource_list_parser = actions.add_parser(
        "resource-list", help="List organization resources"
    )
    resource_list_parser.add_argument("--org-id", required=True)
    resource_list_parser.set_defaults(handler=list_resources)
    resource_create_parser = actions.add_parser(
        "resource-create", help="Create an organization resource"
    )
    resource_create_parser.add_argument("--org-id", required=True)
    resource_create_parser.add_argument("--name", required=True)
    resource_create_parser.add_argument("--kind", required=True)
    resource_create_parser.add_argument("--locator", required=True)
    resource_create_parser.add_argument("--description")
    resource_create_parser.add_argument("--metadata")
    resource_create_parser.set_defaults(handler=create_resource)
    resource_update_parser = actions.add_parser(
        "resource-update", help="Update an organization resource"
    )
    resource_update_parser.add_argument("--org-id", required=True)
    resource_update_parser.add_argument("resource_id")
    resource_update_parser.add_argument("--name")
    resource_update_parser.add_argument("--kind")
    resource_update_parser.add_argument("--locator")
    resource_update_parser.add_argument("--description")
    resource_update_parser.add_argument("--metadata")
    resource_update_parser.set_defaults(handler=update_resource)
    resource_delete_parser = actions.add_parser(
        "resource-delete", help="Delete an organization resource"
    )
    resource_delete_parser.add_argument("--org-id", required=True)
    resource_delete_parser.add_argument("resource_id")
    resource_delete_parser.set_defaults(handler=delete_resource)

    skill_list_parser = actions.add_parser(
        "skill-list", help="List organization skills"
    )
    skill_list_parser.add_argument("--org-id", required=True)
    skill_list_parser.set_defaults(handler=list_skills)
    skill_get_parser = actions.add_parser("skill-get", help="Get an organization skill")
    skill_get_parser.add_argument("--org-id", required=True)
    skill_get_parser.add_argument("skill_id")
    skill_get_parser.set_defaults(handler=get_skill)
    skill_create_parser = actions.add_parser(
        "skill-create", help="Create an organization skill"
    )
    skill_create_parser.add_argument("--org-id", required=True)
    skill_create_parser.add_argument("--name", required=True)
    skill_create_parser.add_argument("--slug")
    skill_create_parser.add_argument("--description")
    skill_create_parser.add_argument("--markdown")
    skill_create_parser.add_argument("--markdown-file")
    skill_create_parser.set_defaults(handler=create_skill)
    skill_file_parser = actions.add_parser(
        "skill-file", help="Read an organization skill file"
    )
    skill_file_parser.add_argument("--org-id", required=True)
    skill_file_parser.add_argument("skill_id")
    skill_file_parser.add_argument("--path", default="SKILL.md")
    skill_file_parser.set_defaults(handler=read_skill_file)
    skill_file_update_parser = actions.add_parser(
        "skill-file-update", help="Update an organization skill file"
    )
    skill_file_update_parser.add_argument("--org-id", required=True)
    skill_file_update_parser.add_argument("skill_id")
    skill_file_update_parser.add_argument("--path", default="SKILL.md")
    content_source = skill_file_update_parser.add_mutually_exclusive_group(
        required=True
    )
    content_source.add_argument("--content")
    content_source.add_argument("--content-file")
    skill_file_update_parser.set_defaults(handler=update_skill_file)
    skill_status_parser = actions.add_parser(
        "skill-update-status", help="Get organization skill update status"
    )
    skill_status_parser.add_argument("--org-id", required=True)
    skill_status_parser.add_argument("skill_id")
    skill_status_parser.set_defaults(handler=get_skill_update_status)
    skill_delete_parser = actions.add_parser(
        "skill-delete", help="Delete an organization skill"
    )
    skill_delete_parser.add_argument("--org-id", required=True)
    skill_delete_parser.add_argument("skill_id")
    skill_delete_parser.set_defaults(handler=delete_skill)


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


def _json_object_or_none(value: str | None) -> dict[str, Any] | None:
    if value is None:
        return None
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("metadata must be a JSON object.")
    return parsed


def _read_text_file(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def list_resources(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", f"/api/orgs/{args.org_id}/resources")


def create_resource(args: argparse.Namespace, client: ApiClient) -> Any:
    payload: dict[str, Any] = {
        "name": args.name,
        "kind": args.kind,
        "locator": args.locator,
    }
    if args.description is not None:
        payload["description"] = args.description
    if args.metadata is not None:
        payload["metadata"] = _json_object_or_none(args.metadata)
    return client.request("POST", f"/api/orgs/{args.org_id}/resources", json=payload)


def update_resource(args: argparse.Namespace, client: ApiClient) -> Any:
    payload = {
        key: value
        for key, value in {
            "name": args.name,
            "kind": args.kind,
            "locator": args.locator,
            "description": args.description,
        }.items()
        if value is not None
    }
    if args.metadata is not None:
        payload["metadata"] = _json_object_or_none(args.metadata)
    if not payload:
        raise ValueError("At least one update field is required.")
    return client.request(
        "PATCH",
        f"/api/orgs/{args.org_id}/resources/{args.resource_id}",
        json=payload,
    )


def delete_resource(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request(
        "DELETE", f"/api/orgs/{args.org_id}/resources/{args.resource_id}"
    )


def list_skills(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", f"/api/orgs/{args.org_id}/skills")


def get_skill(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", f"/api/orgs/{args.org_id}/skills/{args.skill_id}")


def create_skill(args: argparse.Namespace, client: ApiClient) -> Any:
    markdown = args.markdown
    if args.markdown_file is not None:
        markdown = _read_text_file(args.markdown_file)
    payload = {
        key: value
        for key, value in {
            "name": args.name,
            "slug": args.slug,
            "description": args.description,
            "markdown": markdown,
        }.items()
        if value is not None
    }
    return client.request("POST", f"/api/orgs/{args.org_id}/skills", json=payload)


def read_skill_file(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request(
        "GET",
        f"/api/orgs/{args.org_id}/skills/{args.skill_id}/files",
        params={"path": args.path},
    )


def update_skill_file(args: argparse.Namespace, client: ApiClient) -> Any:
    content = args.content
    if args.content_file is not None:
        content = _read_text_file(args.content_file)
    return client.request(
        "PATCH",
        f"/api/orgs/{args.org_id}/skills/{args.skill_id}/files",
        json={"path": args.path, "content": content},
    )


def get_skill_update_status(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request(
        "GET",
        f"/api/orgs/{args.org_id}/skills/{args.skill_id}/update-status",
    )


def delete_skill(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("DELETE", f"/api/orgs/{args.org_id}/skills/{args.skill_id}")
