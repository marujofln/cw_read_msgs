"""Async client for the Evolution API.

Provides methods to resolve LID JIDs to phone number JIDs using
Evolution's internal WhatsApp number cache.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class EvolutionClient:
    """Client for querying Evolution API to resolve LID JIDs.

    Evolution API stores a mapping between LID JIDs (e.g., 54958938411215@lid)
    and phone JIDs (e.g., 554891430125@s.whatsapp.net) in its internal
    IsOnWhatsapp cache. This client queries that cache via the
    /chat/whatsappNumbers endpoint.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._api_key = api_key
        self._http = http_client

    def _headers(self) -> dict[str, str]:
        return {
            "apikey": self._api_key,
            "Content-Type": "application/json",
        }

    async def resolve_lid_to_phone(
        self,
        instance_name: str,
        lid_jid: str,
    ) -> str | None:
        """Resolve a LID JID to a phone number JID via Evolution API.

        Calls POST /chat/whatsappNumbers/{instance} with the LID JID.
        If Evolution has the mapping cached, it returns the corresponding
        @s.whatsapp.net JID.

        Args:
            instance_name: The Evolution instance name (e.g., "gnovit teste")
            lid_jid: The LID JID to resolve (e.g., "54958938411215@lid")

        Returns:
            The phone JID (e.g., "554891430125@s.whatsapp.net") or None if not found.
        """
        url = f"{self._base}/chat/whatsappNumbers/{instance_name}"

        logger.debug(
            "Evolution API request: POST %s with numbers=[%s]",
            url,
            lid_jid,
        )

        try:
            resp = await self._http.post(
                url,
                headers=self._headers(),
                json={"numbers": [lid_jid]},
            )
            resp.raise_for_status()
            data: list[dict[str, Any]] = resp.json()

            logger.debug("Evolution API response: %s", data)

            if not data:
                logger.debug(
                    "Evolution API returned empty response for LID %s",
                    lid_jid,
                )
                return None

            result = data[0]
            jid = result.get("jid")
            exists = result.get("exists", False)

            if not exists or not jid:
                logger.debug(
                    "LID %s not found in Evolution cache (exists=%s, jid=%s)",
                    lid_jid,
                    exists,
                    jid,
                )
                return None

            if jid == lid_jid:
                logger.debug(
                    "Evolution returned same JID %s (no phone mapping)",
                    jid,
                )
                return None

            logger.info(
                "Resolved LID %s -> phone JID %s via Evolution API",
                lid_jid,
                jid,
            )
            return jid

        except httpx.HTTPStatusError as e:
            logger.warning(
                "Evolution API error resolving LID %s: HTTP %d",
                lid_jid,
                e.response.status_code,
            )
            return None
        except Exception:
            logger.exception("Failed to resolve LID %s via Evolution API", lid_jid)
            return None
