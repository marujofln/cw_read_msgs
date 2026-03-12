"""Tests for the Chatwoot webhook endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.main import app


def _make_message_created_payload(
    *,
    message_type: str = "outgoing",
    inbox_name: str = "shop-wa",
    conversation_id: int = 100,
    account_id: int = 1,
    inbox_id: int = 10,
    source_id: str = "5511999999999@s.whatsapp.net",
) -> dict:
    """Build a valid Chatwoot message_created webhook body."""
    return {
        "event": "message_created",
        "message_type": message_type,
        "account": {"id": account_id},
        "inbox": {"id": inbox_id, "name": inbox_name},
        "conversation": {
            "id": conversation_id,
            "contact_inbox": {"source_id": source_id},
            "meta": {},
        },
        "contact": {"id": 42},
    }


@pytest.fixture()
def client() -> TestClient:
    mock_chatwoot = AsyncMock()
    mock_chatwoot.resolve_inbox.return_value = (1, 10, "inbox-identifier")
    mock_chatwoot.get_contact_whatsapp_jid.return_value = None
    mock_chatwoot.get_conversation_source_id.return_value = None
    mock_chatwoot.get_conversation_messages.return_value = [
        {"id": 1, "message_type": "incoming", "source_id": "MSG001"},
        {"id": 2, "message_type": "incoming", "source_id": "MSG002"},
    ]
    mock_evolution = AsyncMock()
    mock_evolution.mark_messages_as_read.return_value = True

    app.state.chatwoot_client = mock_chatwoot
    app.state.evolution_client = mock_evolution
    return TestClient(app, raise_server_exceptions=False)


class TestChatwootWebhook:
    """Integration tests for POST /chatwoot-webhook."""

    def test_ignores_non_message_created(self, client: TestClient) -> None:
        resp = client.post(
            "/chatwoot-webhook",
            json={"event": "conversation_updated"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ignored"
        assert "not message_created" in resp.json()["reason"]

    def test_ignores_incoming_message(self, client: TestClient) -> None:
        resp = client.post(
            "/chatwoot-webhook",
            json=_make_message_created_payload(message_type="incoming"),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ignored"
        assert "not outgoing" in resp.json()["reason"]

    def test_ignores_when_evolution_not_configured(self, client: TestClient) -> None:
        app.state.evolution_client = None
        resp = client.post(
            "/chatwoot-webhook",
            json=_make_message_created_payload(),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "error"
        assert "evolution" in resp.json()["reason"]

    def test_ignores_unknown_inbox(self, client: TestClient) -> None:
        mock_cw = app.state.chatwoot_client
        mock_cw.resolve_inbox.return_value = None

        resp = client.post(
            "/chatwoot-webhook",
            json=_make_message_created_payload(inbox_name="unknown-inbox"),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ignored"
        assert "unknown inbox" in resp.json()["reason"]

    def test_processes_outgoing_and_marks_read(
        self,
        client: TestClient,
    ) -> None:
        mock_cw = app.state.chatwoot_client
        mock_evo = app.state.evolution_client

        resp = client.post(
            "/chatwoot-webhook",
            json=_make_message_created_payload(
                inbox_name="shop-wa",
                source_id="5511999999999@s.whatsapp.net",
            ),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["marked"] == 2
        assert body["evolution_success"] is True

        mock_cw.resolve_inbox.assert_called_once_with("shop-wa")
        mock_cw.get_conversation_messages.assert_called_once_with(
            1, 100, message_type="incoming"
        )
        mock_evo.mark_messages_as_read.assert_called_once_with(
            instance_name="shop-wa",
            remote_jid="5511999999999@s.whatsapp.net",
            message_ids=["MSG001", "MSG002"],
        )

    def test_returns_ok_when_no_incoming_messages(self, client: TestClient) -> None:
        mock_cw = app.state.chatwoot_client
        mock_cw.get_conversation_messages.return_value = []

        resp = client.post(
            "/chatwoot-webhook",
            json=_make_message_created_payload(),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["marked"] == 0
