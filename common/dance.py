from __future__ import annotations

import asyncio
from random import choice


class DanceManager:
    """Gestión común de baile y emotes persistentes por bot."""

    def __init__(self, bot):
        self.bot = bot
        self.config = getattr(bot, "dance_config", {})

    def load_config(self):
        state_manager = getattr(self.bot, "bot_state_manager", None)
        if state_manager is not None:
            state = state_manager.get_state()
            return {"dance_emote": state.dance_emote, "dance_enabled": state.dance_enabled}
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

    async def start_random_dance(self) -> str:
        public_emotes = [
            emote for emote in getattr(self.bot, "emotes_list", [])
            if emote.get("auth") == "public" and isinstance(emote.get("emote"), str)
        ]
        if not public_emotes:
            return "<#FFCC66>🎵 No hay emotes públicos configurados para bailar."
        await self.stop_dance(send_message=False)
        config = self.load_config()
        config["dance_enabled"] = True
        self.save_config(config)
        self.bot.dance_task = asyncio.create_task(self._random_dance_loop(public_emotes))
        return "<#66FF99>💃 Baile del bot activado."

    async def _random_dance_loop(self, public_emotes) -> None:
        try:
            while True:
                emote = choice(public_emotes)
                self.bot.current_bot_emote = emote["emote"]
                await self.bot.highrise.send_emote(emote["emote"], self.bot.bot_id)
                await asyncio.sleep(emote.get("duration", 3))
        except asyncio.CancelledError:
            return
        except Exception as error:
            print(f"Error en el baile del bot: {error}")

    async def stop_dance(self, send_message: bool = True) -> str:
        config = self.load_config()
        config["dance_enabled"] = False
        self.save_config(config)
        task = getattr(self.bot, "dance_task", None)
        if task:
            task.cancel()
            self.bot.dance_task = None
        self.bot.current_bot_emote = None
        try:
            await self.bot.highrise.send_emote("", self.bot.bot_id)
        except Exception:
            pass
        return "<#66CCFF>⏹️ Baile detenido para este bot." if send_message else ""
