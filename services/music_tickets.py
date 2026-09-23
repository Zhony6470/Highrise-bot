from __future__ import annotations

import threading
import uuid
from pathlib import Path
from typing import Any

from services.storage import load_json, save_json


DATA_FILE = "/app/music_tickets.json"
GOLD_PER_BLOCK = 10
_lock = threading.RLock()


def _default_data() -> dict[str, Any]:
    return {
        "settings": {
            "tickets_per_10g": 1,
        },
        "users": {},
        "pending_requests": {},
    }


def _load() -> dict[str, Any]:
    data = load_json(DATA_FILE, default=_default_data())
    if not isinstance(data, dict):
        data = _default_data()

    data.setdefault("settings", {})
    data.setdefault("users", {})
    data.setdefault("pending_requests", {})
    data["settings"].setdefault("tickets_per_10g", 1)
    return data


def _save(data: dict[str, Any]) -> None:
    save_json(DATA_FILE, data)


def _user(data: dict[str, Any], user_id: str, username: str = "") -> dict[str, Any]:
    users = data["users"]
    entry = users.setdefault(
        user_id,
        {
            "username": username,
            "tickets": 0,
            "purchased_tickets": 0,
            "gifted_tickets": 0,
            "songs_requested": 0,
            "songs_played": 0,
            "refunded_tickets": 0,
            "total_tipped_gold": 0,
            "gold_remainder": 0,
        },
    )
    if username:
        entry["username"] = username
    return entry


class MusicTicketManager:
    def get_rate(self) -> int:
        with _lock:
            return int(_load()["settings"].get("tickets_per_10g", 1))

    def set_rate(self, tickets_per_10g: int) -> int:
        if tickets_per_10g < 1:
            raise ValueError("La cantidad de tickets debe ser mayor que 0.")
        with _lock:
            data = _load()
            data["settings"]["tickets_per_10g"] = tickets_per_10g
            _save(data)
            return tickets_per_10g

    def register_tip(self, user_id: str, username: str, gold: int) -> dict[str, int]:
        if gold <= 0:
            return {"tickets_added": 0, "tickets": 0, "purchased": 0, "remainder": 0}

        with _lock:
            data = _load()
            entry = _user(data, user_id, username)
            rate = int(data["settings"].get("tickets_per_10g", 1))

            entry["total_tipped_gold"] = int(entry.get("total_tipped_gold", 0)) + gold
            accumulated = int(entry.get("gold_remainder", 0)) + gold
            blocks, remainder = divmod(accumulated, GOLD_PER_BLOCK)
            added = blocks * rate

            entry["gold_remainder"] = remainder
            entry["tickets"] = int(entry.get("tickets", 0)) + added
            entry["purchased_tickets"] = int(entry.get("purchased_tickets", 0)) + added
            _save(data)

            return {
                "tickets_added": added,
                "tickets": int(entry["tickets"]),
                "purchased": int(entry["purchased_tickets"]),
                "remainder": remainder,
            }

    def add_tickets(self, user_id: str, username: str, amount: int) -> dict[str, int]:
        if amount < 1:
            raise ValueError("La cantidad de tickets debe ser mayor que 0.")

        with _lock:
            data = _load()
            entry = _user(data, user_id, username)
            entry["tickets"] = int(entry.get("tickets", 0)) + amount
            entry["gifted_tickets"] = int(entry.get("gifted_tickets", 0)) + amount
            _save(data)

            return {
                "tickets": int(entry["tickets"]),
                "purchased": int(entry.get("purchased_tickets", 0)),
            }

    def get_balance(self, user_id: str, username: str = "") -> dict[str, int]:
        with _lock:
            entry = _user(_load(), user_id, username)
            return {
                "tickets": int(entry.get("tickets", 0)),
                "purchased": int(entry.get("purchased_tickets", 0)),
                "songs_requested": int(entry.get("songs_requested", 0)),
                "songs_played": int(entry.get("songs_played", 0)),
            }

    def charge_request(
        self,
        user_id: str,
        username: str,
        video_id: str,
        title: str,
    ) -> tuple[str | None, str | None]:
        with _lock:
            data = _load()
            entry = _user(data, user_id, username)
            tickets = int(entry.get("tickets", 0))
            if tickets < 1:
                return None, "No tienes tickets disponibles. Da oro al bot de música para obtener tickets."

            request_id = uuid.uuid4().hex
            entry["tickets"] = tickets - 1
            entry["songs_requested"] = int(entry.get("songs_requested", 0)) + 1

            data["pending_requests"][request_id] = {
                "user_id": user_id,
                "username": username,
                "video_id": video_id,
                "title": title,
                "status": "pending",
                "ticket_charged": 1,
            }
            _save(data)
            return request_id, None

    def mark_played(self, request_id: str) -> bool:
        with _lock:
            data = _load()
            request = data["pending_requests"].get(request_id)
            if not request or request.get("status") != "pending":
                return False

            request["status"] = "played"
            entry = _user(data, request["user_id"], request.get("username", ""))
            entry["songs_played"] = int(entry.get("songs_played", 0)) + 1
            _save(data)
            return True

    def refund_request(self, request_id: str) -> dict[str, Any] | None:
        with _lock:
            data = _load()
            request = data["pending_requests"].get(request_id)
            if not request or request.get("status") != "pending":
                return None

            request["status"] = "refunded"
            entry = _user(data, request["user_id"], request.get("username", ""))
            entry["tickets"] = int(entry.get("tickets", 0)) + 1
            entry["refunded_tickets"] = int(entry.get("refunded_tickets", 0)) + 1
            _save(data)

            return {
                "user_id": request["user_id"],
                "username": request.get("username", ""),
                "title": request.get("title", "Pista desconocida"),
                "tickets": int(entry["tickets"]),
            }

    def pending_request(self, request_id: str) -> dict[str, Any] | None:
        with _lock:
            request = _load()["pending_requests"].get(request_id)
            return dict(request) if request else None

    def get_request(self, request_id: str) -> dict[str, Any] | None:
        with _lock:
            request = _load()["pending_requests"].get(request_id)
            return dict(request) if request else None
