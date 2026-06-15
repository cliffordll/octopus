from __future__ import annotations

import json
import os
from typing import Any

from .types import RuntimeExecutionContext


def apply_runtime_context_env(
    env: dict[str, str], context: RuntimeExecutionContext
) -> None:
    runtime_context = context.config.get("_octopus")
    if not isinstance(runtime_context, dict):
        runtime_context = {}
    workspace = context.workspace if isinstance(context.workspace, dict) else {}
    workspace_context = workspace.get("rudderWorkspace")
    if not isinstance(workspace_context, dict):
        workspace_context = {}

    for key in (
        "OCTOPUS_CONVERSATION_ARTIFACTS_DIR",
        "OCTOPUS_ISSUE_ARTIFACTS_DIR",
        "OCTOPUS_RUN_ARTIFACTS_DIR",
    ):
        env.pop(key, None)

    env["OCTOPUS_AGENT_ID"] = context.agent_id
    env["OCTOPUS_ORG_ID"] = context.org_id
    env["OCTOPUS_RUN_ID"] = context.run_id
    env.setdefault(
        "OCTOPUS_API_URL", os.environ.get("OCTOPUS_API_URL", "http://localhost:8000")
    )

    _set_env(
        env,
        "OCTOPUS_TASK_ID",
        runtime_context.get("taskId") or runtime_context.get("issueId"),
    )
    _set_env(env, "OCTOPUS_WAKE_REASON", runtime_context.get("wakeReason"))
    _set_env(
        env,
        "OCTOPUS_WAKE_COMMENT_ID",
        runtime_context.get("wakeCommentId") or runtime_context.get("commentId"),
    )
    _set_env(env, "OCTOPUS_APPROVAL_ID", runtime_context.get("approvalId"))
    _set_env(env, "OCTOPUS_APPROVAL_STATUS", runtime_context.get("approvalStatus"))
    issue_ids = runtime_context.get("issueIds")
    if isinstance(issue_ids, list):
        linked = [_string(value) for value in issue_ids]
        linked = [value for value in linked if value]
        if linked:
            env["OCTOPUS_LINKED_ISSUE_IDS"] = ",".join(linked)

    _set_env(env, "OCTOPUS_WORKSPACE_CWD", workspace_context.get("cwd"))
    _set_env(env, "OCTOPUS_WORKSPACE_SOURCE", workspace_context.get("source"))
    _set_env(env, "OCTOPUS_WORKSPACE_STRATEGY", workspace_context.get("strategy"))
    _set_env(env, "OCTOPUS_WORKSPACE_ID", workspace_context.get("workspaceId"))
    _set_env(env, "OCTOPUS_WORKSPACE_REPO_URL", workspace_context.get("repoUrl"))
    _set_env(env, "OCTOPUS_WORKSPACE_REPO_REF", workspace_context.get("repoRef"))
    _set_env(env, "OCTOPUS_WORKSPACE_BRANCH", workspace_context.get("branchName"))
    _set_env(
        env,
        "OCTOPUS_WORKSPACE_WORKTREE_PATH",
        workspace_context.get("worktreePath"),
    )
    agent_home = _first_string(
        workspace_context.get("agentHome"), runtime_context.get("agentHome")
    )
    if agent_home:
        env["AGENT_HOME"] = agent_home
        env["OCTOPUS_AGENT_ROOT"] = agent_home
    else:
        env.pop("AGENT_HOME", None)
        env.pop("OCTOPUS_AGENT_ROOT", None)
    _set_env(
        env,
        "OCTOPUS_AGENT_INSTRUCTIONS_DIR",
        _first_string(
            workspace_context.get("instructionsDir"),
            runtime_context.get("agentInstructionsDir"),
        ),
    )
    _set_env(
        env,
        "OCTOPUS_AGENT_MEMORY_DIR",
        _first_string(
            workspace_context.get("memoryDir"), runtime_context.get("agentMemoryDir")
        ),
    )
    _set_env(
        env,
        "OCTOPUS_AGENT_LIFE_DIR",
        _first_string(
            workspace_context.get("lifeDir"), runtime_context.get("agentLifeDir")
        ),
    )
    _set_env(
        env,
        "OCTOPUS_AGENT_SKILLS_DIR",
        _first_string(
            workspace_context.get("skillsDir"),
            runtime_context.get("agentSkillsRootPath"),
        ),
    )
    _set_env(
        env, "OCTOPUS_ORG_WORKSPACE_ROOT", workspace_context.get("orgWorkspaceRoot")
    )
    _set_env(env, "OCTOPUS_ORG_SKILLS_DIR", workspace_context.get("orgSkillsDir"))
    _set_env(env, "OCTOPUS_ORG_PLANS_DIR", workspace_context.get("orgPlansDir"))
    _set_env(env, "OCTOPUS_ORG_ARTIFACTS_DIR", workspace_context.get("orgArtifactsDir"))

    runtime_services = workspace.get("rudderRuntimeServices")
    if isinstance(runtime_services, list) and runtime_services:
        env["OCTOPUS_RUNTIME_SERVICES_JSON"] = json.dumps(runtime_services)
    runtime_service_intents = workspace.get("rudderRuntimeServiceIntents")
    if isinstance(runtime_service_intents, list) and runtime_service_intents:
        env["OCTOPUS_RUNTIME_SERVICE_INTENTS_JSON"] = json.dumps(
            runtime_service_intents
        )
    _set_env(
        env, "OCTOPUS_RUNTIME_PRIMARY_URL", workspace.get("rudderRuntimePrimaryUrl")
    )


def _set_env(env: dict[str, str], key: str, value: Any) -> None:
    text = _string(value)
    if text:
        env[key] = text


def _string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _first_string(*values: Any) -> str | None:
    for value in values:
        text = _string(value)
        if text:
            return text
    return None
