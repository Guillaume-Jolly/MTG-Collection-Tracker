from __future__ import annotations

import gzip
import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


DEFAULT_CACHE_ROOT = Path("data/cache")
USER_AGENT = "mtg-project-pwa/0.1"
MTGJSON_BASE_URL = "https://mtgjson.com/api/v5"
DECK_LIST_GZ_URL = f"{MTGJSON_BASE_URL}/DeckList.json.gz"
SET_LIST_GZ_URL = f"{MTGJSON_BASE_URL}/SetList.json.gz"


class CacheError(RuntimeError):
    pass


def cache_root() -> Path:
    return Path(os.environ.get("MTG_PWA_CACHE", DEFAULT_CACHE_ROOT))


def deck_list_path() -> Path:
    return cache_root() / "mtgjson" / "DeckList.json"


def set_list_path() -> Path:
    return cache_root() / "mtgjson" / "SetList.json"


def deck_json_path(file_name: str) -> Path:
    safe_name = file_name.replace("/", "_").replace("\\", "_")
    return cache_root() / "mtgjson" / "decks" / f"{safe_name}.json"


def image_path(scryfall_id: str) -> Path:
    return cache_root() / "images" / f"{scryfall_id}.jpg"


def local_image_url(scryfall_id: str) -> str | None:
    path = image_path(scryfall_id)
    if path.exists() and path.stat().st_size > 0:
        return f"/cache/images/{scryfall_id}.jpg"
    return None


def scryfall_image_url(scryfall_id: str, *, size: str = "normal") -> str:
    return f"https://cards.scryfall.io/{size}/front/{scryfall_id[0]}/{scryfall_id[1]}/{scryfall_id}.jpg"


def catalog_image_url(scryfall_id: str | None) -> str | None:
    if not scryfall_id:
        return None
    return local_image_url(scryfall_id) or scryfall_image_url(scryfall_id)


def cached_set_codes() -> set[str]:
    sets_dir = cache_root() / "mtgjson" / "sets"
    if not sets_dir.exists():
        return set()
    return {path.stem.upper() for path in sets_dir.glob("*.json")}


def set_stats_cache_path() -> Path:
    return cache_root() / "mtgjson" / "set_stats.json"


def load_set_stats_cache() -> dict[str, Any]:
    path = set_stats_cache_path()
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_set_stats_cache(cache: dict[str, Any]) -> None:
    path = set_stats_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def fetch_gzip_json(url: str) -> dict[str, Any]:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=45) as response:
            return json.loads(gzip.decompress(response.read()).decode("utf-8"))
    except HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        raise CacheError(f"MTGJSON HTTP {error.code}: {details}") from error
    except URLError as error:
        raise CacheError(f"MTGJSON request failed: {error.reason}") from error


def load_deck_list() -> list[dict[str, Any]]:
    path = deck_list_path()
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        return list(payload.get("data") or [])

    payload = fetch_gzip_json(DECK_LIST_GZ_URL)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return list(payload.get("data") or [])


def load_set_list() -> list[dict[str, Any]]:
    path = set_list_path()
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        return list(payload.get("data") or [])

    payload = fetch_gzip_json(SET_LIST_GZ_URL)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return list(payload.get("data") or [])


def set_json_path(set_code: str) -> Path:
    safe_code = set_code.replace("/", "_").replace("\\", "_")
    return cache_root() / "mtgjson" / "sets" / f"{safe_code}.json"


def load_set_json(set_code: str) -> dict[str, Any]:
    path = set_json_path(set_code)
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload.get("data") or {}

    url = f"{MTGJSON_BASE_URL}/{quote(set_code.upper(), safe='')}.json"
    request = Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=45) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        raise CacheError(f"MTGJSON set HTTP {error.code}: {details}") from error
    except URLError as error:
        raise CacheError(f"MTGJSON set request failed: {error.reason}") from error

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload.get("data") or {}


def load_deck(file_name: str) -> dict[str, Any]:
    path = deck_json_path(file_name)
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload.get("data") or {}

    safe_file_name = quote(file_name, safe="")
    url = f"{MTGJSON_BASE_URL}/decks/{safe_file_name}.json"
    request = Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=45) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        raise CacheError(f"MTGJSON deck HTTP {error.code}: {details}") from error
    except URLError as error:
        raise CacheError(f"MTGJSON deck request failed: {error.reason}") from error

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload.get("data") or {}


def download_image(url: str, scryfall_id: str, *, delay_seconds: float = 0.05) -> bool:
    target = image_path(scryfall_id)
    if target.exists() and target.stat().st_size > 0:
        return False

    request = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=30) as response:
            data = response.read()
    except (HTTPError, URLError):
        return False

    if not data:
        return False

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    if delay_seconds:
        time.sleep(delay_seconds)
    return True
