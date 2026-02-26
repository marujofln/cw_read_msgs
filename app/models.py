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
