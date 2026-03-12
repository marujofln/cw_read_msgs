"""Tests for Evolution API and Chatwoot webhook payload parsing."""

from __future__ import annotations

from app.models import (
    ChatwootWebhookPayload,
    EvolutionWebhookPayload,
    MessageStatus,
    PgNotifyConversationRead,
)


class TestEvolutionWebhookPayload:
    """Verify that various payload shapes are parsed correctly."""

    def test_single_entry(self) -> None:
        raw = {
            "event": "messages.update",
            "instance": "my-instance",
            "data": {
                "keyId": "ABC123",
                "remoteJid": "5511999999999@s.whatsapp.net",
                "fromMe": False,
                "status": "READ",
                "instanceId": "uuid-1",
            },
        }
        payload = EvolutionWebhookPayload(**raw)

        assert payload.event == "messages.update"
        assert payload.instance == "my-instance"

        entries = payload.entries()
        assert len(entries) == 1
        assert entries[0].remote_jid == "5511999999999@s.whatsapp.net"
        assert entries[0].from_me is False
        assert entries[0].status == MessageStatus.READ
        assert entries[0].key_id == "ABC123"

    def test_list_of_entries(self) -> None:
        raw = {
            "event": "messages.update",
            "instance": "shop-wa",
            "data": [
                {
                    "keyId": "MSG1",
                    "remoteJid": "5521888888888@s.whatsapp.net",
                    "fromMe": False,
                    "status": "READ",
                },
                {
                    "keyId": "MSG2",
                    "remoteJid": "5521888888888@s.whatsapp.net",
                    "fromMe": False,
                    "status": "PLAYED",
                },
            ],
        }
        payload = EvolutionWebhookPayload(**raw)
        entries = payload.entries()

        assert len(entries) == 2
        assert entries[0].key_id == "MSG1"
        assert entries[1].status == MessageStatus.PLAYED

    def test_outgoing_message(self) -> None:
        raw = {
            "event": "messages.update",
            "instance": "inst",
            "data": {
                "keyId": "OUT1",
                "remoteJid": "5511000000000@s.whatsapp.net",
                "fromMe": True,
                "status": "DELIVERY_ACK",
            },
        }
        payload = EvolutionWebhookPayload(**raw)
        entries = payload.entries()

        assert entries[0].from_me is True
        assert entries[0].status == MessageStatus.DELIVERY_ACK

    def test_is_read_classmethod(self) -> None:
        assert MessageStatus.is_read("READ") is True
        assert MessageStatus.is_read("PLAYED") is True
        assert MessageStatus.is_read("DELIVERY_ACK") is False
        assert MessageStatus.is_read("SERVER_ACK") is False
        assert MessageStatus.is_read("PENDING") is False


class TestChatwootWebhookPayload:
    """Verify Chatwoot webhook payload parsing."""

    def test_parses_message_created(self) -> None:
        raw = {
            "event": "message_created",
            "message_type": "outgoing",
            "account": {"id": 1},
            "inbox": {"id": 10, "name": "shop-wa"},
            "conversation": {
                "id": 100,
                "contact_inbox": {"source_id": "5511999999999@s.whatsapp.net"},
            },
            "contact": {"id": 42},
        }
        payload = ChatwootWebhookPayload(**raw)
        assert payload.event == "message_created"
        assert payload.message_type == "outgoing"
        assert payload.account and payload.account.id == 1
        assert payload.inbox and payload.inbox.name == "shop-wa"
        assert payload.conversation and payload.conversation.id == 100
        assert (
            payload.conversation.contact_inbox
            and payload.conversation.contact_inbox.source_id
            == "5511999999999@s.whatsapp.net"
        )


class TestPgNotifyConversationRead:
    """Verify PG notify payload parsing."""

    def test_parses_payload(self) -> None:
        raw = {"conversation_id": 100, "account_id": 1}
        payload = PgNotifyConversationRead(**raw)
        assert payload.conversation_id == 100
        assert payload.account_id == 1
