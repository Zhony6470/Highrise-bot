import asyncio
from typing import Any

import yt_dlp


async def handle_play(bot, user, message: str) -> str | None:
    parts = message.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        return "Uso: /play <nombre de la canción>"

    query = parts[1].strip()
    await bot.highrise.chat(f"🎶 Iniciando búsqueda de: {query}...")
    track = await asyncio.to_thread(_search_track, query)
    if not track:
        return "⚠️ No encontré esa canción."

    queue = getattr(bot, "music_queue", None)
    if queue is None:
        bot.music_queue = []
        queue = bot.music_queue
    queue.append(track)
    position = len(queue)
    duration = _format_duration(track.get("duration"))
    await bot.highrise.chat(
        "🎶 CANCIÓN EN COLA 🎶\n"
        f"📌 Título: {track['title']}\n"
        f"🎙️ Artista: {track.get('artist', 'Desconocido')}\n"
        f"👤 Solicitante: {user.username}\n"
        f"⏱️ Duración: {duration}\n"
        f"📍 Posición en cola: {position}"
    )
    return None


async def handle_queue(bot, user, message: str) -> str:
    queue = getattr(bot, "music_queue", [])
    if not queue:
        return "🎶 La cola está vacía."
    lines = [
        f"{index}. {track['title']} ({_format_duration(track.get('duration'))})"
        for index, track in enumerate(queue[:10], start=1)
    ]
    return "🎶 COLA DE MÚSICA 🎶\n" + "\n".join(lines)


def _search_track(query: str) -> dict[str, Any] | None:
    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": False,
        "noplaylist": True,
        "default_search": "ytsearch",
    }
    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            search_term = query if query.startswith(("http://", "https://")) else f"ytsearch1:{query}"
            result = downloader.extract_info(search_term, download=False)
    except Exception as error:
        print(f"[MUSIC ERROR] No se pudo buscar '{query}': {error}")
        return None

    entries = result.get("entries") or []
    if not entries:
        print(f"[MUSIC] Sin resultados para: {query}")
        return None
    video = entries[0]
    return {
        "title": video.get("title", query),
        "artist": video.get("artist") or video.get("uploader") or "Desconocido",
        "duration": video.get("duration"),
        "url": video.get("webpage_url") or video.get("original_url"),
    }


def _format_duration(seconds: int | float | None) -> str:
    if not seconds:
        return "desconocida"
    total_seconds = int(seconds)
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}:{seconds:02d}"


COMMANDS = {
    "/play": handle_play,
    "!play": handle_play,
    "/queue": handle_queue,
    "!queue": handle_queue,
}
