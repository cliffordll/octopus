from __future__ import annotations

import argparse
import json
from typing import Any

from ..client import ApiClient


def configure(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("cost", help="Report and query cost events")
    actions = parser.add_subparsers(dest="cost_action", required=True)

    report_parser = actions.add_parser("report", help="Report a cost event")
    report_parser.add_argument("--org-id", required=True)
    report_parser.add_argument("--agent-id")
    report_parser.add_argument("--project-id")
    report_parser.add_argument("--source-type")
    report_parser.add_argument("--source-id")
    report_parser.add_argument("--runtime-type")
    report_parser.add_argument("--provider")
    report_parser.add_argument("--model")
    report_parser.add_argument("--biller")
    report_parser.add_argument("--cost-cents", type=int)
    report_parser.add_argument("--cost-usd", type=float)
    report_parser.add_argument("--input-tokens", type=int)
    report_parser.add_argument("--output-tokens", type=int)
    report_parser.add_argument("--total-tokens", type=int)
    report_parser.add_argument("--metadata")
    report_parser.add_argument("--occurred-at")
    report_parser.set_defaults(handler=report_cost)

    for name, help_text, handler in (
        ("summary", "Show cost summary", cost_summary),
        ("by-agent", "Group cost by agent", cost_by_agent),
        ("by-provider", "Group cost by provider", cost_by_provider),
        ("by-biller", "Group cost by biller", cost_by_biller),
        ("by-project", "Group cost by project", cost_by_project),
        ("by-agent-model", "Group cost by agent and model", cost_by_agent_model),
        ("trend", "Show cost trend", cost_trend),
        ("window-spend", "Show cost for the requested window", cost_window_spend),
    ):
        query_parser = actions.add_parser(name, help=help_text)
        query_parser.add_argument("--org-id", required=True)
        _add_query_args(query_parser)
        query_parser.set_defaults(handler=handler)


def _add_query_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--agent-id")
    parser.add_argument("--project-id")
    parser.add_argument("--provider")
    parser.add_argument("--biller")
    parser.add_argument("--model")
    parser.add_argument("--start-time")
    parser.add_argument("--end-time")
    parser.add_argument("--limit", type=int)


def _query_params(args: argparse.Namespace) -> dict[str, str] | None:
    params: dict[str, str] = {}
    for cli_name, api_name in (
        ("agent_id", "agentId"),
        ("project_id", "projectId"),
        ("provider", "provider"),
        ("biller", "biller"),
        ("model", "model"),
        ("start_time", "startTime"),
        ("end_time", "endTime"),
        ("limit", "limit"),
    ):
        value = getattr(args, cli_name, None)
        if value is not None:
            params[api_name] = str(value)
    return params or None


def _json_object(value: str, flag: str) -> dict[str, Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError(f"{flag} must be a JSON object.")
    return parsed


def report_cost(args: argparse.Namespace, client: ApiClient) -> Any:
    if args.cost_cents is None and args.cost_usd is None:
        raise ValueError("--cost-cents or --cost-usd is required.")
    payload = {
        api_name: value
        for cli_name, api_name in (
            ("agent_id", "agentId"),
            ("project_id", "projectId"),
            ("source_type", "sourceType"),
            ("source_id", "sourceId"),
            ("runtime_type", "runtimeType"),
            ("provider", "provider"),
            ("model", "model"),
            ("biller", "biller"),
            ("cost_cents", "costCents"),
            ("cost_usd", "costUsd"),
            ("input_tokens", "inputTokens"),
            ("output_tokens", "outputTokens"),
            ("total_tokens", "totalTokens"),
            ("occurred_at", "occurredAt"),
        )
        if (value := getattr(args, cli_name, None)) is not None
    }
    if args.metadata is not None:
        payload["metadata"] = _json_object(args.metadata, "--metadata")
    return client.request("POST", f"/api/orgs/{args.org_id}/cost-events", json=payload)


def cost_summary(args: argparse.Namespace, client: ApiClient) -> Any:
    return _cost_query(client, args, "summary")


def cost_by_agent(args: argparse.Namespace, client: ApiClient) -> Any:
    return _cost_query(client, args, "by-agent")


def cost_by_provider(args: argparse.Namespace, client: ApiClient) -> Any:
    return _cost_query(client, args, "by-provider")


def cost_by_biller(args: argparse.Namespace, client: ApiClient) -> Any:
    return _cost_query(client, args, "by-biller")


def cost_by_project(args: argparse.Namespace, client: ApiClient) -> Any:
    return _cost_query(client, args, "by-project")


def cost_by_agent_model(args: argparse.Namespace, client: ApiClient) -> Any:
    return _cost_query(client, args, "by-agent-model")


def cost_trend(args: argparse.Namespace, client: ApiClient) -> Any:
    return _cost_query(client, args, "trend")


def cost_window_spend(args: argparse.Namespace, client: ApiClient) -> Any:
    return _cost_query(client, args, "window-spend")


def _cost_query(client: ApiClient, args: argparse.Namespace, path: str) -> Any:
    return client.request(
        "GET", f"/api/orgs/{args.org_id}/costs/{path}", params=_query_params(args)
    )
