import os
import asyncio
from typing import Optional, Dict, Any
from googleapiclient.discovery import build
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

# Carga cookies de sesión si el archivo existe
if os.path.exists(COOKIES_PATH):
    YTDL_OPTS['cookiefile'] = COOKIES_PATH


class YouTubeSearchError(Exception):
    pass


def search_youtube(query: str) -> Dict[str, str]:
    """Busca en YouTube API v3 (búsqueda general) y devuelve metadatos del video."""
    if not YOUTUBE_API_KEY:
        raise YouTubeSearchError("YOUTUBE_API_KEY no está configurada.")

    try:
        youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
        request = youtube.search().list(
            q=query,
            part="snippet",
            type="video",
            maxResults=1,
            safeSearch="none"
        )
        response = request.execute()
        items = response.get("items", [])
        
        if not items:
            raise YouTubeSearchError("No encontré resultados para esa búsqueda.")

        video = items[0]
        video_id = video.get("id", {}).get("videoId")
        snippet = video.get("snippet", {})
        
        if not video_id or not snippet.get("title"):
            raise YouTubeSearchError("YouTube devolvió un resultado incompleto.")

        return {
            "video_id": video_id,
            "title": snippet["title"],
            "channel": snippet.get("channelTitle", "Canal desconocido"),
            "url": f"https://www.youtube.com/watch?v={video_id}",
        }
    except Exception as e:
        if isinstance(e, YouTubeSearchError):
            raise e
        raise YouTubeSearchError("No se pudo consultar la API de YouTube.") from e


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