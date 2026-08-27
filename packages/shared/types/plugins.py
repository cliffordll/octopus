from __future__ import annotations

from typing import Any, NotRequired, TypedDict

from ..constants.plugins import PluginCapability, PluginUiSlotType


class PluginEntrypoints(TypedDict, total=False):
    worker: str
    ui: str


class PluginUiSlot(TypedDict, total=False):
    type: PluginUiSlotType
    id: str
    displayName: str
    exportName: str
    routePath: str
    entityTypes: list[str]
    order: int


class PluginUi(TypedDict, total=False):
    slots: list[PluginUiSlot]
    launchers: list[dict[str, Any]]


class PluginJobManifest(TypedDict, total=False):
    jobKey: str
    displayName: str
    description: str
    schedule: str


class PluginWebhookManifest(TypedDict, total=False):
    endpointKey: str
    displayName: str
    description: str


class PluginToolManifest(TypedDict, total=False):
    name: str
    displayName: str
    description: str
    parametersSchema: dict[str, Any]


class PluginManifest(TypedDict):
    id: str
    apiVersion: int
    version: str
    displayName: str
    description: NotRequired[str]
    author: NotRequired[str]
    categories: NotRequired[list[str]]
    capabilities: list[PluginCapability]
    entrypoints: PluginEntrypoints
    instanceConfigSchema: NotRequired[dict[str, Any]]
    ui: NotRequired[PluginUi]
    jobs: NotRequired[list[PluginJobManifest]]
    webhooks: NotRequired[list[PluginWebhookManifest]]
    tools: NotRequired[list[PluginToolManifest]]
