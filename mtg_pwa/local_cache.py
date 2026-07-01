from __future__ import annotations

import gzip
import json
import os
import threading
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


def set_icon_path(slug: str) -> Path:
    safe_slug = slug.replace("/", "_").replace("\\", "_").lower()
    return cache_root() / "set-icons" / f"{safe_slug}.svg"


def fallback_set_icon_svg(label: str) -> bytes:
    text = (label or "?")[:4].upper()
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" role="img">
  <circle cx="50" cy="50" r="46" fill="none" stroke="#ffffff" stroke-width="4"/>
  <text x="50" y="58" text-anchor="middle" font-size="22" font-family="Segoe UI, sans-serif" fill="#ffffff">{text}</text>
</svg>""".encode(
        "utf-8"
    )


def fetch_url_bytes(url: str, *, timeout: int = 15) -> bytes:
    request = Request(url, headers={"Accept": "image/svg+xml,*/*", "User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def ensure_set_icon(slug: str, *, set_code: str = "") -> Path:
    safe_slug = slug.lower()
    path = set_icon_path(safe_slug)
    if path.exists() and path.stat().st_size > 0:
        return path

    path.parent.mkdir(parents=True, exist_ok=True)
    candidates: list[str] = []
    if safe_slug:
        candidates.append(safe_slug)
    normalized_code = (set_code or safe_slug).upper()
    if normalized_code:
        candidates.append(normalized_code.lower())

    for entry in load_set_list():
        entry_code = (entry.get("code") or "").upper()
        entry_keyrune = (entry.get("keyruneCode") or "").lower()
        if entry_code == normalized_code or entry_keyrune == safe_slug:
            if entry_keyrune and entry_keyrune != "default":
                candidates.insert(0, entry_keyrune)
            if entry_code:
                candidates.append(entry_code.lower())
            break

    seen: set[str] = set()
    for candidate in candidates:
        token = candidate.lower()
        if not token or token in seen:
            continue
        seen.add(token)
        try:
            data = fetch_url_bytes(f"https://svgs.scryfall.io/sets/{token}.svg")
        except (HTTPError, URLError, TimeoutError):
            continue
        if data.startswith(b"<"):
            path.write_bytes(data)
            return path

    path.write_bytes(fallback_set_icon_svg(normalized_code or safe_slug.upper()))
    return path


def local_set_icon_url(slug: str) -> str:
    return f"/cache/set-icons/{slug.lower()}.svg"


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


_SET_STATS_LOCK = threading.Lock()
_SET_STATS_FILE_LOCK_TIMEOUT = 30.0
_SET_STATS_STALE_LOCK_SECONDS = 300.0


def _set_stats_lock_path() -> Path:
    return set_stats_cache_path().with_suffix(".lock")


class _SetStatsFileLock:
    def __init__(self, *, timeout: float = _SET_STATS_FILE_LOCK_TIMEOUT) -> None:
        self._path = _set_stats_lock_path()
        self._timeout = timeout
        self._fd: int | None = None

    def __enter__(self) -> "_SetStatsFileLock":
        self._path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.time() + self._timeout
        while time.time() < deadline:
            try:
                self._fd = os.open(self._path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                return self
            except FileExistsError:
                try:
                    age = time.time() - self._path.stat().st_mtime
                    if age > _SET_STATS_STALE_LOCK_SECONDS:
                        self._path.unlink()
                        continue
                except OSError:
                    pass
                time.sleep(0.05)
        raise CacheError("Verrou cache set_stats indisponible (autre instance serveur ?).")

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if self._fd is not None:
                os.close(self._fd)
                self._fd = None
        finally:
            try:
                self._path.unlink()
            except OSError:
                pass


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f"{path.suffix}.tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def _load_json_file(path: Path, *, default: Any) -> Any:
    if not path.exists():
        return default
    raw = path.read_text(encoding="utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        corrupt = path.with_suffix(f"{path.suffix}.corrupt")
        try:
            if corrupt.exists():
                corrupt.unlink()
            os.replace(path, corrupt)
        except OSError:
            path.unlink(missing_ok=True)
        return default


def load_set_stats_cache() -> dict[str, Any]:
    with _SET_STATS_LOCK:
        with _SetStatsFileLock():
            return _load_json_file(set_stats_cache_path(), default={})


def save_set_stats_cache(cache: dict[str, Any]) -> None:
    with _SET_STATS_LOCK:
        with _SetStatsFileLock():
            _atomic_write_text(
                set_stats_cache_path(),
                json.dumps(cache, ensure_ascii=False),
            )


def merge_set_stats_cache_entries(entries: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not entries:
        return load_set_stats_cache()
    normalized = {code.upper(): entry for code, entry in entries.items()}
    with _SET_STATS_LOCK:
        with _SetStatsFileLock():
            path = set_stats_cache_path()
            cache = _load_json_file(path, default={})
            cache.update(normalized)
            _atomic_write_text(path, json.dumps(cache, ensure_ascii=False))
            return cache


def upsert_set_stats_cache_entry(set_code: str, entry: dict[str, Any]) -> dict[str, Any]:
    code = set_code.upper()
    merge_set_stats_cache_entries({code: entry})
    return entry


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


def cached_set_codes() -> list[str]:
    sets_dir = cache_root() / "mtgjson" / "sets"
    if not sets_dir.exists():
        return []
    return sorted(path.stem.upper() for path in sets_dir.glob("*.json") if path.stat().st_size > 0)


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
