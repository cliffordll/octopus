from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class _ActiveChatGeneration:
    token: object
    cancel_event: asyncio.Event


_ACTIVE_GENERATIONS: dict[str, _ActiveChatGeneration] = {}


def claim_chat_generation(
    conversation_id: str,
    cancel_event: asyncio.Event,
) -> Callable[[], None] | None:
    if conversation_id in _ACTIVE_GENERATIONS:
        return None

    token = object()
    _ACTIVE_GENERATIONS[conversation_id] = _ActiveChatGeneration(
        token=token,
        cancel_event=cancel_event,
    )

    def release() -> None:
        active = _ACTIVE_GENERATIONS.get(conversation_id)
        if active is not None and active.token is token:
            _ACTIVE_GENERATIONS.pop(conversation_id, None)

    return release


def has_active_chat_generation(conversation_id: str) -> bool:
    return conversation_id in _ACTIVE_GENERATIONS


def cancel_active_chat_generation(conversation_id: str) -> bool:
    active = _ACTIVE_GENERATIONS.get(conversation_id)
    if active is None:
        return False
    active.cancel_event.set()
    return True


def _clear_chat_generations_for_tests() -> None:
    _ACTIVE_GENERATIONS.clear()
