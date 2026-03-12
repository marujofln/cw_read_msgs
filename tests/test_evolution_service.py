"""Tests for the Evolution API client."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.services.evolution import EvolutionClient


@pytest.fixture()
def http_client() -> AsyncMock:
    return AsyncMock(spec=httpx.AsyncClient)


@pytest.fixture()
def evolution_client(http_client: AsyncMock) -> EvolutionClient:
    return EvolutionClient(
        base_url="http://evolution.example.com",
        api_key="test-api-key",
        http_client=http_client,
    )


class TestResolveLidToPhone:
    """Tests for EvolutionClient.resolve_lid_to_phone."""

    @pytest.mark.asyncio()
    async def test_resolves_lid_to_phone_jid(
        self,
        evolution_client: EvolutionClient,
        http_client: AsyncMock,
    ) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {
                "jid": "554891430125@s.whatsapp.net",
                "exists": True,
                "number": "554891430125",
            },
        ]
        mock_response.raise_for_status = MagicMock()
        http_client.post.return_value = mock_response

        result = await evolution_client.resolve_lid_to_phone(
            "my-instance",
            "54958938411215@lid",
        )

        assert result == "554891430125@s.whatsapp.net"
        http_client.post.assert_called_once_with(
            "http://evolution.example.com/chat/whatsappNumbers/my-instance",
            headers={"apikey": "test-api-key", "Content-Type": "application/json"},
            json={"numbers": ["54958938411215@lid"]},
        )

    @pytest.mark.asyncio()
    async def test_returns_none_when_not_found(
        self,
        evolution_client: EvolutionClient,
        http_client: AsyncMock,
    ) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {
                "jid": "54958938411215@lid",
                "exists": False,
            },
        ]
        mock_response.raise_for_status = MagicMock()
        http_client.post.return_value = mock_response

        result = await evolution_client.resolve_lid_to_phone(
            "my-instance",
            "54958938411215@lid",
        )

        assert result is None

    @pytest.mark.asyncio()
    async def test_returns_none_when_same_jid_returned(
        self,
        evolution_client: EvolutionClient,
        http_client: AsyncMock,
    ) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {
                "jid": "54958938411215@lid",
                "exists": True,
            },
        ]
        mock_response.raise_for_status = MagicMock()
        http_client.post.return_value = mock_response

        result = await evolution_client.resolve_lid_to_phone(
            "my-instance",
            "54958938411215@lid",
        )

        assert result is None

    @pytest.mark.asyncio()
    async def test_returns_none_on_empty_response(
        self,
        evolution_client: EvolutionClient,
        http_client: AsyncMock,
    ) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = MagicMock()
        http_client.post.return_value = mock_response

        result = await evolution_client.resolve_lid_to_phone(
            "my-instance",
            "54958938411215@lid",
        )

        assert result is None

    @pytest.mark.asyncio()
    async def test_handles_http_error(
        self,
        evolution_client: EvolutionClient,
        http_client: AsyncMock,
    ) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 500
        http_error = httpx.HTTPStatusError(
            "Server error",
            request=MagicMock(),
            response=mock_response,
        )
        mock_response.raise_for_status.side_effect = http_error
        http_client.post.return_value = mock_response

        result = await evolution_client.resolve_lid_to_phone(
            "my-instance",
            "54958938411215@lid",
        )

        assert result is None

    @pytest.mark.asyncio()
    async def test_handles_network_error(
        self,
        evolution_client: EvolutionClient,
        http_client: AsyncMock,
    ) -> None:
        http_client.post.side_effect = httpx.ConnectError("Connection failed")

        result = await evolution_client.resolve_lid_to_phone(
            "my-instance",
            "54958938411215@lid",
        )

        assert result is None


class TestMarkMessagesAsRead:
    """Tests for EvolutionClient.mark_messages_as_read."""

    @pytest.mark.asyncio()
    async def test_sends_read_receipts(
        self,
        evolution_client: EvolutionClient,
        http_client: AsyncMock,
    ) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.raise_for_status = MagicMock()
        http_client.post.return_value = mock_response

        result = await evolution_client.mark_messages_as_read(
            instance_name="my-instance",
            remote_jid="5511999999999@s.whatsapp.net",
            message_ids=["MSG1", "MSG2"],
        )

        assert result is True
        http_client.post.assert_called_once()
        call_args = http_client.post.call_args
        url = call_args.args[0] if call_args.args else call_args.kwargs.get("url", "")
        assert "markMessageAsRead" in url
        assert call_args.kwargs["json"] == {
            "readMessages": [
                {"remoteJid": "5511999999999@s.whatsapp.net", "fromMe": False, "id": "MSG1"},
                {"remoteJid": "5511999999999@s.whatsapp.net", "fromMe": False, "id": "MSG2"},
            ],
        }

    @pytest.mark.asyncio()
    async def test_returns_true_for_empty_message_ids(
        self,
        evolution_client: EvolutionClient,
        http_client: AsyncMock,
    ) -> None:
        result = await evolution_client.mark_messages_as_read(
            instance_name="my-instance",
            remote_jid="5511999999999@s.whatsapp.net",
            message_ids=[],
        )
        assert result is True
        http_client.post.assert_not_called()

    @pytest.mark.asyncio()
    async def test_returns_false_on_http_error(
        self,
        evolution_client: EvolutionClient,
        http_client: AsyncMock,
    ) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Server error"
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Error", request=MagicMock(), response=mock_response
        )
        http_client.post.return_value = mock_response

        result = await evolution_client.mark_messages_as_read(
            instance_name="my-instance",
            remote_jid="5511999999999@s.whatsapp.net",
            message_ids=["MSG1"],
        )
        assert result is False
