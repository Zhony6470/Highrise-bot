import asyncio
from json import dumps
from os import environ
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class RadioRequestError(Exception):
    pass


async def request_playback(video_id: str, metadata: dict | None = None) -> None:
    endpoint = environ.get("RADIO_PLAYER_URL", "")
    token = environ.get("RADIO_PLAYER_TOKEN", "")
    if not endpoint or not token:
        raise RadioRequestError("La radio no está configurada en el bot.")

    payload = {"video_id": video_id}
    if metadata:
        payload["metadata"] = metadata

    request = Request(
        endpoint.rstrip("/") + "/play",
        data=dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        response = await asyncio.to_thread(urlopen, request, timeout=10)
        if response.status >= 300:
            raise RadioRequestError("El reproductor rechazó la solicitud.")
    except (HTTPError, URLError, TimeoutError) as error:
        raise RadioRequestError("No se pudo contactar el reproductor de radio.") from error
