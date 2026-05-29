from __future__ import annotations

import argparse
from typing import Any

from ..client import ApiClient


def configure(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("run-intelligence", help="Inspect observed runs")
    actions = parser.add_subparsers(dest="run_intelligence_action", required=True)
    list_parser = actions.add_parser("list")
    list_parser.add_argument("--org-id", required=True)
    list_parser.add_argument("--updated-after")
    list_parser.add_argument("--created-before")
    list_parser.add_argument("--run-id-prefix")
    list_parser.add_argument("--agent-id")
    list_parser.add_argument("--status")
    list_parser.add_argument("--runtime")
    list_parser.add_argument("--issue-id")
    list_parser.add_argument("--limit", type=int)
    list_parser.set_defaults(handler=list_runs)
    get_parser = actions.add_parser("get")
    get_parser.add_argument("run_id")
    get_parser.set_defaults(handler=get_run)
    events_parser = actions.add_parser("events")
    events_parser.add_argument("run_id")
    events_parser.set_defaults(handler=list_events)
    log_parser = actions.add_parser("log")
    log_parser.add_argument("run_id")
    log_parser.set_defaults(handler=get_log)


def list_runs(args: argparse.Namespace, client: ApiClient) -> Any:
    params: dict[str, str] = {}
    for cli_name, api_name in (
        ("updated_after", "updatedAfter"),
        ("created_before", "createdBefore"),
        ("run_id_prefix", "runIdPrefix"),
        ("agent_id", "agentId"),
        ("status", "status"),
        ("runtime", "runtime"),
        ("issue_id", "issueId"),
    ):
        value = getattr(args, cli_name)
        if value is not None:
            params[api_name] = str(value)
    if args.limit is not None:
        params["limit"] = str(args.limit)
    return client.request(
        "GET",
        f"/api/run-intelligence/orgs/{args.org_id}/runs",
        params=params or None,
    )


def get_run(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", f"/api/run-intelligence/runs/{args.run_id}")


def list_events(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", f"/api/run-intelligence/runs/{args.run_id}/events")


def get_log(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", f"/api/run-intelligence/runs/{args.run_id}/log")
