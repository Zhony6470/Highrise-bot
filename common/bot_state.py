from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class BotState:
    bot_name: str = ""
    outfit: list[Any] | None = None
    dance_enabled: bool = False
    bot_emote: str = ""
    bot_emote_enabled: bool = False
    active_mode: str = ""


class BotStateManager:
    """Persistencia para cada bot, guardando su estado por nombre."""

    def __init__(self, bot):
        self.bot = bot

    def _state_key(self) -> str:
        name = getattr(self.bot, "bot_username", "") or getattr(self.bot, "bot_id", "default")
        return f"bot_state_{name.lower()}"

    def load(self) -> dict[str, Any]:
        try:
            from services.storage import load_json
            data = load_json(getattr(self.bot, "state_file", "data.json"), default={})
            return data.get(self._state_key(), {})
        except Exception:
            return {}

    def save(self, state: dict[str, Any]) -> None:
        try:
            from services.storage import load_json, save_json
            file_path = getattr(self.bot, "state_file", "data.json")
            data = load_json(file_path, default={})
            data[self._state_key()] = state
            save_json(file_path, data)
        except Exception:
            pass

    def get_state(self) -> BotState:
        raw = self.load()
        active_mode = raw.get("active_mode", "")
        if not active_mode and raw.get("dance_enabled"):
            active_mode = "dance"
        return BotState(
            bot_name=raw.get("bot_name", getattr(self.bot, "bot_username", "")),
            outfit=raw.get("outfit"),
            dance_enabled=bool(raw.get("dance_enabled", False)),
            bot_emote=raw.get("bot_emote", ""),
            bot_emote_enabled=bool(raw.get("bot_emote_enabled", False)),
            active_mode=active_mode,
        )

    def save_state(self, state: BotState) -> None:
        payload = {
            "bot_name": state.bot_name,
            "outfit": state.outfit,
            "dance_enabled": state.dance_enabled,
            "bot_emote": state.bot_emote,
            "bot_emote_enabled": state.bot_emote_enabled,
            "active_mode": state.active_mode,
        }
        self.save(payload)

    def reset_state(self) -> None:
        self.save_state(BotState(bot_name=getattr(self.bot, "bot_username", "")))
