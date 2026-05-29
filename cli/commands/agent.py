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
    adapter_models_parser = actions.add_parser("adapter-models")
    adapter_models_parser.add_argument("--org-id", required=True)
    adapter_models_parser.add_argument("--runtime", required=True, choices=RUNTIMES)
    adapter_models_parser.set_defaults(handler=list_adapter_models)
    adapter_metadata_parser = actions.add_parser("adapter-metadata")
    adapter_metadata_parser.add_argument("--org-id", required=True)
    adapter_metadata_parser.add_argument("--runtime", required=True, choices=RUNTIMES)
    adapter_metadata_parser.set_defaults(handler=get_adapter_metadata)
    adapter_quota_parser = actions.add_parser("adapter-quota-windows")
    adapter_quota_parser.add_argument("--org-id", required=True)
    adapter_quota_parser.add_argument("--runtime", required=True, choices=RUNTIMES)
    adapter_quota_parser.set_defaults(handler=get_adapter_quota_windows)
    adapter_test_parser = actions.add_parser("adapter-test-environment")
    adapter_test_parser.add_argument("--org-id", required=True)
    adapter_test_parser.add_argument("--runtime", required=True, choices=RUNTIMES)
    adapter_test_parser.add_argument("--runtime-config", default="{}")
    adapter_test_parser.set_defaults(handler=test_adapter_environment)
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
    skills_parser = actions.add_parser("skills")
    skills_parser.add_argument("agent_id")
    skills_parser.set_defaults(handler=get_skills)
    skills_sync_parser = actions.add_parser("skills-sync")
    skills_sync_parser.add_argument("agent_id")
    skills_sync_parser.add_argument("--desired-skill", action="append", default=[])
    skills_sync_parser.set_defaults(handler=sync_skills)
    skills_enable_parser = actions.add_parser("skills-enable")
    skills_enable_parser.add_argument("agent_id")
    skills_enable_parser.add_argument("--skill", action="append", default=[])
    skills_enable_parser.set_defaults(handler=enable_skills)
    private_skill_parser = actions.add_parser("private-skill")
    private_skill_parser.add_argument("agent_id")
    private_skill_parser.add_argument("--name", required=True)
    private_skill_parser.add_argument("--slug")
    private_skill_parser.add_argument("--description")
    private_skill_parser.add_argument("--markdown")
    private_skill_parser.set_defaults(handler=create_private_skill)
    skills_analytics_parser = actions.add_parser("skills-analytics")
    skills_analytics_parser.add_argument("agent_id")
    skills_analytics_parser.add_argument("--window-days", type=int, default=30)
    skills_analytics_parser.set_defaults(handler=get_skills_analytics)
    create_parser = actions.add_parser("create")
    create_parser.add_argument("--org-id", required=True)
    create_parser.add_argument("--name", required=True)
    create_parser.add_argument("--role", required=True, choices=ROLES)
    create_parser.add_argument("--runtime", required=True, choices=RUNTIMES)
    create_parser.add_argument("--runtime-config", default="{}")
    create_parser.add_argument("--model")
    create_parser.add_argument("--icon")
    create_parser.add_argument("--desired-skill", action="append", default=[])
    create_parser.add_argument("--metadata")
    create_parser.set_defaults(handler=create_agent)
    update_parser = actions.add_parser("update")
    update_parser.add_argument("agent_id")
    update_parser.add_argument("--name")
    update_parser.add_argument("--title")
    update_parser.add_argument("--icon")
    update_parser.add_argument("--role", choices=ROLES)
    update_parser.add_argument("--reports-to")
    update_parser.add_argument("--capabilities")
    update_parser.add_argument("--desired-skill", action="append")
    update_parser.add_argument("--runtime", choices=RUNTIMES)
    update_parser.add_argument("--runtime-config")
    update_parser.add_argument("--model")
    update_parser.add_argument("--budget-monthly-cents", type=int)
    update_parser.add_argument("--replace-agent-runtime-config", action="store_true")
    update_parser.add_argument("--status")
    update_parser.add_argument("--spent-monthly-cents", type=int)
    update_parser.add_argument("--metadata")
    update_parser.set_defaults(handler=update_agent)
    rollback_parser = actions.add_parser("rollback")
    rollback_parser.add_argument("agent_id")
    rollback_parser.add_argument("revision_id")
    rollback_parser.set_defaults(handler=rollback_config_revision)
    reset_session_parser = actions.add_parser("reset-session")
    reset_session_parser.add_argument("agent_id")
    reset_session_parser.add_argument("--task-key")
    reset_session_parser.set_defaults(handler=reset_session)
    wakeup_parser = actions.add_parser("wakeup")
    wakeup_parser.add_argument("agent_id")
    wakeup_parser.add_argument("--idempotency-key")
    wakeup_parser.add_argument("--reason")
    wakeup_parser.add_argument("--source")
    wakeup_parser.add_argument("--trigger-detail")
    wakeup_parser.add_argument("--payload")
    wakeup_parser.add_argument("--force-fresh-session", action="store_true")
    wakeup_parser.set_defaults(handler=wakeup_agent)
    bootstrap_parser = actions.add_parser("bootstrap-ceo")
    bootstrap_parser.add_argument("--org-id", required=True)
    bootstrap_parser.add_argument("--name", required=True)
    bootstrap_parser.add_argument("--runtime", required=True, choices=RUNTIMES)
    bootstrap_parser.add_argument("--runtime-config", default="{}")
    bootstrap_parser.add_argument("--model")
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


def _runtime_config(
    runtime: str | None, value: str, model: str | None = None
) -> dict[str, Any]:
    config = _json_object(value)
    if model is not None:
        config["model"] = model
    if runtime == "opencode_local":
        configured_model = config.get("model")
        if not isinstance(configured_model, str) or "/" not in configured_model:
            raise ValueError(
                "opencode_local requires --model or runtime config model in provider/model format."
            )
        provider, model_name = configured_model.split("/", 1)
        if not provider.strip() or not model_name.strip():
            raise ValueError(
                "opencode_local requires --model or runtime config model in provider/model format."
            )
        config["model"] = configured_model.strip()
    return config


def list_agents(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", f"/api/orgs/{args.org_id}/agents")


def suggest_agent_name(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", f"/api/orgs/{args.org_id}/agents/name-suggestion")


def list_configurations(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", f"/api/orgs/{args.org_id}/agent-configurations")


def list_adapter_models(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request(
        "GET", f"/api/orgs/{args.org_id}/adapters/{args.runtime}/models"
    )


def get_adapter_metadata(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", f"/api/orgs/{args.org_id}/adapters/{args.runtime}")


def get_adapter_quota_windows(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request(
        "GET", f"/api/orgs/{args.org_id}/adapters/{args.runtime}/quota-windows"
    )


def test_adapter_environment(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request(
        "POST",
        f"/api/orgs/{args.org_id}/adapters/{args.runtime}/test-environment",
        json={"agentRuntimeConfig": _json_object(args.runtime_config)},
    )


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


def get_skills(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", f"/api/agents/{args.agent_id}/skills")


def sync_skills(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request(
        "POST",
        f"/api/agents/{args.agent_id}/skills/sync",
        json={"desiredSkills": args.desired_skill},
    )


def enable_skills(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request(
        "POST",
        f"/api/agents/{args.agent_id}/skills/enable",
        json={"skills": args.skill},
    )


def create_private_skill(args: argparse.Namespace, client: ApiClient) -> Any:
    payload = {
        key: value
        for key, value in {
            "name": args.name,
            "slug": args.slug,
            "description": args.description,
            "markdown": args.markdown,
        }.items()
        if value is not None
    }
    return client.request(
        "POST", f"/api/agents/{args.agent_id}/skills/private", json=payload
    )


def get_skills_analytics(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request(
        "GET",
        f"/api/agents/{args.agent_id}/skills/analytics",
        params={"windowDays": args.window_days},
    )


def create_agent(args: argparse.Namespace, client: ApiClient) -> Any:
    payload: dict[str, Any] = {
        "name": args.name,
        "role": args.role,
        "agentRuntimeType": args.runtime,
        "agentRuntimeConfig": _runtime_config(
            args.runtime, args.runtime_config, args.model
        ),
    }
    if args.icon:
        payload["icon"] = args.icon
    if args.desired_skill:
        payload["desiredSkills"] = args.desired_skill
    if args.metadata:
        payload["metadata"] = _json_object(args.metadata)
    return client.request(
        "POST",
        f"/api/orgs/{args.org_id}/agents",
        json=payload,
    )


def update_agent(args: argparse.Namespace, client: ApiClient) -> Any:
    payload = {
        key: value
        for key, value in {
            "name": args.name,
            "title": args.title,
            "icon": args.icon,
            "role": args.role,
            "reportsTo": args.reports_to,
            "capabilities": args.capabilities,
            "status": args.status,
            "agentRuntimeType": args.runtime,
            "budgetMonthlyCents": args.budget_monthly_cents,
            "spentMonthlyCents": args.spent_monthly_cents,
        }.items()
        if value is not None
    }
    if args.desired_skill is not None:
        payload["desiredSkills"] = args.desired_skill
    if args.runtime_config is not None:
        payload["agentRuntimeConfig"] = _runtime_config(
            args.runtime, args.runtime_config, args.model
        )
    elif args.model is not None:
        payload["agentRuntimeConfig"] = _runtime_config(args.runtime, "{}", args.model)
    if args.metadata is not None:
        payload["metadata"] = _json_object(args.metadata)
    if args.replace_agent_runtime_config:
        payload["replaceAgentRuntimeConfig"] = True
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
    if getattr(args, "source", None):
        payload["source"] = args.source
    if getattr(args, "trigger_detail", None):
        payload["triggerDetail"] = args.trigger_detail
    if getattr(args, "payload", None):
        parsed = json.loads(args.payload)
        if not isinstance(parsed, dict):
            raise ValueError("payload must be a JSON object.")
        payload["payload"] = parsed
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
            "agentRuntimeConfig": _runtime_config(
                args.runtime, args.runtime_config, args.model
            ),
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
