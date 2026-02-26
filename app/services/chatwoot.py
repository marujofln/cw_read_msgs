"""Async client for the Chatwoot API.

Handles searching contacts, resolving conversations, and marking
conversations as read via the ``update_last_seen`` endpoint.

Supports multiple Chatwoot accounts by auto-discovering which inbox
belongs to which account at startup.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class ChatwootClient:
    """Multi-account wrapper around the Chatwoot v1 REST API.

    On startup, ``build_inbox_map`` queries each configured account for
    its API-channel inboxes and caches ``{inbox_name: account_id}``.
    When a webhook arrives, ``resolve_account_id`` translates the
    Evolution instance name into the correct Chatwoot account.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_token: str,
        account_ids: list[int],
        http_client: httpx.AsyncClient,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._account_ids = account_ids
        self._http = http_client
        self._headers = {
            "api_access_token": api_token,
            "Content-Type": "application/json",
        }
        self._inbox_map: dict[str, dict[str, int]] = {}

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _contact_matches(
        contact: dict[str, Any],
        query: str,
        remote_jid: str | None,
    ) -> bool:
        """Return True if contact matches query or remote_jid (for LID source_id)."""
        identifier = str(contact.get("identifier", ""))
        phone_number = str(contact.get("phone_number", ""))
        if query in identifier or query in phone_number:
            return True
        if remote_jid:
            for ci in contact.get("contact_inboxes", []):
                source_id = str(ci.get("source_id", ""))
                if source_id == remote_jid or remote_jid in source_id:
                    return True
        return False

    def _url(self, account_id: int, path: str) -> str:
        return f"{self._base}/api/v1/accounts/{account_id}{path}"

    async def _get(
        self,
        account_id: int,
        path: str,
        **params: Any,
    ) -> dict[str, Any] | list[Any]:
        resp = await self._http.get(
            self._url(account_id, path),
            headers=self._headers,
            params=params,
        )
        resp.raise_for_status()
        return resp.json()  # type: ignore[no-any-return]

    async def _post(self, account_id: int, path: str) -> int:
        resp = await self._http.post(
            self._url(account_id, path),
            headers=self._headers,
        )
        resp.raise_for_status()
        return resp.status_code

    # -- inbox map (auto-discovery) ------------------------------------------

    async def build_inbox_map(self) -> dict[str, dict[str, Any]]:
        """Query every configured account for API-channel inboxes.

        Builds and caches ``{inbox_name: {"account_id": int, "inbox_id": int, "inbox_identifier": str}}``
        so that an Evolution instance name can be resolved to a Chatwoot account
        and inbox.
        """
        inbox_map: dict[str, dict[str, Any]] = {}

        for account_id in self._account_ids:
            try:
                data = await self._get(account_id, "/inboxes")
            except httpx.HTTPStatusError:
                logger.exception(
                    "Failed to list inboxes for account %d", account_id,
                )
                continue

            payload: list[dict[str, Any]] = (
                data.get("payload", []) if isinstance(data, dict) else data
            )

            for inbox in payload:
                channel_type = inbox.get("channel_type", "")
                name = inbox.get("name", "")
                inbox_id = inbox.get("id")
                inbox_identifier = inbox.get("inbox_identifier")
                if (
                    channel_type == "Channel::Api"
                    and name
                    and inbox_id is not None
                ):
                    inbox_map[name] = {
                        "account_id": account_id,
                        "inbox_id": int(inbox_id),
                        "inbox_identifier": inbox_identifier,
                    }

        self._inbox_map = inbox_map
        logger.info("Inbox map built: %s", inbox_map)
        return inbox_map

    async def resolve_account_id(self, instance_name: str) -> int | None:
        """Return the Chatwoot account ID that owns *instance_name*.

        Falls back to a single rebuild if the name is not in the cache
        (handles inboxes created after startup).
        """
        entry = self._inbox_map.get(instance_name)
        if entry is not None:
            return entry["account_id"]

        logger.info(
            "Instance '%s' not in inbox map, rebuilding...", instance_name,
        )
        await self.build_inbox_map()
        entry = self._inbox_map.get(instance_name)
        return entry["account_id"] if entry else None

    async def resolve_inbox(
        self,
        instance_name: str,
    ) -> tuple[int, int, str | None] | None:
        """Return (account_id, inbox_id, inbox_identifier) for the given instance name.

        Falls back to a single rebuild if the name is not in the cache.
        """
        entry = self._inbox_map.get(instance_name)
        if entry is not None:
            return entry["account_id"], entry["inbox_id"], entry.get("inbox_identifier")

        logger.info(
            "Instance '%s' not in inbox map, rebuilding...", instance_name,
        )
        await self.build_inbox_map()
        entry = self._inbox_map.get(instance_name)
        if entry is None:
            return None
        return entry["account_id"], entry["inbox_id"], entry.get("inbox_identifier")

    # -- public API ----------------------------------------------------------

    async def search_contact(
        self,
        account_id: int,
        query: str,
        *,
        jid_type: str | None = None,
        remote_jid: str | None = None,
    ) -> int | None:
        """Search for a contact whose identifier, phone, or source_id matches.

        *query* is the numeric part (e.g. 54958938411215).
        For LID contacts, pass jid_type="lid" and remote_jid="54958938411215@lid"
        to try full JID first and match contact_inboxes source_id.
        Returns the contact ``id`` or ``None`` if not found.
        """
        queries: list[str] = []
        if jid_type == "lid" and remote_jid:
            queries.append(remote_jid)
        queries.append(query)
        if query.isdigit():
            plus_query = f"+{query}"
            if plus_query not in queries:
                queries.append(plus_query)

        for q in queries:
            try:
                data = await self._get(
                    account_id,
                    "/contacts/search",
                    q=q,
                    include_contacts=True,
                )
            except httpx.HTTPStatusError:
                logger.debug(
                    "Chatwoot contact search failed for query '%s'", q,
                )
                continue

            payload: list[dict[str, Any]] = (
                data.get("payload", []) if isinstance(data, dict) else data
            )

            for contact in payload:
                if self._contact_matches(contact, q, remote_jid):
                    contact_id: int = contact["id"]
                    logger.debug(
                        "Found contact id=%d for query '%s'",
                        contact_id,
                        q,
                    )
                    return contact_id

        logger.debug("No contact found for query '%s'", query)
        return None

    async def find_open_conversation(
        self,
        account_id: int,
        contact_id: int,
        inbox_name: str,
        inbox_id: int | None = None,
    ) -> tuple[int, str | None] | None:
        """Return the most recent open conversation for *contact_id* in *inbox_name*.

        Returns a tuple of ``(conversation_id, source_id)`` or ``None``.
        The ``source_id`` is extracted from the conversation's ``contact_inbox`` field.
        """
        try:
            data = await self._get(
                account_id,
                f"/contacts/{contact_id}/conversations",
            )
        except httpx.HTTPStatusError:
            logger.exception(
                "Failed to fetch conversations for contact %d", contact_id,
            )
            return None

        payload: list[dict[str, Any]] = (
            data.get("payload", []) if isinstance(data, dict) else data
        )

        available_convs = [
            (
                conv.get("id"),
                conv.get("inbox_id"),
                (conv.get("inbox") or {}).get("id"),
                (conv.get("inbox") or {}).get("name", ""),
                conv.get("status"),
            )
            for conv in payload
        ]
        logger.debug(
            "Contact %d conversations: %s (looking for inbox_id=%s, name='%s')",
            contact_id,
            available_convs,
            inbox_id,
            inbox_name,
        )

        def _inbox_matches(conv: dict[str, Any]) -> bool:
            conv_inbox_id = conv.get("inbox_id")
            inbox = conv.get("inbox", {}) or {}
            inbox_obj_id = inbox.get("id")
            if inbox_id is not None:
                if conv_inbox_id == inbox_id or inbox_obj_id == inbox_id:
                    return True
            if inbox.get("name", "") == inbox_name:
                return True
            return False

        def _extract_source_id(conv: dict[str, Any]) -> str | None:
            contact_inbox = conv.get("contact_inbox") or {}
            source_id = contact_inbox.get("source_id")
            logger.debug(
                "Conversation %d contact_inbox: %s (extracted source_id=%s)",
                conv.get("id"),
                contact_inbox,
                source_id,
            )
            return source_id

        for conv in payload:
            status = conv.get("status")
            if _inbox_matches(conv) and status == "open":
                conv_id: int = conv["id"]
                source_id = _extract_source_id(conv)
                logger.debug(
                    "Found open conversation id=%d for contact %d (source_id=%s)",
                    conv_id,
                    contact_id,
                    source_id,
                )
                return (conv_id, source_id)

        for conv in payload:
            if _inbox_matches(conv):
                conv_id = conv["id"]
                source_id = _extract_source_id(conv)
                logger.debug(
                    "Fallback: conversation id=%d (status=%s) for contact %d (source_id=%s)",
                    conv_id,
                    conv.get("status"),
                    contact_id,
                    source_id,
                )
                return (conv_id, source_id)

        logger.debug(
            "No conversation found for contact %d in inbox '%s' (id=%s)",
            contact_id,
            inbox_name,
            inbox_id,
        )
        return None

    async def find_conversation_by_contact_source_id(
        self,
        account_id: int,
        inbox_id: int,
        source_id: str,
    ) -> int | None:
        """Find a conversation by listing inbox conversations and matching contact source_id.

        Used as fallback when contact search fails for LID contacts, since
        Evolution/Chatwoot may store source_id as the full JID (e.g. 54958938411215@lid).
        Returns the conversation ``id`` or ``None`` if not found.
        """
        page = 1
        while True:
            try:
                data = await self._get(
                    account_id,
                    "/conversations",
                    inbox_id=inbox_id,
                    status="all",
                    page=page,
                )
            except httpx.HTTPStatusError:
                logger.exception(
                    "Failed to list conversations for inbox %d", inbox_id,
                )
                return None

            payload = data.get("payload", data) if isinstance(data, dict) else data
            if not isinstance(payload, list):
                payload = data.get("data", {}).get("payload", []) or []

            if not payload:
                break

            for conv in payload:
                meta = conv.get("meta", {})
                sender = meta.get("sender", {})
                identifier = str(sender.get("identifier", ""))
                if identifier == source_id:
                    conv_id: int = conv["id"]
                    logger.debug(
                        "Found conversation id=%d by source_id '%s'",
                        conv_id,
                        source_id,
                    )
                    return conv_id

                for ci in sender.get("contact_inboxes", []):
                    if str(ci.get("source_id", "")) == source_id:
                        conv_id = conv["id"]
                        logger.debug(
                            "Found conversation id=%d by contact_inbox source_id",
                            conv_id,
                        )
                        return conv_id

            page += 1
            if len(payload) < 15:
                break

        logger.debug(
            "No conversation found for source_id '%s' in inbox %d",
            source_id,
            inbox_id,
        )
        return None

    async def get_contact_source_id(
        self,
        account_id: int,
        contact_id: int,
        inbox_id: int,
    ) -> str | None:
        """Get the contact's source_id for a specific inbox."""
        try:
            data = await self._get(account_id, f"/contacts/{contact_id}")
        except httpx.HTTPStatusError:
            logger.exception(
                "Failed to get contact %d details", contact_id,
            )
            return None

        contact = data if isinstance(data, dict) else {}
        contact_inboxes = contact.get("contact_inboxes", [])

        logger.debug(
            "Contact %d has %d contact_inboxes: %s",
            contact_id,
            len(contact_inboxes),
            [
                {
                    "inbox_id": ci.get("inbox", {}).get("id") if ci.get("inbox") else ci.get("inbox_id"),
                    "source_id": ci.get("source_id"),
                }
                for ci in contact_inboxes
            ],
        )

        for ci in contact_inboxes:
            ci_inbox = ci.get("inbox", {}) or {}
            if ci_inbox.get("id") == inbox_id or ci.get("inbox_id") == inbox_id:
                source_id = ci.get("source_id")
                if source_id:
                    logger.debug(
                        "Found source_id '%s' for contact %d in inbox %d",
                        source_id,
                        contact_id,
                        inbox_id,
                    )
                    return source_id

        logger.debug(
            "No source_id found for contact %d in inbox %d",
            contact_id,
            inbox_id,
        )
        return None

    async def get_conversation_source_id(
        self,
        account_id: int,
        conversation_id: int,
    ) -> str | None:
        """Get the source_id from conversation details."""
        try:
            data = await self._get(account_id, f"/conversations/{conversation_id}")
        except httpx.HTTPStatusError:
            logger.exception(
                "Failed to get conversation %d details", conversation_id,
            )
            return None

        conv = data if isinstance(data, dict) else {}
        contact_inbox = conv.get("contact_inbox") or {}
        source_id = contact_inbox.get("source_id")

        logger.debug(
            "Conversation %d contact_inbox from details API: %s (source_id=%s)",
            conversation_id,
            contact_inbox,
            source_id,
        )

        return source_id

    async def mark_conversation_read(
        self,
        account_id: int,
        conversation_id: int,
        *,
        inbox_identifier: str | None = None,
        source_id: str | None = None,
    ) -> bool:
        """Mark a conversation as read.

        If inbox_identifier and source_id are provided, uses the public API
        which marks messages as read from the contact's perspective.
        Otherwise falls back to the agent API.
        """
        if inbox_identifier and source_id:
            url = (
                f"{self._base}/public/api/v1/inboxes/{inbox_identifier}"
                f"/contacts/{source_id}/conversations/{conversation_id}/update_last_seen"
            )
            logger.debug(
                "Calling public API: POST %s (inbox_identifier=%s, source_id=%s, conv=%d)",
                url,
                inbox_identifier,
                source_id,
                conversation_id,
            )
            try:
                resp = await self._http.post(url)
                resp.raise_for_status()
                logger.info(
                    "Marked conversation %d as read via public API (HTTP %d)",
                    conversation_id,
                    resp.status_code,
                )
                return True
            except httpx.HTTPStatusError:
                logger.exception(
                    "Failed to mark conversation %d as read via public API",
                    conversation_id,
                )
                return False

        logger.debug(
            "Calling agent API: POST /accounts/%d/conversations/%d/update_last_seen (no inbox_identifier=%s or source_id=%s)",
            account_id,
            conversation_id,
            inbox_identifier,
            source_id,
        )
        try:
            status = await self._post(
                account_id,
                f"/conversations/{conversation_id}/update_last_seen",
            )
            logger.info(
                "Marked conversation %d as read via agent API (HTTP %d)",
                conversation_id,
                status,
            )
            return True
        except httpx.HTTPStatusError:
            logger.exception(
                "Failed to mark conversation %d as read", conversation_id,
            )
            return False
