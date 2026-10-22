from __future__ import annotations

import asyncio

# Serializa los mensajes de todos los juegos del bot y deja tiempo para leerlos.
CHAT_INTERVAL_SECONDS = 2.0
_chat_lock = asyncio.Lock()
_last_chat_at = 0.0


async def send_game_chat(highrise, message: str) -> None:
    global _last_chat_at

    async with _chat_lock:
        loop = asyncio.get_running_loop()
        wait = CHAT_INTERVAL_SECONDS - (loop.time() - _last_chat_at)
        if wait > 0:
            await asyncio.sleep(wait)
        await highrise.chat(message)
        _last_chat_at = loop.time()
