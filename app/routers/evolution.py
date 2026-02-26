"""Webhook endpoint that receives Evolution API events."""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Request, Response

from app.models import EvolutionWebhookPayload, MessageStatus, MessageUpdateData
from app.services.redis_client import push_conversation_read_broadcast

logger = logging.getLogger(__name__)

router = APIRouter()

_JID_RE = re.compile(r"^(\d+)(?::\d+)?@(s\.whatsapp\.net|lid)$")


def _extract_contact_id(remote_jid: str) -> tuple[str, str] | None:
    """Extract the numeric identifier and JID type from a WhatsApp JID.

    Supports standard phone JIDs (``<phone>@s.whatsapp.net``),
    plain Linked-ID JIDs (``<lid>@lid``), and device-suffixed
    LIDs (``<lid>:<device>@lid``).

    Returns ``(numeric_id, jid_type)`` or ``None``.
    """
    match = _JID_RE.match(remote_jid)
    if not match:
        return None
    return match.group(1), match.group(2)


def _is_incoming_read(entry: MessageUpdateData) -> bool:
    """Return True when the entry represents an incoming message we read."""
    if entry.from_me:
        return False
    return MessageStatus.is_read(entry.status)


@router.post("/evolution-webhook")
async def evolution_webhook(request: Request) -> Response:
    """Receive an Evolution API webhook and mark Chatwoot conversations as read.

    Only processes ``messages.update`` events where an incoming message
    (``fromMe=false``) transitions to read status (``status >= READ``).
    """
    body = await request.json()

    event = body.get("event", "")
    if event != "messages.update":
        return Response(
            content='{"status":"ignored","reason":"not messages.update"}',
            media_type="application/json",
        )

    logger.debug("Raw messages.update payload: %s", body)

    try:
        payload = EvolutionWebhookPayload(**body)
    except Exception:
        logger.warning(
            "Could not parse messages.update payload — raw data: %s",
            body.get("data"),
        )
        return Response(
            content='{"status":"ignored","reason":"unrecognised payload shape"}',
            media_type="application/json",
        )

    instance_name = payload.instance
    chatwoot_client = request.app.state.chatwoot_client
    evolution_client = request.app.state.evolution_client

    account_id = await chatwoot_client.resolve_account_id(instance_name)
    if account_id is None:
        logger.warning(
            "Instance '%s' not found in any Chatwoot account", instance_name,
        )
        return Response(
            content=(
                f'{{"status":"ignored",'
                f'"reason":"unknown instance: {instance_name}"}}'
            ),
            media_type="application/json",
        )

    processed = 0

    for entry in payload.entries():
        if not _is_incoming_read(entry):
            continue

        extracted = _extract_contact_id(entry.remote_jid)
        if extracted is None:
            logger.warning(
                "Unsupported JID format: %s", entry.remote_jid,
            )
            continue

        numeric_id, jid_type = extracted

        logger.info(
            "Read receipt: instance=%s account=%d jid=%s type=%s msg_id=%s",
            instance_name,
            account_id,
            numeric_id,
            jid_type,
            entry.key_id,
        )

        search_query = numeric_id
        search_jid = entry.remote_jid

        if jid_type == "lid":
            if evolution_client is not None:
                logger.debug(
                    "Calling Evolution API to resolve LID %s for instance %s",
                    entry.remote_jid,
                    instance_name,
                )
                phone_jid = await evolution_client.resolve_lid_to_phone(
                    instance_name, entry.remote_jid,
                )
                if phone_jid:
                    phone_number = phone_jid.split("@")[0]
                    logger.info(
                        "Resolved LID %s -> phone %s for Chatwoot search",
                        entry.remote_jid,
                        phone_jid,
                    )
                    search_query = phone_number
                    search_jid = phone_jid
                else:
                    logger.debug(
                        "Evolution API returned no phone mapping for LID %s",
                        entry.remote_jid,
                    )
            else:
                logger.debug(
                    "Evolution client not configured, skipping LID resolution for %s",
                    entry.remote_jid,
                )

        resolved_inbox = await chatwoot_client.resolve_inbox(instance_name)
        inbox_id: int | None = None
        inbox_identifier: str | None = None
        if resolved_inbox is not None:
            _, inbox_id, inbox_identifier = resolved_inbox

        contact_id = await chatwoot_client.search_contact(
            account_id,
            search_query,
            jid_type=jid_type,
            remote_jid=search_jid,
        )
        if contact_id is None:
            if jid_type == "lid" and resolved_inbox is not None:
                acc_id, inb_id, inb_ident = resolved_inbox
                conv_id = (
                    await chatwoot_client.find_conversation_by_contact_source_id(
                        acc_id, inb_id, search_jid,
                    )
                )
                if conv_id is not None:
                    success = await chatwoot_client.mark_conversation_read(
                        account_id, conv_id,
                    )
                    if success:
                        processed += 1
                        redis_client = getattr(
                            request.app.state, "redis_client", None
                        )
                        await push_conversation_read_broadcast(
                            redis_client, account_id, conv_id
                        )
                    continue
            logger.warning(
                "No Chatwoot contact found for %s (instance=%s, jid_type=%s)",
                search_query,
                instance_name,
                jid_type,
            )
            continue

        conv_result = await chatwoot_client.find_open_conversation(
            account_id, contact_id, instance_name, inbox_id=inbox_id,
        )
        if conv_result is None:
            logger.warning(
                "No Chatwoot conversation for contact %d in inbox '%s'",
                contact_id,
                instance_name,
            )
            continue

        conv_id, source_id = conv_result

        # Fetch source_id from contact details if not found in conversation list
        if source_id is None and inbox_id is not None:
            source_id = await chatwoot_client.get_contact_source_id(
                account_id, contact_id, inbox_id,
            )
            if source_id:
                logger.debug(
                    "Fetched source_id '%s' from contact %d for inbox %d",
                    source_id,
                    contact_id,
                    inbox_id,
                )

        # Fallback: fetch source_id from conversation details API
        if source_id is None:
            source_id = await chatwoot_client.get_conversation_source_id(
                account_id, conv_id,
            )
            if source_id:
                logger.debug(
                    "Fetched source_id '%s' from conversation %d details",
                    source_id,
                    conv_id,
                )

        success = await chatwoot_client.mark_conversation_read(
            account_id,
            conv_id,
            inbox_identifier=inbox_identifier,
            source_id=source_id,
        )
        if success:
            processed += 1
            redis_client = getattr(request.app.state, "redis_client", None)
            await push_conversation_read_broadcast(
                redis_client, account_id, conv_id
            )

    return Response(
        content=(
            f'{{"status":"ok","instance":"{instance_name}",'
            f'"account_id":{account_id},"processed":{processed}}}'
        ),
        media_type="application/json",
    )
