from __future__ import annotations
import json
import os
from pathlib import Path
from threading import RLock
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
_lock = RLock()


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


def load_json(file_path, default=None):
    path = Path(file_path)

    if SUPABASE_URL and SUPABASE_KEY:
        try:
            file_name = quote(path.name, safe="")
            rows = _supabase_request(
                "GET",
                "bot_files",
                params=f"?select=file_name,content&file_name=eq.{file_name}&limit=1",
            )
            if rows:
                return rows[0]["content"]

            data = _default_data(path.name, default)
            save_json(file_path, data)
            return data
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, KeyError):
            pass

    try:
        with _lock, path.open(encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return _default_data(path.name, default)


def save_json(file_path, data):
    path = Path(file_path)

    if SUPABASE_URL and SUPABASE_KEY:
        try:
            _supabase_request(
                "POST",
                "bot_files",
                {"file_name": path.name, "content": data},
                params="?on_conflict=file_name",
            )
            return
        except (HTTPError, URLError, TimeoutError, OSError, ValueError):
            pass

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with _lock, tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)
