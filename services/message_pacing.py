from __future__ import annotations

import asyncio
import time
from typing import Any

# Ritmo conservador para que los mensajes consecutivos puedan leerse.
CHAT_INTERVAL_SECONDS = 2.5
WHISPER_INTERVAL_SECONDS = 1.5


def install_message_pacing(highrise: Any, *, chat_interval: float = CHAT_INTERVAL_SECONDS,
                           whisper_interval: float = WHISPER_INTERVAL_SECONDS) -> None:
    """Serializa y espacía chat y mensajes privados de una instancia de bot.

    Se instala una sola vez por cliente. No modifica llamadas de emotes, música,
    movimientos ni otras operaciones de la API.
    """
    if getattr(highrise, "_message_pacing_installed", False):
        return

    original_chat = highrise.chat
    original_whisper = highrise.send_whisper
    chat_lock = asyncio.Lock()
    whisper_lock = asyncio.Lock()
    last_chat = 0.0
    last_whisper = 0.0

    async def paced_chat(*args: Any, **kwargs: Any) -> Any:
        nonlocal last_chat
        async with chat_lock:
            now = time.monotonic()
            delay = chat_interval - (now - last_chat)
            if delay > 0:
                await asyncio.sleep(delay)
            result = await original_chat(*args, **kwargs)
            last_chat = time.monotonic()
            return result

    async def paced_whisper(*args: Any, **kwargs: Any) -> Any:
        nonlocal last_whisper
        async with whisper_lock:
            now = time.monotonic()
            delay = whisper_interval - (now - last_whisper)
            if delay > 0:
                await asyncio.sleep(delay)
            result = await original_whisper(*args, **kwargs)
            last_whisper = time.monotonic()
            return result

    highrise.chat = paced_chat
    highrise.send_whisper = paced_whisper
    highrise._message_pacing_installed = True
