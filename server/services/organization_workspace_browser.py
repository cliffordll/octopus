from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import mimetypes
from typing import Literal, TypedDict
from urllib.parse import urlencode
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.organizations import get_organization_by_id

from .workspace_paths import organization_workspace_root

MAX_PREVIEW_BYTES = 200_000
HIDDEN_WORKSPACE_ENTRY_NAMES = {".DS_Store", ".cache", ".npm", ".nvm"}
TEXT_CONTENT_TYPES = {
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
    ".json": "application/json",
    ".csv": "text/csv",
    ".html": "text/html",
    ".htm": "text/html",
}
IMAGE_CONTENT_TYPES = {
    ".avif": "image/avif",
    ".bmp": "image/bmp",
    ".gif": "image/gif",
    ".ico": "image/x-icon",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
}
BINARY_CONTENT_TYPES = {
    ".pdf": "application/pdf",
}


class OrganizationWorkspaceFileEntry(TypedDict):
    name: str
    path: str
    isDirectory: bool


class OrganizationWorkspaceFileList(TypedDict):
    source: str
    rootPath: str
    repoUrl: None
    directoryPath: str
    rootExists: bool
    entries: list[OrganizationWorkspaceFileEntry]
    message: str | None


class OrganizationWorkspaceFileDetail(TypedDict):
    source: str
    rootPath: str
    repoUrl: None
    filePath: str
    rootExists: bool
    content: str | None
    contentType: str | None
    previewKind: Literal["text", "image", "binary"]
    contentPath: str | None
    message: str | None
    truncated: bool


@dataclass(frozen=True)
class OrganizationWorkspaceAttachmentFile:
    normalized_path: str
    original_filename: str
    content_type: str
    content: bytes


@dataclass(frozen=True)
class OrganizationWorkspaceArchiveFile:
    normalized_path: str
    original_filename: str
    content_type: str
    content: bytes


class OrganizationWorkspaceBrowserService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_files(
        self, org_id: str, directory_path: str = ""
    ) -> OrganizationWorkspaceFileList:
        root = await self._resolve_workspace_root(org_id)
        target, normalized = _resolve_within_root(root, directory_path)
        if not root.is_dir():
            return _missing_root_list(root)
        if not target.is_dir():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Directory not found inside the organization workspace",
            )

        entries: list[OrganizationWorkspaceFileEntry] = []
        for child in target.iterdir():
            if child.name in HIDDEN_WORKSPACE_ENTRY_NAMES:
                continue
            rel_path = _to_portable_path(child.relative_to(root))
            entries.append(
                {
                    "name": child.name,
                    "path": rel_path,
                    "isDirectory": child.is_dir(),
                }
            )
        entries.sort(key=lambda item: (not item["isDirectory"], item["name"].lower()))
        return {
            "source": "org_root",
            "rootPath": str(root),
            "repoUrl": None,
            "directoryPath": normalized,
            "rootExists": True,
            "entries": entries,
            "message": "This folder is empty." if not entries else None,
        }

    async def read_file(
        self, org_id: str, file_path: str
    ) -> OrganizationWorkspaceFileDetail:
        root = await self._resolve_workspace_root(org_id)
        target, normalized = _resolve_within_root(root, file_path)
        if not root.is_dir():
            return _missing_root_detail(root, normalized)
        if not target.is_file():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="File not found inside the organization workspace",
            )

        content = target.read_bytes()
        content_type = _content_type(normalized or str(target), content)
        preview_kind = _preview_kind(content_type, content)
        if preview_kind == "image":
            return {
                "source": "org_root",
                "rootPath": str(root),
                "repoUrl": None,
                "filePath": normalized,
                "rootExists": True,
                "content": None,
                "contentType": content_type,
                "previewKind": "image",
                "contentPath": _content_path(org_id, normalized),
                "message": None,
                "truncated": False,
            }
        if preview_kind == "binary":
            return {
                "source": "org_root",
                "rootPath": str(root),
                "repoUrl": None,
                "filePath": normalized,
                "rootExists": True,
                "content": None,
                "contentType": content_type,
                "previewKind": "binary",
                "contentPath": None,
                "message": "Binary files are not previewed in the organization workspace view.",
                "truncated": False,
            }

        truncated = len(content) > MAX_PREVIEW_BYTES
        return {
            "source": "org_root",
            "rootPath": str(root),
            "repoUrl": None,
            "filePath": normalized,
            "rootExists": True,
            "content": content[:MAX_PREVIEW_BYTES].decode("utf-8", errors="replace"),
            "contentType": content_type,
            "previewKind": "text",
            "contentPath": None,
            "message": "Preview truncated to the first 200 KB." if truncated else None,
            "truncated": truncated,
        }

    async def read_attachment_file(
        self, org_id: str, file_path: str
    ) -> OrganizationWorkspaceAttachmentFile:
        root = await self._resolve_workspace_root(org_id)
        target, normalized = _resolve_within_root(root, file_path)
        if not root.is_dir():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="The workspace root is not available on this machine yet.",
            )
        if not target.is_file():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="File not found inside the organization workspace",
            )
        content = target.read_bytes()
        return OrganizationWorkspaceAttachmentFile(
            normalized_path=normalized,
            original_filename=target.name,
            content_type=_content_type(normalized or str(target), content),
            content=content,
        )

    async def read_archive_file(
        self, org_id: str, requested_path: str
    ) -> OrganizationWorkspaceArchiveFile:
        root = await self._resolve_workspace_root(org_id)
        target, normalized = _resolve_within_root(root, requested_path)
        if not root.is_dir():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="The workspace root is not available on this machine yet.",
            )
        if not target.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Path not found inside the organization workspace",
            )
        archive = BytesIO()
        with ZipFile(archive, "w", compression=ZIP_DEFLATED) as zip_file:
            if target.is_file():
                zip_file.write(target, normalized or target.name)
            else:
                for child in sorted(target.rglob("*")):
                    if _is_hidden_workspace_path(child, root):
                        continue
                    rel_path = _to_portable_path(child.relative_to(root))
                    if child.is_dir():
                        zip_file.writestr(f"{rel_path}/", b"")
                    elif child.is_file():
                        zip_file.write(child, rel_path)
        archive_name = _archive_filename(normalized)
        return OrganizationWorkspaceArchiveFile(
            normalized_path=normalized,
            original_filename=archive_name,
            content_type="application/zip",
            content=archive.getvalue(),
        )

    async def _resolve_workspace_root(self, org_id: str) -> Path:
        organization = await get_organization_by_id(self._session, org_id)
        if organization is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organization not found",
            )
        root = organization_workspace_root(org_id)
        for child in ("agents", "skills", "plans", "artifacts"):
            (root / child).mkdir(parents=True, exist_ok=True)
        return root


def _resolve_within_root(root: Path, requested_path: str) -> tuple[Path, str]:
    raw = requested_path.strip()
    target = (root / raw).resolve() if raw else root.resolve()
    resolved_root = root.resolve()
    try:
        relative = target.relative_to(resolved_root)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Requested path must stay inside the organization workspace root",
        ) from exc
    return target, _to_portable_path(relative)


def _to_portable_path(value: Path) -> str:
    return value.as_posix() if str(value) != "." else ""


def _is_hidden_workspace_path(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    return any(part in HIDDEN_WORKSPACE_ENTRY_NAMES for part in relative.parts)


def _archive_filename(normalized_path: str) -> str:
    if not normalized_path:
        return "workspace.zip"
    name = Path(normalized_path).name or "workspace"
    return f"{name}.zip"


def _missing_root_list(root: Path) -> OrganizationWorkspaceFileList:
    return {
        "source": "org_root",
        "rootPath": str(root),
        "repoUrl": None,
        "directoryPath": "",
        "rootExists": False,
        "entries": [],
        "message": "The workspace root is not available on this machine yet.",
    }


def _missing_root_detail(
    root: Path, normalized: str
) -> OrganizationWorkspaceFileDetail:
    return {
        "source": "org_root",
        "rootPath": str(root),
        "repoUrl": None,
        "filePath": normalized,
        "rootExists": False,
        "content": None,
        "contentType": None,
        "previewKind": "binary",
        "contentPath": None,
        "message": "The workspace root is not available on this machine yet.",
        "truncated": False,
    }


def _content_type(file_path: str, content: bytes) -> str:
    suffix = Path(file_path).suffix.lower()
    mapped = (
        TEXT_CONTENT_TYPES.get(suffix)
        or IMAGE_CONTENT_TYPES.get(suffix)
        or BINARY_CONTENT_TYPES.get(suffix)
    )
    if mapped:
        return mapped
    guessed, _ = mimetypes.guess_type(file_path)
    if guessed:
        return guessed
    return "application/octet-stream" if _has_binary_bytes(content) else "text/plain"


def _preview_kind(
    content_type: str, content: bytes
) -> Literal["text", "image", "binary"]:
    if content_type.lower().startswith("image/"):
        return "image"
    if _has_binary_bytes(content):
        return "binary"
    return "text"


def _has_binary_bytes(content: bytes) -> bool:
    return b"\x00" in content


def _content_path(org_id: str, normalized_path: str) -> str:
    return f"/api/orgs/{org_id}/workspace/file/content?{urlencode({'path': normalized_path})}"
