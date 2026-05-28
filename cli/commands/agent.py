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
    name_suggestion_parser = actions.add_parser("name-suggestion")
    name_suggestion_parser.add_argument("--org-id", required=True)
    name_suggestion_parser.set_defaults(handler=suggest_agent_name)
    configurations_parser = actions.add_parser("configurations")
    configurations_parser.add_argument("--org-id", required=True)
    configurations_parser.set_defaults(handler=list_configurations)
    get_parser = actions.add_parser("get")
    get_parser.add_argument("agent_id")
    get_parser.set_defaults(handler=get_agent)
    configuration_parser = actions.add_parser("configuration")
    configuration_parser.add_argument("agent_id")
    configuration_parser.set_defaults(handler=get_configuration)
    revisions_parser = actions.add_parser("config-revisions")
    revisions_parser.add_argument("agent_id")
    revisions_parser.set_defaults(handler=list_config_revisions)
    revision_parser = actions.add_parser("config-revision")
    revision_parser.add_argument("agent_id")
    revision_parser.add_argument("revision_id")
    revision_parser.set_defaults(handler=get_config_revision)
    runtime_state_parser = actions.add_parser("runtime-state")
    runtime_state_parser.add_argument("agent_id")
    runtime_state_parser.set_defaults(handler=get_runtime_state)
    task_sessions_parser = actions.add_parser("task-sessions")
    task_sessions_parser.add_argument("agent_id")
    task_sessions_parser.set_defaults(handler=list_task_sessions)
    create_parser = actions.add_parser("create")
    create_parser.add_argument("--org-id", required=True)
    create_parser.add_argument("--name", required=True)
    create_parser.add_argument("--role", required=True, choices=ROLES)
    create_parser.add_argument("--runtime", required=True, choices=RUNTIMES)
    create_parser.add_argument("--runtime-config", default="{}")
    create_parser.set_defaults(handler=create_agent)
    update_parser = actions.add_parser("update")
    update_parser.add_argument("agent_id")
    update_parser.add_argument("--name")
    update_parser.add_argument("--title")
    update_parser.add_argument("--role", choices=ROLES)
    update_parser.add_argument("--reports-to")
    update_parser.add_argument("--capabilities")
    update_parser.add_argument("--runtime", choices=RUNTIMES)
    update_parser.add_argument("--runtime-config")
    update_parser.add_argument("--budget-monthly-cents", type=int)
    update_parser.set_defaults(handler=update_agent)
    rollback_parser = actions.add_parser("rollback")
    rollback_parser.add_argument("agent_id")
    rollback_parser.add_argument("revision_id")
    rollback_parser.set_defaults(handler=rollback_config_revision)
    reset_session_parser = actions.add_parser("reset-session")
    reset_session_parser.add_argument("agent_id")
    reset_session_parser.add_argument("--task-key")
    reset_session_parser.add_argument("--force-fresh-session", action="store_true")
    reset_session_parser.set_defaults(handler=reset_session)
    wakeup_parser = actions.add_parser("wakeup")
    wakeup_parser.add_argument("agent_id")
    wakeup_parser.add_argument("--idempotency-key")
    wakeup_parser.add_argument("--reason")
    wakeup_parser.add_argument("--force-fresh-session", action="store_true")
    wakeup_parser.set_defaults(handler=wakeup_agent)
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


def suggest_agent_name(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", f"/api/orgs/{args.org_id}/agents/name-suggestion")


def list_configurations(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", f"/api/orgs/{args.org_id}/agent-configurations")


def get_agent(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", f"/api/agents/{args.agent_id}")


def get_configuration(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", f"/api/agents/{args.agent_id}/configuration")


def list_config_revisions(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", f"/api/agents/{args.agent_id}/config-revisions")


def get_config_revision(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request(
        "GET",
        f"/api/agents/{args.agent_id}/config-revisions/{args.revision_id}",
    )


def get_runtime_state(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", f"/api/agents/{args.agent_id}/runtime-state")


def list_task_sessions(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", f"/api/agents/{args.agent_id}/task-sessions")


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


def update_agent(args: argparse.Namespace, client: ApiClient) -> Any:
    payload = {
        key: value
        for key, value in {
            "name": args.name,
            "title": args.title,
            "role": args.role,
            "reportsTo": args.reports_to,
            "capabilities": args.capabilities,
            "agentRuntimeType": args.runtime,
            "budgetMonthlyCents": args.budget_monthly_cents,
        }.items()
        if value is not None
    }
    if args.runtime_config is not None:
        payload["agentRuntimeConfig"] = _json_object(args.runtime_config)
    if not payload:
        raise ValueError("At least one update field is required.")
    return client.request("PATCH", f"/api/agents/{args.agent_id}", json=payload)


def rollback_config_revision(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request(
        "POST",
        f"/api/agents/{args.agent_id}/config-revisions/{args.revision_id}/rollback",
        json={},
    )


def reset_session(args: argparse.Namespace, client: ApiClient) -> Any:
    payload: dict[str, Any] = {}
    if args.task_key:
        payload["taskKey"] = args.task_key
    if args.force_fresh_session:
        payload["forceFreshSession"] = True
    return client.request(
        "POST",
        f"/api/agents/{args.agent_id}/runtime-state/reset-session",
        json=payload,
    )


def _wake_payload(args: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if args.idempotency_key:
        payload["idempotencyKey"] = args.idempotency_key
    if args.reason:
        payload["reason"] = args.reason
    if args.force_fresh_session:
        payload["forceFreshSession"] = True
    return payload


def wakeup_agent(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request(
        "POST",
        f"/api/agents/{args.agent_id}/wakeup",
        json=_wake_payload(args),
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
