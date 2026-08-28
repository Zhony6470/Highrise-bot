import json
import os
from pathlib import Path

from supabase import Client, create_client


SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
_client: Client | None = (
    create_client(SUPABASE_URL, SUPABASE_KEY)
    if SUPABASE_URL and SUPABASE_KEY
    else None
)


def load_json(file_path: str) -> dict:
    file_name = Path(file_path).name
    if _client:
        response = (
            _client.table("bot_files")
            .select("content")
            .filter("file_name", "eq", f'"{file_name}"')
            .limit(1)
            .execute()
        )
        if response.data:
            return response.data[0]["content"]

        data = _default_data(file_name)
        save_json(file_path, data)
        return data

    try:
        with open(file_path, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}

    if _client:
        save_json(file_path, data)
    return data


def _default_data(file_name: str) -> dict:
    if file_name == "data.json":
        return {
            "users": {},
            "bot_position": {"x": 0, "y": 0, "z": 0, "facing": "FrontRight"},
        }
    if file_name == "posiciones.json":
        return {"posiciones": {}}
    if file_name == "roles.json":
        return {"vip_users": [], "users": {}}
    return {}


def save_json(file_path: str, data: dict) -> None:
    if _client:
        _client.table("bot_files").upsert(
            {"file_name": Path(file_path).name, "content": data},
            returning="representation",
        ).execute()
        return

    with open(file_path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4)
