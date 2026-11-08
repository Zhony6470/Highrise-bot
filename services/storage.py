from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from threading import RLock
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
ROOT_DIR = Path(__file__).resolve().parent.parent
_lock = RLock()
_MISSING = object()

# Existing records were keyed only by basename. Keep these aliases so the
# first read of each namespaced file can migrate the old data without deleting
# the legacy record. The two data.json files intentionally both read the old
# shared record once; after migration, their writes are isolated.
_LEGACY_KEYS = {
    "bots/bot1/data/data.json": "data.json",
    "bots/fun/data/data.json": "data.json",
    "bots/bot1/data/posiciones.json": "posiciones.json",
}


def _storage_key(file_path) -> str:
    """Return a stable repository-relative key instead of a basename."""
    path = Path(file_path)
    try:
        return path.resolve().relative_to(ROOT_DIR.resolve()).as_posix()
    except ValueError:
        # Preserve compatibility for paths intentionally stored outside /app.
        return path.name


def _default_data(name, default=None):
    return {
        "data.json": {
            "users": {},
            "bot_position": {"x": 0, "y": 0, "z": 0, "facing": "FrontRight"},
        },
        "posiciones.json": {"posiciones": {}},
        "roles.json": {"vip_users": [], "users": {}},
    }.get(name, default if default is not None else {})


def _supabase_request(method, path, payload=None, params=""):
    url = f"{SUPABASE_URL}/rest/v1/{path}{params}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    }
    if payload is not None:
        headers["Content-Type"] = "application/json"
        headers["Prefer"] = "resolution=merge-duplicates,return=representation"
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers=headers,
        method=method,
    )
    with urlopen(request, timeout=15) as response:
        raw = response.read()
        return json.loads(raw) if raw else []


def _read_local(path: Path):
    try:
        with _lock, path.open(encoding="utf-8") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return _MISSING


def _write_local(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with _lock, tmp.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=4, ensure_ascii=False)
        file.flush()
        os.fsync(file.fileno())
    tmp.replace(path)


def _merge_legacy_data(local_data, legacy_data):
    """Keep local-only keys while preferring the previous Supabase values."""
    if not isinstance(local_data, dict) or not isinstance(legacy_data, dict):
        return legacy_data

    merged = deepcopy(local_data)
    for key, value in legacy_data.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


def _get_supabase_file(file_name: str):
    encoded_name = quote(file_name, safe="")
    return _supabase_request(
        "GET",
        "bot_files",
        params=f"?select=file_name,content&file_name=eq.{encoded_name}&limit=1",
    )


def load_json(file_path, default=None):
    path = Path(file_path)
    storage_key = _storage_key(path)

    if SUPABASE_URL and SUPABASE_KEY:
        try:
            rows = _get_supabase_file(storage_key)
            if rows:
                data = rows[0]["content"]
                # Keep the local copy current so a temporary Supabase outage
                # does not force the bot to fall back to an old snapshot.
                try:
                    _write_local(path, data)
                except OSError:
                    pass
                return data

            legacy_key = _LEGACY_KEYS.get(storage_key)
            if legacy_key:
                legacy_rows = _get_supabase_file(legacy_key)
                if legacy_rows:
                    local_data = _read_local(path)
                    legacy_data = legacy_rows[0]["content"]
                    data = (
                        _merge_legacy_data(local_data, legacy_data)
                        if local_data is not _MISSING
                        else legacy_data
                    )
                    # Save under the new key; deliberately leave the old
                    # shared record untouched as a recovery copy.
                    save_json(file_path, data)
                    return data

            local_data = _read_local(path)
            if local_data is not _MISSING:
                # Seed a new namespaced Supabase record from the local file.
                save_json(file_path, local_data)
                return local_data

            data = _default_data(path.name, default)
            save_json(file_path, data)
            return data
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, KeyError):
            pass

    local_data = _read_local(path)
    if local_data is not _MISSING:
        return local_data
    return _default_data(path.name, default)


def save_json(file_path, data):
    path = Path(file_path)
    storage_key = _storage_key(path)

    if SUPABASE_URL and SUPABASE_KEY:
        try:
            _supabase_request(
                "POST",
                "bot_files",
                {"file_name": storage_key, "content": data},
                params=f"?on_conflict=file_name",
            )
        except (HTTPError, URLError, TimeoutError, OSError, ValueError):
            pass

    # Always maintain a durable local mirror, whether or not Supabase worked.
    _write_local(path, data)
