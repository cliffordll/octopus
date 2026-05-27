from __future__ import annotations

import argparse
import json
from typing import Any

from ..client import ApiClient

ROLES = (
    "ceo",
    "cto",
    "cmo",
    "cfo",
    "engineer",
    "designer",
    "pm",
    "qa",
    "devops",
    "researcher",
    "general",
)
RUNTIMES = (
    "process",
    "http",
    "claude_local",
    "codex_local",
    "gemini_local",
    "opencode_local",
    "pi_local",
    "cursor",
    "openclaw_gateway",
    "hermes_local",
)


def configure(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("agent", help="Manage agents")
    actions = parser.add_subparsers(dest="agent_action", required=True)
    list_parser = actions.add_parser("list")
    list_parser.add_argument("--org-id", required=True)
    list_parser.set_defaults(handler=list_agents)
    get_parser = actions.add_parser("get")
    get_parser.add_argument("agent_id")
    get_parser.set_defaults(handler=get_agent)
    create_parser = actions.add_parser("create")
    create_parser.add_argument("--org-id", required=True)
    create_parser.add_argument("--name", required=True)
    create_parser.add_argument("--role", required=True, choices=ROLES)
    create_parser.add_argument("--runtime", required=True, choices=RUNTIMES)
    create_parser.add_argument("--runtime-config", default="{}")
    create_parser.set_defaults(handler=create_agent)
    bootstrap_parser = actions.add_parser("bootstrap-ceo")
    bootstrap_parser.add_argument("--org-id", required=True)
    bootstrap_parser.add_argument("--name", required=True)
    bootstrap_parser.add_argument("--runtime", required=True, choices=RUNTIMES)
    bootstrap_parser.add_argument("--runtime-config", default="{}")
    bootstrap_parser.set_defaults(handler=bootstrap_ceo)
    for name, handler in (
        ("pause", pause_agent),
        ("resume", resume_agent),
        ("terminate", terminate_agent),
        ("invoke", invoke_agent),
    ):
        action = actions.add_parser(name)
        action.add_argument("agent_id")
        action.set_defaults(handler=handler)


def _json_object(value: str) -> dict[str, Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("Runtime config must be a JSON object.")
    return parsed


def list_agents(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", f"/api/orgs/{args.org_id}/agents")


def get_agent(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", f"/api/agents/{args.agent_id}")


def create_agent(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request(
        "POST",
        f"/api/orgs/{args.org_id}/agents",
        json={
            "name": args.name,
            "role": args.role,
            "agentRuntimeType": args.runtime,
            "agentRuntimeConfig": _json_object(args.runtime_config),
        },
    )


def bootstrap_ceo(args: argparse.Namespace, client: ApiClient) -> Any:
    existing = client.request("GET", f"/api/orgs/{args.org_id}/agents")
    if not isinstance(existing, list):
        raise ValueError("Agent list response must be an array.")
    if existing:
        raise ValueError("Organization already has agents; use agent create instead.")
    return client.request(
        "POST",
        f"/api/orgs/{args.org_id}/agents",
        json={
            "name": args.name,
            "role": "ceo",
            "agentRuntimeType": args.runtime,
            "agentRuntimeConfig": _json_object(args.runtime_config),
        },
    )


def pause_agent(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("POST", f"/api/agents/{args.agent_id}/pause", json={})


def resume_agent(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("POST", f"/api/agents/{args.agent_id}/resume", json={})


def terminate_agent(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("POST", f"/api/agents/{args.agent_id}/terminate", json={})


def invoke_agent(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request(
        "POST", f"/api/agents/{args.agent_id}/heartbeat/invoke", json={}
    )
