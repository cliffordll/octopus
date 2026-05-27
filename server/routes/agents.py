from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status

from packages.shared.api_paths.agents import (
    AGENT_CONFIGURATION_PATH,
    AGENT_CONFIG_REVISIONS_PATH,
    AGENT_CONFIG_REVISION_PATH,
    AGENT_CONFIG_ROLLBACK_PATH,
    AGENT_DETAIL_PATH,
    AGENT_PAUSE_PATH,
    AGENT_RESET_SESSION_PATH,
    AGENT_RESUME_PATH,
    AGENT_RUNTIME_STATE_PATH,
    AGENT_TASK_SESSIONS_PATH,
    AGENT_TERMINATE_PATH,
    ORG_AGENT_CONFIGURATIONS_PATH,
    ORG_AGENT_LIST_PATH,
    ORG_AGENT_NAME_SUGGESTION_PATH,
)
from packages.shared.api_paths.heartbeat import (
    AGENT_HEARTBEAT_INVOKE_PATH,
    AGENT_WAKEUP_PATH,
    HEARTBEAT_RUN_EVENTS_PATH,
    HEARTBEAT_RUN_PATH,
    ORG_HEARTBEAT_RUNS_PATH,
)
from packages.shared.types.agent import (
    Agent,
    AgentConfiguration,
    AgentConfigRevision,
    AgentDetail,
    AgentRuntimeState,
    AgentTaskSession,
    ResetAgentSessionResult,
)
from packages.shared.types.heartbeat import HeartbeatRun, HeartbeatRunEvent
from packages.shared.validators.agent import (
    validate_create_agent,
    validate_reset_agent_session,
    validate_update_agent,
)
from packages.shared.validators.heartbeat import validate_wake_agent

from ..dependencies.access import (
    assert_organization_access,
    require_actor_identity,
    require_board_access,
    require_organization_access,
)
from ..dependencies.agents import get_agent_service
from ..dependencies.heartbeat import get_heartbeat_service
from ..services.agents import AgentConflictError, AgentService
from ..services.heartbeat import HeartbeatService

router = APIRouter(tags=["agents"])


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
) -> Agent:
    return await _lifecycle_action(
        id, action="resume", request=request, service=service
    )


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


@router.get(ORG_AGENT_CONFIGURATIONS_PATH)
async def list_agent_configurations_route(
    orgId: str,
    _: None = Depends(require_board_access),
    service: AgentService = Depends(get_agent_service),
) -> list[AgentConfiguration]:
    return await service.list_configurations_for_org(orgId)


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
    if run is None:
        return {"status": "skipped"}
    await heartbeat.record_invoked_activity(
        run, actor_type=actor.actor_type, actor_id=actor.actor_id
    )
    return run


@router.post(AGENT_WAKEUP_PATH, status_code=status.HTTP_202_ACCEPTED)
async def wake_agent_route(
    id: str,
    request: Request,
    body: dict[str, Any] = Body(default={}),
    service: AgentService = Depends(get_agent_service),
    heartbeat: HeartbeatService = Depends(get_heartbeat_service),
) -> HeartbeatRun | dict[str, str]:
    return await _invoke_agent(id, request, body, service=service, heartbeat=heartbeat)


@router.post(AGENT_HEARTBEAT_INVOKE_PATH, status_code=status.HTTP_202_ACCEPTED)
async def invoke_agent_heartbeat_route(
    id: str,
    request: Request,
    service: AgentService = Depends(get_agent_service),
    heartbeat: HeartbeatService = Depends(get_heartbeat_service),
) -> HeartbeatRun | dict[str, str]:
    return await _invoke_agent(id, request, {}, service=service, heartbeat=heartbeat)


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
    heartbeat: HeartbeatService = Depends(get_heartbeat_service),
) -> list[HeartbeatRunEvent]:
    run = await heartbeat.get(runId)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Heartbeat run not found"
        )
    assert_organization_access(request, run["orgId"])
    return await heartbeat.list_events(runId)
