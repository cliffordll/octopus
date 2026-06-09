from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from packages.shared.api_paths.plugins import (
    PLUGIN_ACTION_PATH,
    PLUGIN_AVAILABLE_PATH,
    PLUGIN_CONFIG_PATH,
    PLUGIN_DATA_PATH,
    PLUGIN_DISABLE_PATH,
    PLUGIN_ENABLE_PATH,
    PLUGIN_EXAMPLES_PATH,
    PLUGIN_INSTALL_PATH,
    PLUGIN_JOB_TRIGGER_PATH,
    PLUGIN_JOBS_PATH,
    PLUGIN_LOGS_PATH,
    PLUGIN_LIST_PATH,
    PLUGIN_DETAIL_PATH,
    PLUGIN_STATIC_PATH,
    PLUGIN_UI_CONTRIBUTIONS_PATH,
    PLUGIN_UI_STREAM_PATH,
    PLUGIN_WEBHOOK_PATH,
)
from packages.shared.constants.plugins import PluginUiSlotType

from ..dependencies.database import get_session
from ..plugins.catalog import (
    DEFAULT_PLUGIN_CATALOG_ROOT,
    PluginCatalog,
    load_plugin_catalog,
)
from ..plugins.registry import PluginRegistryService
from ..plugins.ui_bridge import PluginUiBridge
from ..plugins.worker_manager import PluginWorkerManager

router = APIRouter(tags=["plugins"])


@router.get(PLUGIN_LIST_PATH)
async def list_plugins_route(
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    return await PluginRegistryService(session).list_plugins()


@router.post(PLUGIN_INSTALL_PATH, status_code=status.HTTP_201_CREATED)
async def install_plugin_route(
    body: dict[str, Any] = Body(...),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        manifest = body.get("manifest")
        if not isinstance(manifest, dict):
            raise ValueError("'manifest' is required and must be an object")
        return await PluginRegistryService(session).install_plugin(
            manifest=manifest,
            source_type=_required_body_string(body, "sourceType"),
            source_locator=_required_body_string(body, "sourceLocator"),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


@router.delete(PLUGIN_DETAIL_PATH)
async def uninstall_plugin_route(
    pluginId: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        return await PluginRegistryService(session).uninstall_plugin(pluginId)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.get(PLUGIN_AVAILABLE_PATH)
async def list_available_plugins_route(request: Request) -> dict[str, Any]:
    catalog = _load_catalog(request)
    return _catalog_response(catalog)


@router.get(PLUGIN_EXAMPLES_PATH)
async def list_example_plugins_route(request: Request) -> dict[str, Any]:
    catalog = _load_catalog(request)
    return _catalog_response(catalog, examples_only=True)


@router.post(PLUGIN_ENABLE_PATH)
async def enable_plugin_route(
    pluginId: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        return await PluginRegistryService(session).enable_plugin(pluginId)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.post(PLUGIN_DISABLE_PATH)
async def disable_plugin_route(
    pluginId: str,
    body: dict[str, Any] | None = Body(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        reason = body.get("reason") if isinstance(body, dict) else None
        return await PluginRegistryService(session).disable_plugin(
            pluginId,
            reason=reason if isinstance(reason, str) else None,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.post(PLUGIN_CONFIG_PATH)
async def save_plugin_config_route(
    pluginId: str,
    body: dict[str, Any] = Body(...),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        config_json = body.get("configJson")
        if not isinstance(config_json, dict):
            raise ValueError("'configJson' is required and must be an object")
        return await PluginRegistryService(session).upsert_config(pluginId, config_json)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.post("/api/plugins/{pluginId}/state/{key}")
async def save_plugin_state_route(
    pluginId: str,
    key: str,
    body: dict[str, Any] = Body(...),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        return await PluginRegistryService(session).set_state(
            pluginId,
            key,
            body.get("valueJson"),
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


@router.get(PLUGIN_JOBS_PATH)
async def list_plugin_jobs_route(
    pluginId: str,
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    try:
        return await PluginRegistryService(session).list_jobs(pluginId)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.post(PLUGIN_JOB_TRIGGER_PATH)
async def trigger_plugin_job_route(
    pluginId: str,
    jobId: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        return await PluginRegistryService(session).record_job_run(
            pluginId,
            jobId,
            status="queued",
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.post(PLUGIN_WEBHOOK_PATH)
async def receive_plugin_webhook_route(
    pluginId: str,
    endpointKey: str,
    body: dict[str, Any] = Body(default={}),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    service = PluginRegistryService(session)
    try:
        delivery = await service.record_webhook_delivery(
            pluginId,
            endpoint_key=endpointKey,
            request_json=body,
            status="received",
        )
        await service.add_log(
            pluginId,
            level="info",
            message="Webhook received",
            details_json={"endpointKey": endpointKey},
        )
        return delivery
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.get(PLUGIN_LOGS_PATH)
async def list_plugin_logs_route(
    pluginId: str,
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    try:
        return await PluginRegistryService(session).list_logs(pluginId)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


@router.get(PLUGIN_UI_CONTRIBUTIONS_PATH)
async def list_plugin_ui_contributions_route(
    request: Request,
    slotType: PluginUiSlotType | None = None,
    entityType: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _ui_bridge(request, session).list_contributions(
        slot_type=slotType,
        entity_type=entityType,
    )


@router.post(PLUGIN_DATA_PATH)
async def plugin_bridge_data_route(
    request: Request,
    pluginId: str,
    key: str,
    body: dict[str, Any] | None = Body(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        context = body.get("context") if isinstance(body, dict) else {}
        return await _ui_bridge(request, session).get_data(
            pluginId,
            key=key,
            context=context if isinstance(context, dict) else {},
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc


@router.post(PLUGIN_ACTION_PATH)
async def plugin_bridge_action_route(
    request: Request,
    pluginId: str,
    key: str,
    body: dict[str, Any] | None = Body(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        payload = body if isinstance(body, dict) else {}
        input_json = payload.get("input", {})
        context = payload.get("context", {})
        return await _ui_bridge(request, session).perform_action(
            pluginId,
            key=key,
            input_json=input_json if isinstance(input_json, dict) else {},
            context=context if isinstance(context, dict) else {},
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc


@router.get(PLUGIN_UI_STREAM_PATH)
async def plugin_ui_stream_route(
    request: Request,
    pluginId: str,
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    try:
        return StreamingResponse(
            _ui_bridge(request, session).stream_events(pluginId),
            media_type="text/event-stream",
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc


@router.get(PLUGIN_STATIC_PATH)
async def plugin_static_asset_route(
    request: Request,
    pluginId: str,
    assetPath: str,
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    try:
        path = await _ui_bridge(request, session).static_asset_path(
            pluginId,
            assetPath,
        )
        return FileResponse(path)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


def _load_catalog(request: Request) -> PluginCatalog:
    root = getattr(
        request.app.state,
        "plugin_catalog_root",
        DEFAULT_PLUGIN_CATALOG_ROOT,
    )
    return load_plugin_catalog(root)


def _ui_bridge(request: Request, session: AsyncSession) -> PluginUiBridge:
    worker_manager = getattr(request.app.state, "plugin_worker_manager", None)
    return PluginUiBridge(
        PluginRegistryService(session),
        worker_manager=worker_manager
        if isinstance(worker_manager, PluginWorkerManager)
        else None,
    )


def _required_body_string(body: dict[str, Any], field: str) -> str:
    value = body.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"'{field}' is required and must be a non-empty string")
    return value


def _catalog_response(
    catalog: PluginCatalog, *, examples_only: bool = False
) -> dict[str, Any]:
    entries = [
        entry for entry in catalog.entries if not examples_only or entry.example is True
    ]
    return {
        "items": [
            {
                "id": entry.plugin_id,
                "displayName": entry.display_name,
                "version": entry.version,
                "sourcePath": str(entry.source_path),
                "example": entry.example,
                "manifest": entry.manifest,
            }
            for entry in entries
        ],
        "errors": [
            {
                "id": error.plugin_id,
                "manifestPath": str(error.manifest_path),
                "message": error.message,
            }
            for error in catalog.errors
        ],
    }
