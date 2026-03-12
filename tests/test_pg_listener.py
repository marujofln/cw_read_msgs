"""Tests for the PG listener service."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.pg_listener import _handle_conversation_read


@pytest.mark.asyncio()
async def test_handle_conversation_read_marks_messages() -> None:
    """_handle_conversation_read fetches messages and calls Evolution API."""
    mock_chatwoot = AsyncMock()
    mock_chatwoot.get_conversation_source_id.return_value = "5511999999999@s.whatsapp.net"
    mock_chatwoot.get_conversation_inbox_id.return_value = 10
    mock_chatwoot._inbox_map = {
        "shop-wa": {"account_id": 1, "inbox_id": 10},
    }
    mock_chatwoot.resolve_instance_name = MagicMock(return_value="shop-wa")
    mock_chatwoot.get_conversation_messages.return_value = [
        {"id": 1, "source_id": "MSG001"},
        {"id": 2, "source_id": "MSG002"},
    ]

    mock_evolution = AsyncMock()
    mock_evolution.mark_messages_as_read.return_value = True

    await _handle_conversation_read(
        mock_chatwoot,
        mock_evolution,
        account_id=1,
        conversation_id=100,
    )

    mock_chatwoot.get_conversation_source_id.assert_called_once_with(1, 100)
    mock_chatwoot.get_conversation_inbox_id.assert_called_once_with(1, 100)
    mock_chatwoot.get_conversation_messages.assert_called_once_with(
        1, 100, message_type="incoming"
    )
    mock_evolution.mark_messages_as_read.assert_called_once_with(
        instance_name="shop-wa",
        remote_jid="5511999999999@s.whatsapp.net",
        message_ids=["MSG001", "MSG002"],
    )


@pytest.mark.asyncio()
async def test_handle_conversation_read_returns_early_when_no_source_id() -> None:
    """_handle_conversation_read exits when conversation has no source_id."""
    mock_chatwoot = AsyncMock()
    mock_chatwoot.get_conversation_source_id.return_value = None

    mock_evolution = AsyncMock()

    await _handle_conversation_read(
        mock_chatwoot,
        mock_evolution,
        account_id=1,
        conversation_id=100,
    )

    mock_chatwoot.get_conversation_source_id.assert_called_once()
    mock_evolution.mark_messages_as_read.assert_not_called()


@pytest.mark.asyncio()
async def test_handle_conversation_read_returns_early_when_inbox_not_in_map() -> None:
    """_handle_conversation_read exits when inbox is not an Evolution API inbox."""
    mock_chatwoot = AsyncMock()
    mock_chatwoot.get_conversation_source_id.return_value = "5511999999999@s.whatsapp.net"
    mock_chatwoot.get_conversation_inbox_id.return_value = 99
    mock_chatwoot._inbox_map = {"shop-wa": {"account_id": 1, "inbox_id": 10}}
    mock_chatwoot.resolve_instance_name = MagicMock(return_value=None)

    mock_evolution = AsyncMock()

    await _handle_conversation_read(
        mock_chatwoot,
        mock_evolution,
        account_id=1,
        conversation_id=100,
    )

    mock_chatwoot.get_conversation_inbox_id.assert_called_once()
    mock_evolution.mark_messages_as_read.assert_not_called()
