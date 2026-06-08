from __future__ import annotations

import argparse
import json
from typing import Any

from ..client import ApiClient


def configure(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("activity", help="Query activity events")
    actions = parser.add_subparsers(dest="activity_action", required=True)

    list_parser = actions.add_parser("list", help="List organization activity")
    list_parser.add_argument("--org-id", required=True)
    _add_query_args(list_parser)
    list_parser.set_defaults(handler=list_org_activity)

    create_parser = actions.add_parser("create", help="Create an activity event")
    create_parser.add_argument("--org-id", required=True)
    create_parser.add_argument("--action", required=True)
    create_parser.add_argument("--entity-type", required=True)
    create_parser.add_argument("--entity-id", required=True)
    create_parser.add_argument("--actor-id", required=True)
    create_parser.add_argument("--actor-type")
    create_parser.add_argument("--actor-agent-id")
    create_parser.add_argument("--run-id")
    create_parser.add_argument("--details")
    create_parser.set_defaults(handler=create_activity)

    issue_parser = actions.add_parser("issue", help="List issue activity")
    issue_parser.add_argument("issue_id")
    _add_query_args(issue_parser)
    issue_parser.set_defaults(handler=list_issue_activity)

    issue_runs_parser = actions.add_parser("issue-runs", help="List runs linked to an issue")
    issue_runs_parser.add_argument("issue_id")
    issue_runs_parser.set_defaults(handler=list_issue_runs)

    run_issues_parser = actions.add_parser("run-issues", help="List issues linked to a run")
    run_issues_parser.add_argument("run_id")
    run_issues_parser.set_defaults(handler=list_run_issues)


def _add_query_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--entity-type")
    parser.add_argument("--entity-id")
    parser.add_argument("--actor-agent-id")
    parser.add_argument("--actor-user-id")
    parser.add_argument("--action")
    parser.add_argument("--start-time")
    parser.add_argument("--end-time")
    parser.add_argument("--limit", type=int)


def _query_params(args: argparse.Namespace) -> dict[str, str] | None:
    params: dict[str, str] = {}
    for cli_name, api_name in (
        ("entity_type", "entityType"),
        ("entity_id", "entityId"),
        ("actor_agent_id", "actorAgentId"),
        ("actor_user_id", "actorUserId"),
        ("action", "action"),
        ("start_time", "startTime"),
        ("end_time", "endTime"),
        ("limit", "limit"),
    ):
        value = getattr(args, cli_name, None)
        if value is not None:
            params[api_name] = str(value)
    return params or None


def list_org_activity(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request(
        "GET", f"/api/orgs/{args.org_id}/activity", params=_query_params(args)
    )


def create_activity(args: argparse.Namespace, client: ApiClient) -> Any:
    payload: dict[str, Any] = {
        "action": args.action,
        "entityType": args.entity_type,
        "entityId": args.entity_id,
        "actorId": args.actor_id,
    }
    if args.actor_type is not None:
        payload["actorType"] = args.actor_type
    for cli_name, api_name in (
        ("actor_agent_id", "agentId"),
        ("run_id", "runId"),
    ):
        value = getattr(args, cli_name)
        if value is not None:
            payload[api_name] = value
    if args.details is not None:
        details = json.loads(args.details)
        if not isinstance(details, dict):
            raise ValueError("--details must be a JSON object.")
        payload["details"] = details
    return client.request("POST", f"/api/orgs/{args.org_id}/activity", json=payload)


def list_issue_activity(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request(
        "GET", f"/api/issues/{args.issue_id}/activity", params=_query_params(args)
    )


def list_issue_runs(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", f"/api/issues/{args.issue_id}/runs")


def list_run_issues(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", f"/api/heartbeat-runs/{args.run_id}/issues")
