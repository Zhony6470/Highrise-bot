from __future__ import annotations

import asyncio


class DanceManager:
    """Gestión común de baile y emotes persistentes por bot."""

    def __init__(self, bot):
        self.bot = bot
        self.config = getattr(bot, "dance_config", {})

    def load_config(self):
        state_manager = getattr(self.bot, "bot_state_manager", None)
        if state_manager is not None:
            state = state_manager.get_state()
            config = getattr(self.bot, "dance_config", {})
            config["dance_emote"] = state.dance_emote or config.get("dance_emote", "")
            config["dance_enabled"] = bool(state.dance_enabled or config.get("dance_enabled", False))
            self.bot.dance_config = config
            return config
        return getattr(self.bot, "dance_config", {})

    def save_config(self, data):
        self.bot.dance_config = data
        state_manager = getattr(self.bot, "bot_state_manager", None)
        if state_manager is not None:
            state = state_manager.get_state()
            state.dance_emote = str(data.get("dance_emote", ""))
            state.dance_enabled = bool(data.get("dance_enabled", False))
            state_manager.save_state(state)

    async def set_dance_emote(self, emote_id: str) -> str:
        config = self.load_config()
        config["dance_emote"] = emote_id
        config["dance_enabled"] = True
        self.save_config(config)
        return f"<#66FF99>✨ Emote de baile configurado: {emote_id}."

    async def start_dance(self, emote_id: str | None = None) -> str:
        config = self.load_config()
        chosen = emote_id or config.get("dance_emote")
        if not chosen:
            return "<#FFCC66>🎵 No hay un emote de baile configurado para este bot."
        config["dance_enabled"] = True
        config["dance_emote"] = chosen
        self.save_config(config)
        return f"<#66FF99>🎵 Baile activado con emote: {chosen}."

    async def stop_dance(self) -> str:
        config = self.load_config()
        config["dance_enabled"] = False
        self.save_config(config)
        try:
            await self.bot.highrise.send_emote("", self.bot.bot_id)
        except Exception:
            pass
        return "<#66CCFF>⏹️ Baile detenido para este bot."
