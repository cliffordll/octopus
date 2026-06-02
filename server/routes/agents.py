from __future__ import annotations

import asyncio
from typing import Any

from fastapi import (
    APIRouter,
    Body,
    Depends,
    HTTPException,
    Request,
    status,
)
from fastapi.responses import JSONResponse

from packages.shared.api_paths.agents import (
    AGENT_ARCHIVE_PATH,
    AGENT_CONFIGURATION_PATH,
    AGENT_CONFIG_REVISIONS_PATH,
    AGENT_CONFIG_REVISION_PATH,
    AGENT_CONFIG_ROLLBACK_PATH,
    AGENT_DETAIL_PATH,
    AGENT_INSTRUCTIONS_BUNDLE_FILE_PATH,
    AGENT_INSTRUCTIONS_BUNDLE_PATH,
    AGENT_INSTRUCTIONS_PATH,
    AGENT_PAUSE_PATH,
    AGENT_RESET_SESSION_PATH,
    AGENT_RESUME_PATH,
    AGENT_RUNTIME_STATE_PATH,
    AGENT_SKILLS_ANALYTICS_PATH,
    AGENT_SKILLS_ENABLE_PATH,
    AGENT_SKILLS_PATH,
    AGENT_SKILLS_PRIVATE_PATH,
    AGENT_SKILLS_SYNC_PATH,
    AGENT_TASK_SESSIONS_PATH,
    AGENT_TERMINATE_PATH,
    ORG_AGENT_CONFIGURATIONS_PATH,
    ORG_AGENT_LIST_PATH,
    ORG_AGENT_NAME_SUGGESTION_PATH,
    ORG_ADAPTER_METADATA_PATH,
    ORG_ADAPTER_MODELS_PATH,
    ORG_ADAPTER_QUOTA_WINDOWS_PATH,
    ORG_ADAPTER_TEST_ENVIRONMENT_PATH,
)
from packages.runtimes import (
    get_runtime_adapter,
    get_runtime_metadata,
    get_runtime_quota_windows,
    list_runtime_models,
)
from packages.shared.api_paths.heartbeat import (
    AGENT_HEARTBEAT_INVOKE_PATH,
    AGENT_WAKEUP_PATH,
    HEARTBEAT_RUN_CANCEL_PATH,
    HEARTBEAT_RUN_EVENTS_PATH,
    HEARTBEAT_RUN_LOG_PATH,
    HEARTBEAT_RUN_PATH,
    HEARTBEAT_RUN_RETRY_PATH,
    HEARTBEAT_RUN_WORKSPACE_OPERATIONS_PATH,
    ORG_HEARTBEAT_RUNS_PATH,
)
from packages.shared.types.agent import (
    Agent,
    AgentConfiguration,
    AgentConfigRevision,
    AgentDetail,
    AgentInstructionsBundle,
    AgentInstructionsFileDetail,
    AgentInstructionsPathResult,
    AgentRuntimeState,
    AgentSkillAnalytics,
    AgentSkillSnapshot,
    AgentTaskSession,
    ResetAgentSessionResult,
)
from packages.shared.types.heartbeat import HeartbeatRun, HeartbeatRunEvent
from packages.shared.types.workspace import WorkspaceOperation
from packages.shared.validators.agent import (
    validate_agent_private_skill,
    validate_agent_skills_enable,
    validate_agent_skills_sync,
    validate_create_agent,
    validate_reset_agent_session,
    validate_test_agent_runtime_environment,
    validate_update_agent,
    validate_update_agent_instructions_bundle,
    validate_update_agent_instructions_path,
    validate_upsert_agent_instructions_file,
)
from packages.shared.validators.heartbeat import validate_wake_agent

from ..dependencies.access import (
    assert_organization_access,
    require_actor_identity,
    require_board_access,
    require_organization_access,
)
from ..dependencies.agent_instructions import get_agent_instructions_service
from ..dependencies.agents import get_agent_service
from ..dependencies.heartbeat import get_heartbeat_service
from ..dependencies.workspaces import get_workspace_service
from ..services.agents import AgentConflictError, AgentService
from ..services.agent_instructions import AgentInstructionsService
from ..services.heartbeat import HeartbeatService, dispatch_queued_agent
from ..services.workspaces import WorkspaceService

router = APIRouter(tags=["agents"])


def _schedule_dispatch(request: Request, agent_id: str) -> None:
    async def dispatch_after_commit() -> None:
        await asyncio.sleep(0.01)
        await dispatch_queued_agent(request.app.state.session_factory, agent_id)

    task = asyncio.create_task(dispatch_after_commit())
    tasks = getattr(request.app.state, "heartbeat_dispatch_tasks", set())
    tasks.add(task)
    request.app.state.heartbeat_dispatch_tasks = tasks
    task.add_done_callback(tasks.discard)


async def _get_agent_or_404(
    agent_id: str, *, request: Request, service: AgentService
) -> Agent:
    agent = await service.get(agent_id)
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found"
        )
    assert_organization_access(request, agent["orgId"])
    return agent


@router.get(ORG_AGENT_LIST_PATH)
async def list_agents_route(
    orgId: str,
    _: None = Depends(require_organization_access),
    service: AgentService = Depends(get_agent_service),
) -> list[Agent]:
    return await service.list_for_org(orgId)


@router.post(ORG_AGENT_LIST_PATH, status_code=status.HTTP_201_CREATED)
async def create_agent_route(
    request: Request,
    orgId: str,
    body: dict[str, Any] = Body(...),
    _: None = Depends(require_board_access),
    service: AgentService = Depends(get_agent_service),
) -> Agent:
    try:
        payload = validate_create_agent(body)
        actor = require_actor_identity(request)
        return await service.create_agent(
            orgId, payload, actor_type=actor.actor_type, actor_id=actor.actor_id
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


@router.get(ORG_AGENT_NAME_SUGGESTION_PATH)
async def suggest_agent_name_route(
    orgId: str,
    _: None = Depends(require_board_access),
    service: AgentService = Depends(get_agent_service),
) -> dict[str, str]:
    return {"name": await service.suggest_name(orgId)}


@router.get(AGENT_DETAIL_PATH)
async def get_agent_route(
    id: str,
    request: Request,
    service: AgentService = Depends(get_agent_service),
) -> AgentDetail:
    agent = await service.get_detail(id)
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found"
        )
    assert_organization_access(request, agent["orgId"])
    return agent


@router.patch(AGENT_DETAIL_PATH)
async def update_agent_route(
    id: str,
    request: Request,
    body: dict[str, Any] = Body(...),
    _: None = Depends(require_board_access),
    service: AgentService = Depends(get_agent_service),
) -> Agent:
    await _get_agent_or_404(id, request=request, service=service)
    try:
        payload = validate_update_agent(body)
        actor = require_actor_identity(request)
        updated = await service.update_agent(
            id, payload, actor_type=actor.actor_type, actor_id=actor.actor_id
        )
    except AgentConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found"
        )
    return updated


async def _lifecycle_action(
    agent_id: str,
    *,
    action: str,
    request: Request,
    service: AgentService,
) -> Agent:
    await _get_agent_or_404(agent_id, request=request, service=service)
    actor = require_actor_identity(request)
    method = {
        "archive": service.terminate_agent,
        "pause": service.pause_agent,
        "resume": service.resume_agent,
        "terminate": service.terminate_agent,
    }[action]
    try:
        agent = await method(
            agent_id, actor_type=actor.actor_type, actor_id=actor.actor_id
        )
    except AgentConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found"
        )
    return agent


@router.post(AGENT_ARCHIVE_PATH)
async def archive_agent_route(
    id: str,
    request: Request,
    _: None = Depends(require_board_access),
    service: AgentService = Depends(get_agent_service),
) -> Agent:
    return await _lifecycle_action(
        id, action="archive", request=request, service=service
    )


@router.post(AGENT_PAUSE_PATH)
async def pause_agent_route(
    id: str,
    request: Request,
    _: None = Depends(require_board_access),
    service: AgentService = Depends(get_agent_service),
) -> Agent:
    return await _lifecycle_action(id, action="pause", request=request, service=service)


@router.post(AGENT_RESUME_PATH)
async def resume_agent_route(
    id: str,
    request: Request,
    _: None = Depends(require_board_access),
    service: AgentService = Depends(get_agent_service),
    heartbeat: HeartbeatService = Depends(get_heartbeat_service),
) -> Agent:
    agent = await _lifecycle_action(
        id, action="resume", request=request, service=service
    )
    resumed = await heartbeat.resume_deferred_wakeups(id, execute_immediately=False)
    if resumed:
        _schedule_dispatch(request, id)
    return agent


@router.post(AGENT_TERMINATE_PATH)
async def terminate_agent_route(
    id: str,
    request: Request,
    _: None = Depends(require_board_access),
    service: AgentService = Depends(get_agent_service),
) -> Agent:
    return await _lifecycle_action(
        id, action="terminate", request=request, service=service
    )


@router.get(AGENT_CONFIGURATION_PATH)
async def get_agent_configuration_route(
    id: str,
    request: Request,
    _: None = Depends(require_board_access),
    service: AgentService = Depends(get_agent_service),
) -> AgentConfiguration:
    await _get_agent_or_404(id, request=request, service=service)
    configuration = await service.get_configuration(id)
    if configuration is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found"
        )
    return configuration


@router.patch(AGENT_INSTRUCTIONS_PATH)
async def update_agent_instructions_path_route(
    request: Request,
    id: str,
    body: dict[str, Any] = Body(...),
    agent_service: AgentService = Depends(get_agent_service),
    instructions_service: AgentInstructionsService = Depends(
        get_agent_instructions_service
    ),
) -> AgentInstructionsPathResult:
    await _get_agent_or_404(id, request=request, service=agent_service)
    try:
        payload = validate_update_agent_instructions_path(body)
        actor = require_actor_identity(request)
        result = await instructions_service.update_path(
            id,
            payload,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found"
        )
    return result


@router.get(AGENT_INSTRUCTIONS_BUNDLE_PATH)
async def get_agent_instructions_bundle_route(
    request: Request,
    id: str,
    agent_service: AgentService = Depends(get_agent_service),
    instructions_service: AgentInstructionsService = Depends(
        get_agent_instructions_service
    ),
) -> AgentInstructionsBundle:
    await _get_agent_or_404(id, request=request, service=agent_service)
    result = await instructions_service.get_bundle(id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found"
        )
    return result


@router.patch(AGENT_INSTRUCTIONS_BUNDLE_PATH)
async def update_agent_instructions_bundle_route(
    request: Request,
    id: str,
    body: dict[str, Any] = Body(...),
    agent_service: AgentService = Depends(get_agent_service),
    instructions_service: AgentInstructionsService = Depends(
        get_agent_instructions_service
    ),
) -> AgentInstructionsBundle:
    await _get_agent_or_404(id, request=request, service=agent_service)
    try:
        payload = validate_update_agent_instructions_bundle(body)
        actor = require_actor_identity(request)
        result = await instructions_service.update_bundle(
            id,
            payload,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found"
        )
    return result


@router.get(AGENT_INSTRUCTIONS_BUNDLE_FILE_PATH)
async def read_agent_instructions_file_route(
    request: Request,
    id: str,
    path: str = "",
    agent_service: AgentService = Depends(get_agent_service),
    instructions_service: AgentInstructionsService = Depends(
        get_agent_instructions_service
    ),
) -> AgentInstructionsFileDetail:
    await _get_agent_or_404(id, request=request, service=agent_service)
    if not path.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Query parameter 'path' is required",
        )
    try:
        result = await instructions_service.read_file(id, path)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found"
        )
    return result


@router.put(AGENT_INSTRUCTIONS_BUNDLE_FILE_PATH)
async def upsert_agent_instructions_file_route(
    request: Request,
    id: str,
    body: dict[str, Any] = Body(...),
    agent_service: AgentService = Depends(get_agent_service),
    instructions_service: AgentInstructionsService = Depends(
        get_agent_instructions_service
    ),
) -> AgentInstructionsFileDetail:
    await _get_agent_or_404(id, request=request, service=agent_service)
    try:
        payload = validate_upsert_agent_instructions_file(body)
        actor = require_actor_identity(request)
        result = await instructions_service.write_file(
            id,
            payload,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found"
        )
    return result


@router.delete(AGENT_INSTRUCTIONS_BUNDLE_FILE_PATH)
async def delete_agent_instructions_file_route(
    request: Request,
    id: str,
    path: str = "",
    agent_service: AgentService = Depends(get_agent_service),
    instructions_service: AgentInstructionsService = Depends(
        get_agent_instructions_service
    ),
) -> AgentInstructionsBundle:
    await _get_agent_or_404(id, request=request, service=agent_service)
    if not path.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Query parameter 'path' is required",
        )
    try:
        actor = require_actor_identity(request)
        result = await instructions_service.delete_file(
            id,
            path,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found"
        )
    return result


@router.get(ORG_AGENT_CONFIGURATIONS_PATH)
async def list_agent_configurations_route(
    orgId: str,
    _: None = Depends(require_board_access),
    service: AgentService = Depends(get_agent_service),
) -> list[AgentConfiguration]:
    return await service.list_configurations_for_org(orgId)


@router.get(ORG_ADAPTER_MODELS_PATH)
async def list_adapter_models_route(
    orgId: str,
    type: str,
    _: None = Depends(require_organization_access),
) -> list[dict[str, str]]:
    return await list_runtime_models(type)


@router.get(ORG_ADAPTER_METADATA_PATH)
async def get_adapter_metadata_route(
    orgId: str,
    type: str,
    _: None = Depends(require_organization_access),
) -> dict[str, Any]:
    try:
        return await get_runtime_metadata(type)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


@router.get(ORG_ADAPTER_QUOTA_WINDOWS_PATH)
async def get_adapter_quota_windows_route(
    orgId: str,
    type: str,
    _: None = Depends(require_organization_access),
) -> dict[str, Any]:
    try:
        return await get_runtime_quota_windows(type)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


@router.post(ORG_ADAPTER_TEST_ENVIRONMENT_PATH)
async def test_adapter_environment_route(
    orgId: str,
    type: str,
    body: dict[str, Any] = Body(default={}),
    _: None = Depends(require_board_access),
) -> dict[str, Any]:
    try:
        payload = validate_test_agent_runtime_environment(body)
        result = await get_runtime_adapter(type).test_environment(
            payload["agentRuntimeConfig"]
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    return {
        "agentRuntimeType": result.agent_runtime_type,
        "status": result.status,
        "checks": result.checks,
    }


@router.get(AGENT_CONFIG_REVISIONS_PATH)
async def list_agent_config_revisions_route(
    id: str,
    request: Request,
    _: None = Depends(require_board_access),
    service: AgentService = Depends(get_agent_service),
) -> list[AgentConfigRevision]:
    await _get_agent_or_404(id, request=request, service=service)
    return await service.list_config_revisions(id)


@router.get(AGENT_CONFIG_REVISION_PATH)
async def get_agent_config_revision_route(
    id: str,
    revisionId: str,
    request: Request,
    _: None = Depends(require_board_access),
    service: AgentService = Depends(get_agent_service),
) -> AgentConfigRevision:
    await _get_agent_or_404(id, request=request, service=service)
    revision = await service.get_config_revision(id, revisionId)
    if revision is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Revision not found"
        )
    return revision


@router.post(AGENT_CONFIG_ROLLBACK_PATH)
async def rollback_agent_config_revision_route(
    id: str,
    revisionId: str,
    request: Request,
    _: None = Depends(require_board_access),
    service: AgentService = Depends(get_agent_service),
) -> Agent:
    await _get_agent_or_404(id, request=request, service=service)
    actor = require_actor_identity(request)
    try:
        agent = await service.rollback_config_revision(
            id, revisionId, actor_type=actor.actor_type, actor_id=actor.actor_id
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Revision not found"
        )
    return agent


@router.get(AGENT_RUNTIME_STATE_PATH)
async def get_agent_runtime_state_route(
    id: str,
    request: Request,
    _: None = Depends(require_board_access),
    service: AgentService = Depends(get_agent_service),
) -> AgentRuntimeState:
    await _get_agent_or_404(id, request=request, service=service)
    state_data = await service.get_runtime_state(id)
    if state_data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found"
        )
    return state_data


@router.get(AGENT_TASK_SESSIONS_PATH)
async def list_agent_task_sessions_route(
    id: str,
    request: Request,
    _: None = Depends(require_board_access),
    service: AgentService = Depends(get_agent_service),
) -> list[AgentTaskSession]:
    await _get_agent_or_404(id, request=request, service=service)
    return await service.list_task_sessions(id)


@router.post(AGENT_RESET_SESSION_PATH)
async def reset_agent_runtime_session_route(
    id: str,
    request: Request,
    body: dict[str, Any] = Body(...),
    _: None = Depends(require_board_access),
    service: AgentService = Depends(get_agent_service),
) -> ResetAgentSessionResult:
    await _get_agent_or_404(id, request=request, service=service)
    try:
        payload = validate_reset_agent_session(body)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    actor = require_actor_identity(request)
    result = await service.reset_runtime_session(
        id, payload, actor_type=actor.actor_type, actor_id=actor.actor_id
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found"
        )
    return result


@router.get(AGENT_SKILLS_PATH)
async def get_agent_skills_route(
    id: str,
    request: Request,
    _: None = Depends(require_board_access),
    service: AgentService = Depends(get_agent_service),
) -> AgentSkillSnapshot:
    await _get_agent_or_404(id, request=request, service=service)
    snapshot = await service.get_skill_snapshot(id)
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found"
        )
    return snapshot


@router.post(AGENT_SKILLS_SYNC_PATH)
async def sync_agent_skills_route(
    id: str,
    request: Request,
    body: dict[str, Any] = Body(default={}),
    _: None = Depends(require_board_access),
    service: AgentService = Depends(get_agent_service),
) -> AgentSkillSnapshot:
    await _get_agent_or_404(id, request=request, service=service)
    try:
        payload = validate_agent_skills_sync(body)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    actor = require_actor_identity(request)
    snapshot = await service.sync_skills(
        id,
        payload["desiredSkills"],
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
    )
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found"
        )
    return snapshot


@router.post(AGENT_SKILLS_ENABLE_PATH)
async def enable_agent_skills_route(
    id: str,
    request: Request,
    body: dict[str, Any] = Body(default={}),
    _: None = Depends(require_board_access),
    service: AgentService = Depends(get_agent_service),
) -> AgentSkillSnapshot:
    await _get_agent_or_404(id, request=request, service=service)
    try:
        payload = validate_agent_skills_enable(body)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    actor = require_actor_identity(request)
    snapshot = await service.enable_skills(
        id,
        payload["skills"],
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
    )
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found"
        )
    return snapshot


@router.post(AGENT_SKILLS_PRIVATE_PATH, status_code=status.HTTP_201_CREATED)
async def create_agent_private_skill_route(
    id: str,
    request: Request,
    body: dict[str, Any] = Body(...),
    _: None = Depends(require_board_access),
    service: AgentService = Depends(get_agent_service),
) -> dict[str, Any]:
    await _get_agent_or_404(id, request=request, service=service)
    try:
        payload = validate_agent_private_skill(body)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    actor = require_actor_identity(request)
    try:
        entry = await service.create_private_skill(
            id,
            payload,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
        )
    except AgentConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found"
        )
    return entry


@router.get(AGENT_SKILLS_ANALYTICS_PATH)
async def get_agent_skills_analytics_route(
    id: str,
    request: Request,
    windowDays: int = 30,
    _: None = Depends(require_board_access),
    service: AgentService = Depends(get_agent_service),
) -> AgentSkillAnalytics:
    await _get_agent_or_404(id, request=request, service=service)
    analytics = await service.get_skill_analytics(id, window_days=windowDays)
    if analytics is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found"
        )
    return analytics


async def _invoke_agent(
    id: str,
    request: Request,
    body: dict[str, Any],
    *,
    service: AgentService,
    heartbeat: HeartbeatService,
) -> HeartbeatRun | dict[str, str]:
    await _get_agent_or_404(id, request=request, service=service)
    actor = require_actor_identity(request)
    if actor.actor_type == "agent" and actor.actor_id != id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Agent can only invoke itself",
        )
    try:
        payload = validate_wake_agent(body)
        run = await heartbeat.wakeup(
            id,
            payload,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            execute_immediately=False,
        )
    except AgentConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    if run is None:
        return {"status": "skipped"}
    await heartbeat.record_invoked_activity(
        run, actor_type=actor.actor_type, actor_id=actor.actor_id
    )
    if run["status"] == "queued":
        _schedule_dispatch(request, id)
    return run


@router.post(AGENT_WAKEUP_PATH, status_code=status.HTTP_202_ACCEPTED)
async def wake_agent_route(
    id: str,
    request: Request,
    body: dict[str, Any] = Body(default={}),
    service: AgentService = Depends(get_agent_service),
    heartbeat: HeartbeatService = Depends(get_heartbeat_service),
) -> HeartbeatRun | dict[str, str]:
    return await _invoke_agent(
        id,
        request,
        body,
        service=service,
        heartbeat=heartbeat,
    )


@router.post(AGENT_HEARTBEAT_INVOKE_PATH, status_code=status.HTTP_202_ACCEPTED)
async def invoke_agent_heartbeat_route(
    id: str,
    request: Request,
    service: AgentService = Depends(get_agent_service),
    heartbeat: HeartbeatService = Depends(get_heartbeat_service),
) -> HeartbeatRun | dict[str, str]:
    return await _invoke_agent(
        id,
        request,
        {},
        service=service,
        heartbeat=heartbeat,
    )


@router.get(ORG_HEARTBEAT_RUNS_PATH)
async def list_heartbeat_runs_route(
    orgId: str,
    agentId: str | None = None,
    _: None = Depends(require_organization_access),
    heartbeat: HeartbeatService = Depends(get_heartbeat_service),
) -> list[HeartbeatRun]:
    return await heartbeat.list_for_org(orgId, agentId)


@router.get(HEARTBEAT_RUN_PATH)
async def get_heartbeat_run_route(
    runId: str,
    request: Request,
    heartbeat: HeartbeatService = Depends(get_heartbeat_service),
) -> HeartbeatRun:
    run = await heartbeat.get(runId)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Heartbeat run not found"
        )
    assert_organization_access(request, run["orgId"])
    return run


@router.get(HEARTBEAT_RUN_EVENTS_PATH)
async def list_heartbeat_run_events_route(
    runId: str,
    request: Request,
    afterSeq: int = 0,
    limit: int = 200,
    heartbeat: HeartbeatService = Depends(get_heartbeat_service),
) -> list[HeartbeatRunEvent]:
    run = await heartbeat.get(runId)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Heartbeat run not found"
        )
    assert_organization_access(request, run["orgId"])
    return await heartbeat.list_events(runId, after_seq=afterSeq, limit=limit)


@router.get(HEARTBEAT_RUN_LOG_PATH)
async def get_heartbeat_run_log_route(
    runId: str,
    request: Request,
    offset: int = 0,
    limitBytes: int = 256_000,
    heartbeat: HeartbeatService = Depends(get_heartbeat_service),
) -> JSONResponse:
    run = await heartbeat.get(runId)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Heartbeat run not found"
        )
    assert_organization_access(request, run["orgId"])
    log = await heartbeat.read_log(runId, offset=offset, limit_bytes=limitBytes)
    assert log is not None
    return JSONResponse(
        log,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@router.get(HEARTBEAT_RUN_WORKSPACE_OPERATIONS_PATH)
async def list_heartbeat_run_workspace_operations_route(
    runId: str,
    request: Request,
    heartbeat: HeartbeatService = Depends(get_heartbeat_service),
    workspaces: WorkspaceService = Depends(get_workspace_service),
) -> list[WorkspaceOperation]:
    run = await heartbeat.get(runId)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Heartbeat run not found"
        )
    assert_organization_access(request, run["orgId"])
    return await workspaces.list_operations_for_run(runId)


@router.post(HEARTBEAT_RUN_CANCEL_PATH)
async def cancel_heartbeat_run_route(
    runId: str,
    request: Request,
    _: None = Depends(require_board_access),
    heartbeat: HeartbeatService = Depends(get_heartbeat_service),
) -> HeartbeatRun:
    existing = await heartbeat.get(runId)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Heartbeat run not found"
        )
    assert_organization_access(request, existing["orgId"])
    run = await heartbeat.cancel_run(runId)
    assert run is not None
    actor = require_actor_identity(request)
    await heartbeat.record_run_activity(
        run,
        action="heartbeat.cancelled",
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
    )
    return run


@router.post(HEARTBEAT_RUN_RETRY_PATH)
async def retry_heartbeat_run_route(
    runId: str,
    request: Request,
    _: None = Depends(require_board_access),
    heartbeat: HeartbeatService = Depends(get_heartbeat_service),
) -> HeartbeatRun:
    original = await heartbeat.get(runId)
    if original is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Heartbeat run not found"
        )
    assert_organization_access(request, original["orgId"])
    actor = require_actor_identity(request)
    try:
        run = await heartbeat.retry_run(
            runId,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            execute_immediately=False,
        )
    except AgentConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Heartbeat run not found"
        )
    await heartbeat.record_run_activity(
        run,
        action="heartbeat.retried",
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
    )
    _schedule_dispatch(request, run["agentId"])
    return run
