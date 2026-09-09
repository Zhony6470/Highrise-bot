import asyncio
from json import loads
from os import environ
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen


class YouTubeSearchError(Exception):
    pass


async def search_video(query: str) -> dict:
    api_key = environ.get("YOUTUBE_API_KEY", "")
    if not api_key:
        raise YouTubeSearchError("YOUTUBE_API_KEY no está configurada.")

    parameters = urlencode({
        "part": "snippet",
        "q": query,
        "type": "video",
        "maxResults": 1,
        "videoLicense": "creativeCommon",
        "safeSearch": "none",
        "key": api_key,
    })
    url = f"https://www.googleapis.com/youtube/v3/search?{parameters}"

    try:
        response = await asyncio.to_thread(urlopen, url, timeout=10)
        payload = loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, ValueError) as error:
        raise YouTubeSearchError("No se pudo consultar YouTube.") from error

    if not payload.get("items"):
        raise YouTubeSearchError("No encontré resultados para esa búsqueda.")

    item = payload["items"][0]
    video_id = item.get("id", {}).get("videoId")
    snippet = item.get("snippet", {})
    if not video_id or not snippet.get("title"):
        raise YouTubeSearchError("YouTube devolvió un resultado incompleto.")

    return {
        "title": snippet["title"],
        "channel": snippet.get("channelTitle", "Canal desconocido"),
        "url": f"https://www.youtube.com/watch?v={video_id}",
    }
