from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .access import RoleAccessService
from .service import RoleService

__all__ = [
    "ManagedRole",
    "RoleAccessService",
    "RoleManagementService",
    "RoleService",
]

if TYPE_CHECKING:
    from .management import ManagedRole, RoleManagementService


def __getattr__(name: str) -> Any:
    if name in {"ManagedRole", "RoleManagementService"}:
        from .management import ManagedRole, RoleManagementService

        return {
            "ManagedRole": ManagedRole,
            "RoleManagementService": RoleManagementService,
        }[name]
    raise AttributeError(name)
