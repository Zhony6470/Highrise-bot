import os
import json
import subprocess
from typing import Dict, Any

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