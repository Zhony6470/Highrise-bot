from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class BotState:
    bot_name: str = ""
    position: dict[str, Any] | None = None
    outfit: list[Any] | None = None
    dance_emote: str = ""
    dance_enabled: bool = False
    reset_token: str = ""


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
        return BotState(
            bot_name=raw.get("bot_name", getattr(self.bot, "bot_username", "")),
            position=raw.get("position"),
            outfit=raw.get("outfit"),
            dance_emote=raw.get("dance_emote", ""),
            dance_enabled=bool(raw.get("dance_enabled", False)),
            reset_token=raw.get("reset_token", ""),
        )

    def save_state(self, state: BotState) -> None:
        payload = {
            "bot_name": state.bot_name,
            "position": state.position,
            "outfit": state.outfit,
            "dance_emote": state.dance_emote,
            "dance_enabled": state.dance_enabled,
            "reset_token": state.reset_token,
        }
        self.save(payload)

    def reset_state(self) -> None:
        self.save_state(BotState(bot_name=getattr(self.bot, "bot_username", "")))
