from __future__ import annotations

import json
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


class ScryfallError(RuntimeError):
    pass


class ScryfallClient:
    base_url = "https://api.scryfall.com"

    def __init__(self, user_agent: str = "mtg-project-pwa/0.1") -> None:
        self.user_agent = user_agent

    def search_cards(
        self,
        query: str,
        *,
        lang: str = "fr",
        limit: int = 24,
        serialized: bool = False,
    ) -> list[dict[str, Any]]:
        user_query = query.strip()
        if not user_query:
            return []

        scryfall_query = normalize_search_query(user_query)
        if serialized:
            scryfall_query = f"({scryfall_query}) is:serialized"

        if lang and lang != "all" and not serialized:
            scryfall_query = f"({scryfall_query}) lang:{lang}"

        params = {
            "q": scryfall_query,
            "unique": "prints",
            "order": "name",
            "include_multilingual": "true",
        }
        payload = self._get("/cards/search", params=params)
        return list(payload.get("data", []))[:limit]

    def card(self, scryfall_id: str) -> dict[str, Any]:
        return self._get(f"/cards/{scryfall_id}")

    def rulings(self, scryfall_id: str) -> list[dict[str, Any]]:
        payload = self._get(f"/cards/{scryfall_id}/rulings")
        return list(payload.get("data", []))

    def collection(self, scryfall_ids: list[str]) -> list[dict[str, Any]]:
        cards: list[dict[str, Any]] = []
        for index in range(0, len(scryfall_ids), 75):
            chunk = scryfall_ids[index : index + 75]
            payload = self._post(
                "/cards/collection",
                {"identifiers": [{"id": scryfall_id} for scryfall_id in chunk]},
            )
            cards.extend(payload.get("data", []))
            self.throttle()
        return cards

    def cards_by_oracle_id(self, oracle_id: str, *, max_cards: int = 120) -> list[dict[str, Any]]:
        if not oracle_id:
            return []
        cards: list[dict[str, Any]] = []
        params = {
            "q": f"oracle_id:{oracle_id}",
            "unique": "prints",
            "order": "released",
            "dir": "desc",
        }
        payload = self._get("/cards/search", params=params)
        cards.extend(payload.get("data", []))
        while payload.get("has_more") and len(cards) < max_cards:
            self.throttle()
            next_page = payload.get("next_page")
            if not next_page:
                break
            payload = self._get_url(next_page)
            cards.extend(payload.get("data", []))
        return cards[:max_cards]

    def cards_by_set_collector(
        self,
        set_code: str,
        collector_number: str,
        *,
        limit: int = 12,
    ) -> list[dict[str, Any]]:
        if not set_code or not collector_number:
            return []
        params = {
            "q": f"set:{set_code.lower()} cn:{collector_number}",
            "unique": "prints",
        }
        payload = self._get("/cards/search", params=params)
        return list(payload.get("data", []))[:limit]

    def card_by_set_number_lang(self, set_code: str, collector_number: str, lang: str = "en") -> dict[str, Any]:
        safe_set = quote(set_code.lower(), safe="")
        safe_number = quote(collector_number, safe="")
        safe_lang = quote(lang.lower(), safe="")
        return self._get(f"/cards/{safe_set}/{safe_number}/{safe_lang}")

    def _get(self, path: str, *, params: dict[str, str] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"
        return self._get_url(url)

    def _get_url(self, url: str) -> dict[str, Any]:
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": self.user_agent,
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            details = error.read().decode("utf-8", errors="replace")
            raise ScryfallError(f"Scryfall HTTP {error.code}: {details}") from error
        except URLError as error:
            raise ScryfallError(f"Scryfall request failed: {error.reason}") from error

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": self.user_agent,
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            details = error.read().decode("utf-8", errors="replace")
            raise ScryfallError(f"Scryfall HTTP {error.code}: {details}") from error
        except URLError as error:
            raise ScryfallError(f"Scryfall request failed: {error.reason}") from error

    @staticmethod
    def throttle() -> None:
        # Scryfall asks clients to keep requests roughly 50-100 ms apart.
        time.sleep(0.12)


def normalize_search_query(query: str) -> str:
    if any(token in query for token in (":", "!", "(", ")", " or ", " and ")):
        return query
    escaped = query.replace('"', '\\"')
    return f'name:"{escaped}"'
