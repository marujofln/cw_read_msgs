"""Webhook endpoint that receives Chatwoot events.

Layer 1: When an agent sends a reply (message_created, message_type=outgoing),
fetch unread incoming messages and mark them as read on WhatsApp via Evolution API.
"""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Request, Response

from app.models import ChatwootWebhookPayload

logger = logging.getLogger(__name__)

router = APIRouter()

# Match WhatsApp JID formats: 5511999999999@s.whatsapp.net or 54958938411215@lid
_JID_RE = re.compile(r"^(\d+)(?::\d+)?@(s\.whatsapp\.net|lid)$")


def _ensure_jid(value: str) -> str:
    """Ensure value is a full WhatsApp JID (add @s.whatsapp.net if plain digits)."""
    if "@" in value:
        return value
    if value.isdigit():
        return f"{value}@s.whatsapp.net"
    return value


@router.post("/chatwoot-webhook")
async def chatwoot_webhook(request: Request) -> Response:
    """Receive Chatwoot webhooks and mark WhatsApp messages as read when agents reply.

    Processes message_created events with message_type=outgoing (agent reply).
    Fetches incoming messages from the conversation, extracts their WhatsApp
    message IDs (source_id), and calls Evolution API to send read receipts.
    """
    body = await request.json()

    event = body.get("event", "")
    if event != "message_created":
        return Response(
            content='{"status":"ignored","reason":"not message_created"}',
            media_type="application/json",
        )

    message_type = body.get("message_type", "")
    if message_type != "outgoing":
        return Response(
            content='{"status":"ignored","reason":"not outgoing message"}',
            media_type="application/json",
        )

    logger.debug("Chatwoot webhook message_created outgoing: %s", body)

    try:
        payload = ChatwootWebhookPayload(**body)
    except Exception:
        logger.warning(
            "Could not parse Chatwoot webhook payload — raw: %s",
            {k: v for k, v in body.items() if k != "content"},
        )
        return Response(
            content='{"status":"ignored","reason":"unparseable payload"}',
            media_type="application/json",
        )

    if not payload.account or not payload.inbox or not payload.conversation:
        return Response(
            content='{"status":"ignored","reason":"missing account/inbox/conversation"}',
            media_type="application/json",
        )

    inbox_name = payload.inbox.name
    if not inbox_name:
        logger.warning("Chatwoot webhook: inbox has no name")
        return Response(
            content='{"status":"ignored","reason":"inbox has no name"}',
            media_type="application/json",
        )

    chatwoot_client = request.app.state.chatwoot_client
    evolution_client = request.app.state.evolution_client

    if evolution_client is None:
        logger.warning(
            "Evolution API not configured — cannot send read receipts for inbox '%s'",
            inbox_name,
        )
        return Response(
            content='{"status":"error","reason":"evolution_api_not_configured"}',
            media_type="application/json",
        )

    # Resolve inbox -> Evolution instance name (inbox name = instance name)
    resolved = await chatwoot_client.resolve_inbox(inbox_name)
    if resolved is None:
        logger.warning(
            "Inbox '%s' not in inbox map — skipping read receipt",
            inbox_name,
        )
        return Response(
            content=f'{{"status":"ignored","reason":"unknown inbox: {inbox_name}"}}',
            media_type="application/json",
        )

    account_id, inbox_id, _ = resolved
    conv = payload.conversation
    conversation_id = conv.id

    # Get contact's WhatsApp JID (source_id)
    remote_jid: str | None = None
    if conv.contact_inbox and conv.contact_inbox.source_id:
        remote_jid = _ensure_jid(conv.contact_inbox.source_id)
    if not remote_jid and payload.contact:
        contact_id = payload.contact.id
        remote_jid = await chatwoot_client.get_contact_whatsapp_jid(
            account_id, contact_id, inbox_id,
        )
        if remote_jid:
            remote_jid = _ensure_jid(remote_jid)
    if not remote_jid:
        remote_jid = await chatwoot_client.get_conversation_source_id(
            account_id, conversation_id,
        )
        if remote_jid:
            remote_jid = _ensure_jid(remote_jid)

    if not remote_jid:
        logger.warning(
            "Could not resolve WhatsApp JID for conversation %d (inbox %s)",
            conversation_id,
            inbox_name,
        )
        return Response(
            content='{"status":"ignored","reason":"no_whatsapp_jid"}',
            media_type="application/json",
        )

    if not _JID_RE.match(remote_jid):
        logger.warning("Invalid JID format: %s", remote_jid)
        return Response(
            content='{"status":"ignored","reason":"invalid_jid"}',
            media_type="application/json",
        )

    # Fetch incoming messages and collect source_id (WhatsApp message IDs)
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
        return Response(
            content='{"status":"ok","marked":0}',
            media_type="application/json",
        )

    success = await evolution_client.mark_messages_as_read(
        instance_name=inbox_name,
        remote_jid=remote_jid,
        message_ids=message_ids,
    )

    if success:
        logger.info(
            "Marked %d message(s) as read on WhatsApp for conversation %d (inbox %s)",
            len(message_ids),
            conversation_id,
            inbox_name,
        )

    return Response(
        content=(
            f'{{"status":"ok","marked":{len(message_ids)},'
            f'"evolution_success":{str(success).lower()}}}'
        ),
        media_type="application/json",
    )
