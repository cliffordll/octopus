from __future__ import annotations

import argparse
from typing import Any

from ..client import ApiClient


def configure(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("heartbeat", help="Read heartbeat runs")
    actions = parser.add_subparsers(dest="heartbeat_action", required=True)
    list_parser = actions.add_parser("list")
    list_parser.add_argument("--org-id", required=True)
    list_parser.add_argument("--agent-id")
    list_parser.set_defaults(handler=list_runs)
    get_parser = actions.add_parser("get")
    get_parser.add_argument("run_id")
    get_parser.set_defaults(handler=get_run)
    events_parser = actions.add_parser("events")
    events_parser.add_argument("run_id")
    events_parser.set_defaults(handler=list_events)
    run_parser = actions.add_parser("run")
    run_parser.add_argument("--agent-id", required=True)
    run_parser.set_defaults(handler=run_heartbeat)


def list_runs(args: argparse.Namespace, client: ApiClient) -> Any:
    params = {"agentId": args.agent_id} if args.agent_id else None
    return client.request(
        "GET", f"/api/orgs/{args.org_id}/heartbeat-runs", params=params
    )


def get_run(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", f"/api/heartbeat-runs/{args.run_id}")


def list_events(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", f"/api/heartbeat-runs/{args.run_id}/events")


def run_heartbeat(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request(
        "POST", f"/api/agents/{args.agent_id}/heartbeat/invoke", json={}
    )
