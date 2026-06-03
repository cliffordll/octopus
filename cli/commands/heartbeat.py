from __future__ import annotations

import argparse
import json
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
    events_parser.add_argument("--after-seq", type=int)
    events_parser.add_argument("--limit", type=int)
    events_parser.set_defaults(handler=list_events)
    log_parser = actions.add_parser("log")
    log_parser.add_argument("run_id")
    log_parser.add_argument("--offset", type=int)
    log_parser.add_argument("--limit-bytes", type=int)
    log_parser.set_defaults(handler=get_log)
    workspace_parser = actions.add_parser("workspace-operations")
    workspace_parser.add_argument("run_id")
    workspace_parser.set_defaults(handler=list_workspace_operations)
    workspace_log_parser = actions.add_parser("workspace-operation-log")
    workspace_log_parser.add_argument("operation_id")
    workspace_log_parser.add_argument("--offset", type=int)
    workspace_log_parser.add_argument("--limit-bytes", type=int)
    workspace_log_parser.set_defaults(handler=get_workspace_operation_log)
    debug_parser = actions.add_parser("debug")
    debug_parser.add_argument("run_id")
    debug_parser.add_argument("--after-seq", type=int)
    debug_parser.add_argument("--limit", type=int, default=100)
    debug_parser.set_defaults(handler=debug_run)
    run_parser = actions.add_parser("run")
    run_parser.add_argument("--agent-id", required=True)
    run_parser.add_argument("--idempotency-key")
    run_parser.add_argument("--reason")
    run_parser.add_argument("--source")
    run_parser.add_argument("--trigger-detail")
    run_parser.add_argument("--payload")
    run_parser.add_argument("--force-fresh-session", action="store_true")
    run_parser.set_defaults(handler=run_heartbeat)
    cancel_parser = actions.add_parser("cancel")
    cancel_parser.add_argument("run_id")
    cancel_parser.set_defaults(handler=cancel_run)
    retry_parser = actions.add_parser("retry")
    retry_parser.add_argument("run_id")
    retry_parser.set_defaults(handler=retry_run)


def list_runs(args: argparse.Namespace, client: ApiClient) -> Any:
    params = {"agentId": args.agent_id} if args.agent_id else None
    return client.request(
        "GET", f"/api/orgs/{args.org_id}/heartbeat-runs", params=params
    )


def get_run(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", f"/api/heartbeat-runs/{args.run_id}")


def list_events(args: argparse.Namespace, client: ApiClient) -> Any:
    params: dict[str, str] = {}
    if args.after_seq is not None:
        params["afterSeq"] = str(args.after_seq)
    if args.limit is not None:
        params["limit"] = str(args.limit)
    return client.request(
        "GET",
        f"/api/heartbeat-runs/{args.run_id}/events",
        params=params or None,
    )


def get_log(args: argparse.Namespace, client: ApiClient) -> Any:
    params: dict[str, str] = {}
    if args.offset is not None:
        params["offset"] = str(args.offset)
    if args.limit_bytes is not None:
        params["limitBytes"] = str(args.limit_bytes)
    return client.request(
        "GET",
        f"/api/heartbeat-runs/{args.run_id}/log",
        params=params or None,
    )


def list_workspace_operations(args: argparse.Namespace, client: ApiClient) -> Any:
    operations = client.request(
        "GET",
        f"/api/heartbeat-runs/{args.run_id}/workspace-operations",
    )
    return {"workspaceOperations": operations}


def get_workspace_operation_log(args: argparse.Namespace, client: ApiClient) -> Any:
    params: dict[str, str] = {}
    if args.offset is not None:
        params["offset"] = str(args.offset)
    if args.limit_bytes is not None:
        params["limitBytes"] = str(args.limit_bytes)
    return client.request(
        "GET",
        f"/api/workspace-operations/{args.operation_id}/log",
        params=params or None,
    )


def debug_run(args: argparse.Namespace, client: ApiClient) -> Any:
    run = client.request("GET", f"/api/heartbeat-runs/{args.run_id}")
    params: dict[str, str] = {}
    if args.after_seq is not None:
        params["afterSeq"] = str(args.after_seq)
    if args.limit is not None:
        params["limit"] = str(args.limit)
    events = client.request(
        "GET",
        f"/api/heartbeat-runs/{args.run_id}/events",
        params=params or None,
    )
    return {
        "debug": {
            "run": run,
            "events": events,
        }
    }


def run_heartbeat(args: argparse.Namespace, client: ApiClient) -> Any:
    payload: dict[str, Any] = {}
    if args.idempotency_key:
        payload["idempotencyKey"] = args.idempotency_key
    if args.reason:
        payload["reason"] = args.reason
    if args.source:
        payload["source"] = args.source
    if args.trigger_detail:
        payload["triggerDetail"] = args.trigger_detail
    if args.payload:
        parsed = json.loads(args.payload)
        if not isinstance(parsed, dict):
            raise ValueError("payload must be a JSON object.")
        payload["payload"] = parsed
    if args.force_fresh_session:
        payload["forceFreshSession"] = True
    return client.request("POST", f"/api/agents/{args.agent_id}/wakeup", json=payload)


def cancel_run(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("POST", f"/api/heartbeat-runs/{args.run_id}/cancel", json={})


def retry_run(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("POST", f"/api/heartbeat-runs/{args.run_id}/retry", json={})
