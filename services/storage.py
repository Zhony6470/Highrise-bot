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
            remote_data = response.data[0]["content"]
            if not _is_empty_data(file_name, remote_data):
                return remote_data
            try:
                with open(file_path, "r", encoding="utf-8") as file:
                    local_data = json.load(file)
            except (FileNotFoundError, json.JSONDecodeError):
                local_data = {}
            if not _is_empty_data(file_name, local_data):
                save_json(file_path, local_data)
                return local_data
            return remote_data

    try:
        with open(file_path, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}

    if _client:
        save_json(file_path, data)
    return data


def _is_empty_data(file_name: str, data: dict) -> bool:
    if file_name == "data.json":
        return not data.get("users") and data.get("bot_position") == {
            "x": 0, "y": 0, "z": 0, "facing": "FrontRight"
        }
    if file_name == "posiciones.json":
        return not data.get("posiciones")
    if file_name == "roles.json":
        return not data.get("users") and not data.get("vip_users")
    return not data


def save_json(file_path: str, data: dict) -> None:
    with open(file_path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4)

    if _client:
        _client.table("bot_files").upsert(
            {"file_name": Path(file_path).name, "content": data},
            returning="representation",
        ).execute()
