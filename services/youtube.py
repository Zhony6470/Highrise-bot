import os
import asyncio
import json
import subprocess
from typing import Optional, Dict, Any
import re
import yt_dlp

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
COOKIES_PATH = os.path.join(os.path.dirname(__file__), "cookies.txt")

# Configuración avanzada de yt-dlp para mitigar bloqueos en VPS
YTDL_OPTS: Dict[str, Any] = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,
    'retries': 10,
    'extractor_args': {
        'youtube': {
            'player_client': ['ios', 'android', 'web_embedded'],
            'skip': ['hls', 'dash']
        }
    }
}


def _duration_seconds(value: str) -> int | None:
    match = re.fullmatch(
        r"P(?:(?P<days>\d+)D)?T(?:(?P<hours>\d+)H)?"
        r"(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?",
        value,
    )
    if not match:
        return None
    parts = {key: int(number or 0) for key, number in match.groupdict().items()}
    return parts["days"] * 86400 + parts["hours"] * 3600 + parts["minutes"] * 60 + parts["seconds"]

# Carga cookies de sesión si el archivo existe
if os.path.exists(COOKIES_PATH):
    YTDL_OPTS['cookiefile'] = COOKIES_PATH


class YouTubeSearchError(Exception):
    pass


def search_youtube(query: str) -> Dict[str, str]:
    """Busca en YouTube usando yt-dlp y devuelve metadatos con la misma estructura que usa main.py."""
    command = [
        "yt-dlp",
        "--dump-single-json",
        "--no-playlist",
        "--flat-playlist",
        f"ytsearch1:{query}",
    ]

    if os.path.exists(COOKIES_PATH):
        command.extend(["--cookies", COOKIES_PATH])

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=45,
            check=True,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise YouTubeSearchError("No pude buscar la canción ahora mismo.") from error

    try:
        data = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as error:
        raise YouTubeSearchError("La respuesta de búsqueda de YouTube no es válida.") from error

    entries = data.get("entries") or []
    if not entries:
        raise YouTubeSearchError("No encontré ninguna canción con ese nombre.")

    entry = entries[0]
    video_id = entry.get("id")
    title = entry.get("title") or "Pista desconocida"
    channel = entry.get("channel") or entry.get("uploader") or "Canal desconocido"
    duration = entry.get("duration")

    if not video_id:
        raise YouTubeSearchError("YouTube devolvió un resultado incompleto.")

    return {
        "video_id": video_id,
        "title": title,
        "channel": channel,
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "duration": duration,
    }


async def extract_stream_info(video_id_or_url: str) -> Optional[Dict[str, Any]]:
    """Resuelve la URL directa del audio usando yt-dlp con las opciones anti-bloqueo."""
    loop = asyncio.get_event_loop()
    url = (
        video_id_or_url
        if video_id_or_url.startswith("http")
        else f"https://www.youtube.com/watch?v={video_id_or_url}"
    )

    def _extract():
        with yt_dlp.YoutubeDL(YTDL_OPTS) as ytdl:
            info = ytdl.extract_info(url, download=False)
            if 'entries' in info:
                info = info['entries'][0]
            return {
                "stream_url": info.get("url"),
                "title": info.get("title"),
                "artist": info.get("uploader"),
                "duration": info.get("duration")
            }

    try:
        return await loop.run_in_executor(None, _extract)
    except Exception as e:
        print(f"[Error yt-dlp]: {e}")
        return None