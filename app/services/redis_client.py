"""Redis client for pushing broadcast triggers to the daemon."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

QUEUE = "cw_read_msgs:conversation_read"


async def push_conversation_read_broadcast(
    redis: Redis | None,
    account_id: int,
    conversation_id: int,
) -> None:
    """Push a message to Redis for the broadcast daemon to dispatch CONVERSATION_READ.

    Fire-and-forget: does not raise on Redis errors, only logs.
    """
    if redis is None:
        return
    try:
        payload = json.dumps({"account_id": account_id, "conversation_id": conversation_id})
        await redis.lpush(QUEUE, payload)
        logger.debug(
            "Pushed broadcast trigger account_id=%d conversation_id=%d",
            account_id,
            conversation_id,
        )
    except Exception:
        logger.exception(
            "Failed to push broadcast trigger account_id=%d conversation_id=%d",
            account_id,
            conversation_id,
        )
