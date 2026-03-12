"""Tests for the ChatwootClient service."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
import respx

from app.services.chatwoot import ChatwootClient

BASE_URL = "http://chatwoot-test:3000"
ACCOUNT_IDS = [1, 2]


@pytest_asyncio.fixture()
async def chatwoot() -> AsyncIterator[ChatwootClient]:
    async with httpx.AsyncClient() as http_client:
        yield ChatwootClient(
            base_url=BASE_URL,
            api_token="tok",
            account_ids=ACCOUNT_IDS,
            http_client=http_client,
        )


class TestBuildInboxMap:

    @respx.mock
    async def test_builds_map_from_multiple_accounts(
        self,
        chatwoot: ChatwootClient,
    ) -> None:
        respx.get(f"{BASE_URL}/api/v1/accounts/1/inboxes").mock(
            return_value=httpx.Response(
                200,
                json={
                    "payload": [
                        {
                            "id": 10,
                            "name": "shop-wa",
                            "channel_type": "Channel::Api",
                            "inbox_identifier": "shop-wa-id",
                        },
                        {
                            "id": 11,
                            "name": "email-inbox",
                            "channel_type": "Channel::Email",
                        },
                    ],
                },
            ),
        )
        respx.get(f"{BASE_URL}/api/v1/accounts/2/inboxes").mock(
            return_value=httpx.Response(
                200,
                json={
                    "payload": [
                        {
                            "id": 20,
                            "name": "clinic-wa",
                            "channel_type": "Channel::Api",
                            "inbox_identifier": "clinic-wa-id",
                        },
                    ],
                },
            ),
        )

        result = await chatwoot.build_inbox_map()

        assert result == {
            "shop-wa": {"account_id": 1, "inbox_id": 10, "inbox_identifier": "shop-wa-id"},
            "clinic-wa": {"account_id": 2, "inbox_id": 20, "inbox_identifier": "clinic-wa-id"},
        }
        assert await chatwoot.resolve_account_id("shop-wa") == 1
        assert await chatwoot.resolve_account_id("clinic-wa") == 2

    @respx.mock
    async def test_skips_failing_accounts(
        self,
        chatwoot: ChatwootClient,
    ) -> None:
        respx.get(f"{BASE_URL}/api/v1/accounts/1/inboxes").mock(
            return_value=httpx.Response(500),
        )
        respx.get(f"{BASE_URL}/api/v1/accounts/2/inboxes").mock(
            return_value=httpx.Response(
                200,
                json={
                    "payload": [
                        {
                            "id": 20,
                            "name": "clinic-wa",
                            "channel_type": "Channel::Api",
                        },
                    ],
                },
            ),
        )

        result = await chatwoot.build_inbox_map()

        assert result == {"clinic-wa": {"account_id": 2, "inbox_id": 20, "inbox_identifier": None}}


class TestResolveInbox:

    @respx.mock
    async def test_resolves_inbox(self, chatwoot: ChatwootClient) -> None:
        respx.get(f"{BASE_URL}/api/v1/accounts/1/inboxes").mock(
            return_value=httpx.Response(
                200,
                json={
                    "payload": [
                        {
                            "id": 10,
                            "name": "shop-wa",
                            "channel_type": "Channel::Api",
                            "inbox_identifier": "shop-wa-id",
                        },
                    ],
                },
            ),
        )
        respx.get(f"{BASE_URL}/api/v1/accounts/2/inboxes").mock(
            return_value=httpx.Response(200, json={"payload": []}),
        )

        await chatwoot.build_inbox_map()
        result = await chatwoot.resolve_inbox("shop-wa")
        assert result == (1, 10, "shop-wa-id")

    @respx.mock
    async def test_returns_none_for_unknown_instance(
        self, chatwoot: ChatwootClient
    ) -> None:
        for aid in ACCOUNT_IDS:
            respx.get(f"{BASE_URL}/api/v1/accounts/{aid}/inboxes").mock(
                return_value=httpx.Response(200, json={"payload": []}),
            )

        result = await chatwoot.resolve_inbox("no-such-instance")
        assert result is None


class TestResolveAccountId:

    @respx.mock
    async def test_returns_none_for_unknown_instance(
        self,
        chatwoot: ChatwootClient,
    ) -> None:
        for aid in ACCOUNT_IDS:
            respx.get(f"{BASE_URL}/api/v1/accounts/{aid}/inboxes").mock(
                return_value=httpx.Response(
                    200, json={"payload": []},
                ),
            )

        result = await chatwoot.resolve_account_id("no-such-instance")
        assert result is None


class TestSearchContact:

    @respx.mock
    async def test_finds_contact_by_phone(
        self,
        chatwoot: ChatwootClient,
    ) -> None:
        respx.get(
            f"{BASE_URL}/api/v1/accounts/1/contacts/search",
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "payload": [
                        {
                            "id": 42,
                            "identifier": "5511999999999",
                            "phone_number": "+5511999999999",
                        },
                    ],
                },
            ),
        )

        result = await chatwoot.search_contact(1, "5511999999999")
        assert result == 42

    @respx.mock
    async def test_finds_contact_by_lid(
        self,
        chatwoot: ChatwootClient,
    ) -> None:
        respx.get(
            f"{BASE_URL}/api/v1/accounts/1/contacts/search",
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "payload": [
                        {
                            "id": 55,
                            "identifier": "54958938411215",
                            "phone_number": "",
                        },
                    ],
                },
            ),
        )

        result = await chatwoot.search_contact(1, "54958938411215")
        assert result == 55

    @respx.mock
    async def test_finds_lid_contact_by_source_id(
        self,
        chatwoot: ChatwootClient,
    ) -> None:
        respx.get(
            f"{BASE_URL}/api/v1/accounts/1/contacts/search",
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "payload": [
                        {
                            "id": 66,
                            "identifier": "",
                            "phone_number": "",
                            "contact_inboxes": [
                                {
                                    "source_id": "54958938411215@lid",
                                    "inbox": {"id": 10},
                                },
                            ],
                        },
                    ],
                },
            ),
        )

        result = await chatwoot.search_contact(
            1,
            "54958938411215",
            jid_type="lid",
            remote_jid="54958938411215@lid",
        )
        assert result == 66

    @respx.mock
    async def test_returns_none_when_not_found(
        self,
        chatwoot: ChatwootClient,
    ) -> None:
        respx.get(
            f"{BASE_URL}/api/v1/accounts/1/contacts/search",
        ).mock(
            return_value=httpx.Response(200, json={"payload": []}),
        )

        result = await chatwoot.search_contact(1, "0000000000")
        assert result is None

    @respx.mock
    async def test_returns_none_on_http_error(
        self,
        chatwoot: ChatwootClient,
    ) -> None:
        respx.get(
            f"{BASE_URL}/api/v1/accounts/1/contacts/search",
        ).mock(
            return_value=httpx.Response(500),
        )

        result = await chatwoot.search_contact(1, "5511999999999")
        assert result is None


class TestFindOpenConversation:

    @respx.mock
    async def test_finds_open_conversation(
        self,
        chatwoot: ChatwootClient,
    ) -> None:
        respx.get(
            f"{BASE_URL}/api/v1/accounts/1/contacts/10/conversations",
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "payload": [
                        {
                            "id": 100,
                            "status": "open",
                            "inbox": {"name": "my-instance"},
                            "contact_inbox": {"source_id": "source-123"},
                        },
                    ],
                },
            ),
        )

        result = await chatwoot.find_open_conversation(1, 10, "my-instance")
        assert result == (100, "source-123")

    @respx.mock
    async def test_falls_back_to_any_status(
        self,
        chatwoot: ChatwootClient,
    ) -> None:
        respx.get(
            f"{BASE_URL}/api/v1/accounts/1/contacts/10/conversations",
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "payload": [
                        {
                            "id": 200,
                            "status": "pending",
                            "inbox": {"name": "inst"},
                            "contact_inbox": {"source_id": "fallback-source"},
                        },
                    ],
                },
            ),
        )

        result = await chatwoot.find_open_conversation(1, 10, "inst")
        assert result == (200, "fallback-source")

    @respx.mock
    async def test_ignores_wrong_inbox(
        self,
        chatwoot: ChatwootClient,
    ) -> None:
        respx.get(
            f"{BASE_URL}/api/v1/accounts/1/contacts/10/conversations",
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "payload": [
                        {
                            "id": 300,
                            "status": "open",
                            "inbox": {"name": "other-inbox"},
                        },
                    ],
                },
            ),
        )

        result = await chatwoot.find_open_conversation(1, 10, "my-inbox")
        assert result is None


class TestFindConversationByContactSourceId:

    @respx.mock
    async def test_finds_conversation_by_sender_identifier(
        self,
        chatwoot: ChatwootClient,
    ) -> None:
        respx.get(
            f"{BASE_URL}/api/v1/accounts/1/conversations",
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "payload": [
                        {
                            "id": 100,
                            "meta": {
                                "sender": {
                                    "id": 5,
                                    "identifier": "54958938411215@lid",
                                },
                            },
                        },
                    ],
                },
            ),
        )

        result = await chatwoot.find_conversation_by_contact_source_id(
            1,
            10,
            "54958938411215@lid",
        )
        assert result == 100

    @respx.mock
    async def test_returns_none_when_not_found(
        self,
        chatwoot: ChatwootClient,
    ) -> None:
        respx.get(
            f"{BASE_URL}/api/v1/accounts/1/conversations",
        ).mock(
            return_value=httpx.Response(200, json={"payload": []}),
        )

        result = await chatwoot.find_conversation_by_contact_source_id(
            1,
            10,
            "54958938411215@lid",
        )
        assert result is None


class TestMarkConversationRead:

    @respx.mock
    async def test_successful_mark(self, chatwoot: ChatwootClient) -> None:
        respx.post(
            f"{BASE_URL}/api/v1/accounts/1"
            "/conversations/100/update_last_seen",
        ).mock(
            return_value=httpx.Response(200),
        )

        result = await chatwoot.mark_conversation_read(1, 100)
        assert result is True

    @respx.mock
    async def test_failure_returns_false(
        self,
        chatwoot: ChatwootClient,
    ) -> None:
        respx.post(
            f"{BASE_URL}/api/v1/accounts/1"
            "/conversations/100/update_last_seen",
        ).mock(
            return_value=httpx.Response(404),
        )

        result = await chatwoot.mark_conversation_read(1, 100)
        assert result is False
