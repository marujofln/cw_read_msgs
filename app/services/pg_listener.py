"""PostgreSQL LISTEN/NOTIFY listener for Layer 2: agent views conversation.

When Chatwoot's update_last_seen updates agent_last_seen_at, a PG trigger
emits pg_notify('cw_conversation_read', json_payload). This module listens
on that channel and triggers the read receipt flow.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.chatwoot import ChatwootClient
    from app.services.evolution import EvolutionClient

logger = logging.getLogger(__name__)

CHANNEL = "cw_conversation_read"


async def run_pg_listener(
    database_url: str,
    chatwoot_client: ChatwootClient,
    evolution_client: EvolutionClient | None,
) -> None:
    """Listen on cw_conversation_read and mark WhatsApp messages as read.

    Runs until cancelled. Reconnects on connection loss.
    """
    import asyncpg

    while True:
        try:
            conn = await asyncpg.connect(database_url)
            await conn.add_listener(CHANNEL, _make_notify_callback(chatwoot_client, evolution_client))
            logger.info("PG listener connected, listening on channel '%s'", CHANNEL)
            # Wait indefinitely; the listener callback handles notifications
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            logger.info("PG listener cancelled")
            if "conn" in dir() and conn is not None:
                await conn.close()
            raise
        except Exception:
            logger.exception("PG listener error, reconnecting in 5s")
            await asyncio.sleep(5)


def _make_notify_callback(chatwoot_client: ChatwootClient, evolution_client: EvolutionClient | None):
    """Build a callback that handles NOTIFY payloads.

    asyncpg invokes this callback synchronously; we schedule async work via
    create_task to avoid blocking the connection.
    """

    def _on_notify(connection, pid, channel, payload):
        if channel != CHANNEL or not payload:
            return
        if evolution_client is None:
            logger.debug("PG notify received but Evolution API not configured, skipping")
            return
        try:
            data = json.loads(payload)
            conversation_id = data.get("conversation_id")
            account_id = data.get("account_id")
            if not conversation_id or not account_id:
                logger.warning("Invalid PG notify payload: %s", payload)
                return
            asyncio.create_task(
                _handle_conversation_read(
                    chatwoot_client,
                    evolution_client,
                    account_id=int(account_id),
                    conversation_id=int(conversation_id),
                ),
            )
        except json.JSONDecodeError as e:
            logger.warning("Invalid JSON in PG notify: %s", e)
        except Exception:
            logger.exception("Error handling PG notify payload: %s", payload)

    return _on_notify


async def _handle_conversation_read(
    chatwoot_client: ChatwootClient,
    evolution_client: EvolutionClient,
    *,
    account_id: int,
    conversation_id: int,
) -> None:
    """Resolve conversation to inbox/JID, fetch messages, mark as read on WhatsApp."""
    # Get conversation details to find inbox and contact
    source_id = await chatwoot_client.get_conversation_source_id(
        account_id, conversation_id,
    )
    if not source_id:
        logger.debug(
            "No source_id for conversation %d (account %d)",
            conversation_id,
            account_id,
        )
        return

    # Get inbox_id for this conversation and resolve to Evolution instance name
    inbox_id = await chatwoot_client.get_conversation_inbox_id(
        account_id, conversation_id,
    )
    if inbox_id is None:
        logger.debug(
            "Could not get inbox_id for conversation %d",
            conversation_id,
        )
        return

    instance_name = chatwoot_client.resolve_instance_name(account_id, inbox_id)
    if not instance_name:
        logger.debug(
            "Inbox %d (account %d) not in inbox map — not an Evolution API inbox",
            inbox_id,
            account_id,
        )
        return

    # Ensure source_id is full JID
    if "@" not in source_id:
        remote_jid = f"{source_id}@s.whatsapp.net"
    else:
        remote_jid = source_id

    messages = await chatwoot_client.get_conversation_messages(
        account_id,
        conversation_id,
        message_type="incoming",
    )
    message_ids = []
    for msg in messages:
        sid = msg.get("source_id")
        if sid and isinstance(sid, str) and sid.strip():
            message_ids.append(sid.strip())

    if not message_ids:
        logger.debug(
            "No incoming messages with source_id in conversation %d",
            conversation_id,
        )
        return

    success = await evolution_client.mark_messages_as_read(
        instance_name=instance_name,
        remote_jid=remote_jid,
        message_ids=message_ids,
    )
    if success:
        logger.info(
            "PG notify: marked %d message(s) as read on WhatsApp for conversation %d",
            len(message_ids),
            conversation_id,
        )
