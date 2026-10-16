from __future__ import annotations

import asyncio
from random import choice


class DanceManager:
    """Gestiona los dos modos persistentes de emote del bot."""

    def __init__(self, bot):
        self.bot = bot
        self.task = None

    def state(self):
        return self.bot.bot_state_manager.get_state()

    def save(self, state):
        self.bot.bot_state_manager.save_state(state)

    async def restore(self) -> None:
        state = self.state()
        if state.active_mode == "dance" and state.dance_enabled:
            await self.start_random_dance(send_message=False)
        elif state.active_mode == "emote" and state.bot_emote_enabled and state.bot_emote:
            await self.start_bot_emote(state.bot_emote, send_message=False)

    async def start_random_dance(self, send_message: bool = True) -> str:
        public_emotes = [
            emote for emote in getattr(self.bot, "emotes_list", [])
            if emote.get("auth") == "public" and isinstance(emote.get("emote"), str)
        ]
        if not public_emotes:
            return "<#FFCC66>🎵 No hay emotes públicos configurados para bailar."
        await self._stop_runtime()
        state = self.state()
        state.dance_enabled = True
        state.bot_emote_enabled = False
        state.active_mode = "dance"
        self.save(state)
        self.task = asyncio.create_task(self._random_dance_loop(public_emotes))
        return "<#66FF99>💃 Baile del bot activado." if send_message else ""

    async def _random_dance_loop(self, public_emotes) -> None:
        loop = asyncio.get_running_loop()
        next_send_at = loop.time()

        while True:
            try:
                emote = choice(public_emotes)
                emote_id = emote["emote"]
                duration = max(float(emote.get("duration", 3)), 0.1)
                interval = max(duration - 0.35, 0.1)

                self.bot.current_bot_emote = emote_id
                send_started_at = loop.time()
                next_send_at = max(next_send_at, send_started_at)
                await self.bot.highrise.send_emote(emote_id, self.bot.bot_id)
                next_send_at = max(next_send_at, send_started_at) + interval
                await asyncio.sleep(max(0.0, next_send_at - loop.time()))
            except asyncio.CancelledError:
                return
            except Exception as error:
                print(f"Error en el baile del bot: {error}")
                await asyncio.sleep(1)
                next_send_at = loop.time()

    async def _stop_runtime(self) -> None:
        if self.task:
            self.task.cancel()
            self.task = None
        self.bot.current_bot_emote = None
        try:
            await self.bot.highrise.send_emote("", self.bot.bot_id)
        except Exception:
            pass

    async def stop_dance(self, send_message: bool = True) -> str:
        await self._stop_runtime()
        state = self.state()
        state.dance_enabled = False
        state.bot_emote_enabled = False
        state.active_mode = ""
        self.save(state)
        return "<#66CCFF>⏹️ Baile detenido para este bot." if send_message else ""

    async def start_bot_emote(self, emote_id: str, send_message: bool = True) -> str:
        await self._stop_runtime()
        state = self.state()
        state.bot_emote = emote_id
        state.bot_emote_enabled = True
        state.dance_enabled = False
        state.active_mode = "emote"
        self.save(state)
        self.task = asyncio.create_task(self._bot_emote_loop(emote_id))
        return f"<#66FF99>✨ Emote del bot activado: {emote_id}." if send_message else ""

    async def _bot_emote_loop(self, emote_id: str) -> None:
        duration = max(float(next(
            (item.get("duration", 1) for item in getattr(self.bot, "emotes_list", [])
             if item.get("emote") == emote_id),
            1,
        )), 0.1)
        # Reenviar antes de la fase de recuperación/levantarse del avatar.
        # Es una prueba de continuidad visual; la API normal no expone loop nativo.
        interval = max(duration * 0.97, 0.1)
        loop = asyncio.get_running_loop()
        next_send_at = loop.time()

        try:
            while True:
                self.bot.current_bot_emote = emote_id
                send_started_at = loop.time()
                await self.bot.highrise.send_emote(emote_id, self.bot.bot_id)

                # Schedule from the start of the request, not its response.
                # This avoids adding network latency to every emote cycle.
                next_send_at = max(next_send_at, send_started_at) + interval
                await asyncio.sleep(max(0.0, next_send_at - loop.time()))
        except asyncio.CancelledError:
            return
        except Exception as error:
            print(f"Error en el emote persistente del bot: {error}")

    async def stop_bot_emote(self) -> str:
        await self._stop_runtime()
        state = self.state()
        state.dance_enabled = False
        state.bot_emote_enabled = False
        state.active_mode = ""
        self.save(state)
        return "<#66CCFF>⏹️ Emote del bot detenido."
