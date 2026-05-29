from __future__ import annotations

from typing import NotRequired, TypedDict


class LogReadResult(TypedDict):
    content: str
    endOffset: int
    eof: bool
    nextOffset: NotRequired[int]
