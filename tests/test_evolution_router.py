"""Tests for the Evolution webhook endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client() -> TestClient:
    mock_chatwoot = AsyncMock()
    mock_chatwoot.resolve_account_id.return_value = 1
    mock_chatwoot.search_contact.return_value = None
    app.state.chatwoot_client = mock_chatwoot
    app.state.evolution_client = None
    return TestClient(app, raise_server_exceptions=False)


def _make_update_payload(
    *,
    instance: str = "test-inst",
    remote_jid: str = "5511999999999@s.whatsapp.net",
    from_me: bool = False,
    status: str = "READ",
    key_id: str = "MSG1",
) -> dict:
    """Build a valid Evolution API v2.x messages.update webhook body."""
    return {
        "event": "messages.update",
        "instance": instance,
        "data": {
            "keyId": key_id,
            "remoteJid": remote_jid,
            "fromMe": from_me,
            "status": status,
            "instanceId": "some-uuid",
        },
    }


class TestEvolutionWebhook:
    """Integration tests for POST /evolution-webhook."""

    def test_ignores_non_update_event(self, client: TestClient) -> None:
        resp = client.post(
            "/evolution-webhook",
            json={"event": "messages.upsert", "instance": "x", "data": {}},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ignored"

    def test_ignores_outgoing_message(self, client: TestClient) -> None:
        resp = client.post(
            "/evolution-webhook",
            json=_make_update_payload(from_me=True),
        )
        assert resp.status_code == 200
        assert resp.json()["processed"] == 0

    def test_ignores_low_status(self, client: TestClient) -> None:
        resp = client.post(
            "/evolution-webhook",
            json=_make_update_payload(status="DELIVERY_ACK"),
        )
        assert resp.status_code == 200
        assert resp.json()["processed"] == 0

    def test_gracefully_handles_invalid_payload(
        self,
        client: TestClient,
    ) -> None:
        resp = client.post(
            "/evolution-webhook",
            json={"event": "messages.update", "bad": "data"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ignored"

    def test_ignores_unknown_instance(self, client: TestClient) -> None:
        mock_cw = app.state.chatwoot_client
        mock_cw.resolve_account_id.return_value = None

        resp = client.post(
            "/evolution-webhook",
            json=_make_update_payload(instance="unknown-inst"),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ignored"
        assert "unknown instance" in resp.json()["reason"]

    def test_processes_valid_read_receipt(self, client: TestClient) -> None:
        mock_cw = app.state.chatwoot_client
        mock_cw.resolve_account_id.return_value = 1
        mock_cw.resolve_inbox.return_value = (1, 10, "inbox-identifier")
        mock_cw.search_contact.return_value = 42
        mock_cw.find_open_conversation.return_value = (100, "source-id-123")
        mock_cw.mark_conversation_read.return_value = True

        resp = client.post(
            "/evolution-webhook",
            json=_make_update_payload(
                instance="my-instance",
                key_id="READ1",
            ),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["processed"] == 1
        assert body["instance"] == "my-instance"
        assert body["account_id"] == 1

        mock_cw.resolve_account_id.assert_called_with("my-instance")
        mock_cw.search_contact.assert_called_once_with(
            1,
            "5511999999999",
            jid_type="s.whatsapp.net",
            remote_jid="5511999999999@s.whatsapp.net",
        )
        mock_cw.find_open_conversation.assert_called_once_with(
            1, 42, "my-instance", inbox_id=10,
        )
        mock_cw.mark_conversation_read.assert_called_once_with(
            1, 100, inbox_identifier="inbox-identifier", source_id="source-id-123",
        )

    def test_processes_lid_jid(self, client: TestClient) -> None:
        mock_cw = app.state.chatwoot_client
        mock_cw.resolve_account_id.return_value = 1
        mock_cw.resolve_inbox.return_value = (1, 10, "inbox-id")
        mock_cw.search_contact.return_value = 55
        mock_cw.find_open_conversation.return_value = (200, "source-123")
        mock_cw.mark_conversation_read.return_value = True

        resp = client.post(
            "/evolution-webhook",
            json=_make_update_payload(
                remote_jid="54958938411215@lid",
            ),
        )
        assert resp.status_code == 200
        assert resp.json()["processed"] == 1
        mock_cw.search_contact.assert_called_once_with(
            1,
            "54958938411215",
            jid_type="lid",
            remote_jid="54958938411215@lid",
        )

    def test_lid_fallback_when_search_fails(self, client: TestClient) -> None:
        mock_cw = app.state.chatwoot_client
        mock_cw.resolve_account_id.return_value = 1
        mock_cw.resolve_inbox.return_value = (1, 10, "inbox-id")
        mock_cw.search_contact.return_value = None
        mock_cw.find_conversation_by_contact_source_id.return_value = 200
        mock_cw.mark_conversation_read.return_value = True

        resp = client.post(
            "/evolution-webhook",
            json=_make_update_payload(remote_jid="54958938411215@lid"),
        )
        assert resp.status_code == 200
        assert resp.json()["processed"] == 1

        mock_cw.find_conversation_by_contact_source_id.assert_called_once_with(
            1, 10, "54958938411215@lid",
        )
        mock_cw.mark_conversation_read.assert_called_once_with(1, 200)

    def test_processes_played_status(self, client: TestClient) -> None:
        mock_cw = app.state.chatwoot_client
        mock_cw.resolve_account_id.return_value = 1
        mock_cw.resolve_inbox.return_value = (1, 10, "inbox-id")
        mock_cw.search_contact.return_value = 42
        mock_cw.find_open_conversation.return_value = (100, "source-123")
        mock_cw.mark_conversation_read.return_value = True

        resp = client.post(
            "/evolution-webhook",
            json=_make_update_payload(status="PLAYED"),
        )
        assert resp.status_code == 200
        assert resp.json()["processed"] == 1

    def test_health_endpoint(self, client: TestClient) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_lid_resolution_via_evolution_api(self, client: TestClient) -> None:
        mock_cw = app.state.chatwoot_client
        mock_cw.resolve_account_id.return_value = 1
        mock_cw.resolve_inbox.return_value = (1, 10, "inbox-id")
        mock_cw.search_contact.return_value = 42
        mock_cw.find_open_conversation.return_value = (100, "source-123")
        mock_cw.mark_conversation_read.return_value = True

        mock_evo = AsyncMock()
        mock_evo.resolve_lid_to_phone.return_value = "554891430125@s.whatsapp.net"
        app.state.evolution_client = mock_evo

        resp = client.post(
            "/evolution-webhook",
            json=_make_update_payload(
                instance="my-instance",
                remote_jid="54958938411215@lid",
            ),
        )
        assert resp.status_code == 200
        assert resp.json()["processed"] == 1

        mock_evo.resolve_lid_to_phone.assert_called_once_with(
            "my-instance",
            "54958938411215@lid",
        )
        mock_cw.search_contact.assert_called_once_with(
            1,
            "554891430125",
            jid_type="lid",
            remote_jid="554891430125@s.whatsapp.net",
        )

    def test_lid_fallback_to_source_id_when_evolution_fails(
        self,
        client: TestClient,
    ) -> None:
        mock_cw = app.state.chatwoot_client
        mock_cw.resolve_account_id.return_value = 1
        mock_cw.resolve_inbox.return_value = (1, 10, "inbox-id")
        mock_cw.search_contact.return_value = None
        mock_cw.find_conversation_by_contact_source_id.return_value = 200
        mock_cw.mark_conversation_read.return_value = True

        mock_evo = AsyncMock()
        mock_evo.resolve_lid_to_phone.return_value = None
        app.state.evolution_client = mock_evo

        resp = client.post(
            "/evolution-webhook",
            json=_make_update_payload(remote_jid="54958938411215@lid"),
        )
        assert resp.status_code == 200
        assert resp.json()["processed"] == 1

        mock_evo.resolve_lid_to_phone.assert_called_once()
        mock_cw.find_conversation_by_contact_source_id.assert_called_once_with(
            1, 10, "54958938411215@lid",
        )
