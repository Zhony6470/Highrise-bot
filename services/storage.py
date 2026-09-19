from __future__ import annotations

import json
import os
from pathlib import Path

try:
    from supabase import Client, create_client
except ImportError:  # pragma: no cover - fallback local storage when supabase is absent
    Client = None  # type: ignore[assignment]
    create_client = None  # type: ignore[assignment]


SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
_client: Client | None = (
    create_client(SUPABASE_URL, SUPABASE_KEY)
    if create_client and SUPABASE_URL and SUPABASE_KEY
    else None
)


def load_json(file_path: str, default=None):
    file_name = Path(file_path).name
    if _client:
        response = (
            _client.table("bot_files")
            .select("file_name, content")
            .execute()
        )
        matching_rows = [row for row in response.data if row.get("file_name") == file_name]
        if matching_rows:
            return matching_rows[0]["content"]

        data = _default_data(file_name, default)
        save_json(file_path, data)
        return data

    try:
        with open(file_path, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        data = _default_data(file_name, default)

    return data


def _default_data(file_name: str, default=None):
    if file_name == "data.json":
        return {
            "users": {},
            "bot_position": {"x": 0, "y": 0, "z": 0, "facing": "FrontRight"},
        }
    if file_name == "posiciones.json":
        return {"posiciones": {}}
    if file_name == "roles.json":
        return {"vip_users": [], "users": {}}
    return default if default is not None else {}


def save_json(file_path: str, data: dict) -> None:
    if _client:
        try:
            _client.table("bot_files").upsert(
                {"file_name": Path(file_path).name, "content": data},
                returning="representation",
            ).execute()
            print(f"[STORAGE] Guardado en Supabase: {Path(file_path).name}")
        except Exception as error:
            print(f"[STORAGE ERROR] No se pudo guardar {Path(file_path).name}: {error}")
            raise
        return

    with open(file_path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4)
