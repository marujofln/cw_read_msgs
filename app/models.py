"""Pydantic models for Evolution API webhook payloads."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class MessageStatus(StrEnum):
    """WhatsApp message delivery status strings sent by Evolution API v2.x."""

    PENDING = "PENDING"
    SERVER_ACK = "SERVER_ACK"
    DELIVERY_ACK = "DELIVERY_ACK"
    READ = "READ"
    PLAYED = "PLAYED"

    @classmethod
    def is_read(cls, value: str) -> bool:
        """Return True when *value* represents a read-or-later status."""
        return value in {cls.READ, cls.PLAYED}


class MessageUpdateData(BaseModel):
    """Flat payload emitted by Evolution API v2.x for ``messages.update``.

    Evolution flattens the Baileys ``{ key, update }`` pair into a single
    object before sending it over the webhook.
    """

    key_id: str = Field(alias="keyId")
    remote_jid: str = Field(alias="remoteJid")
    from_me: bool = Field(alias="fromMe")
    status: str
    participant: str | None = None
    instance_id: str | None = Field(default=None, alias="instanceId")

    model_config = {"populate_by_name": True}


class EvolutionWebhookPayload(BaseModel):
    """Top-level Evolution API webhook payload for ``messages.update``.

    Evolution may send ``data`` as a single object or as a list,
    depending on version and event batching.
    """

    event: str
    instance: str
    data: list[MessageUpdateData] | MessageUpdateData

    def entries(self) -> list[MessageUpdateData]:
        """Normalise ``data`` into a list regardless of shape."""
        if isinstance(self.data, list):
            return self.data
        return [self.data]


# ---------------------------------------------------------------------------
# Chatwoot webhook models (for message_created and related events)
# ---------------------------------------------------------------------------


class ChatwootWebhookAccount(BaseModel):
    """Account object in Chatwoot webhook payload."""

    id: int
    name: str | None = None


class ChatwootWebhookInbox(BaseModel):
    """Inbox object in Chatwoot webhook payload."""

    id: int
    name: str | None = None
    channel_type: str | None = None


class ChatwootWebhookContact(BaseModel):
    """Contact object in Chatwoot webhook payload."""

    id: int
    name: str | None = None
    identifier: str | None = None
    phone_number: str | None = None


class ChatwootWebhookContactInbox(BaseModel):
    """Contact inbox (conversation metadata) in Chatwoot webhook."""

    source_id: str | None = None


class ChatwootWebhookConversation(BaseModel):
    """Conversation object in Chatwoot webhook payload."""

    id: int
    display_id: int | None = None
    inbox_id: int | None = None
    meta: dict | None = None
    contact_inbox: ChatwootWebhookContactInbox | None = None
    messages: list[dict] | None = None


class ChatwootWebhookPayload(BaseModel):
    """Top-level Chatwoot webhook payload (e.g. message_created, conversation_updated).

    Used for Layer 1: detect agent replies and trigger WhatsApp read receipts.
    """

    event: str
    id: int | None = None
    content: str | None = None
    message_type: str | None = None
    account: ChatwootWebhookAccount | None = None
    inbox: ChatwootWebhookInbox | None = None
    contact: ChatwootWebhookContact | None = None
    conversation: ChatwootWebhookConversation | None = None


class PgNotifyConversationRead(BaseModel):
    """Payload emitted by PostgreSQL trigger on agent_last_seen_at update.

    Used for Layer 2: detect agent viewing conversation without replying.
    """

    conversation_id: int
    account_id: int
