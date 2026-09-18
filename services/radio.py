import asyncio
from json import dumps
from os import environ
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from json import loads


class RadioRequestError(Exception):
    pass


def _radio_request_config() -> tuple[str, str]:
    endpoint = environ.get("RADIO_PLAYER_URL", "").strip()
    token = environ.get("RADIO_PLAYER_TOKEN", "").strip()
    if not endpoint or not token:
        raise RadioRequestError("La radio no está configurada en el bot.")
    return endpoint.rstrip("/"), token


async def _call_radio_with_retry(request, *, timeout: float, error_message: str, allow_http_error: bool = False):
    last_error = None
    for attempt in range(2):
        try:
            response = await asyncio.to_thread(urlopen, request, timeout=timeout)
            if getattr(response, "status", 200) >= 300 and not allow_http_error:
                raise RadioRequestError("El reproductor rechazó la solicitud.")
            return response
        except HTTPError:
            if allow_http_error:
                raise
            last_error = None
            break
        except (URLError, TimeoutError, ValueError) as error:
            last_error = error
            if attempt == 1:
                break
            await asyncio.sleep(0.5)
    if last_error is not None:
        raise RadioRequestError(error_message) from last_error
    raise RadioRequestError(error_message)


async def request_playback(video_id: str, metadata: dict | None = None) -> None:
    endpoint, token = _radio_request_config()

    payload = {"video_id": video_id, "requested_track": True}
    if metadata:
        payload["metadata"] = metadata

    request = Request(
        endpoint + "/play",
        data=dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        response = await _call_radio_with_retry(request, timeout=10, error_message="No se pudo contactar el reproductor de radio.")
        if getattr(response, "status", 200) >= 300:
            raise RadioRequestError("El reproductor rechazó la solicitud.")
    except RadioRequestError:
        raise
    except Exception as error:
        raise RadioRequestError("No se pudo contactar el reproductor de radio.") from error


async def request_radio_state() -> dict:
    endpoint, token = _radio_request_config()

    request = Request(
        endpoint + "/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        response = await _call_radio_with_retry(request, timeout=5, error_message="No se pudo consultar la radio.")
        return loads(response.read().decode("utf-8"))
    except RadioRequestError:
        raise
    except (ValueError) as error:
        raise RadioRequestError("No se pudo consultar la radio.") from error


async def request_skip() -> None:
    endpoint, token = _radio_request_config()

    request = Request(
        endpoint + "/skip",
        headers={"Authorization": f"Bearer {token}"},
        method="POST",
    )
    try:
        response = await _call_radio_with_retry(request, timeout=5, error_message="No se pudo saltar la canción actual.")
        if getattr(response, "status", 200) >= 300:
            raise RadioRequestError("La radio rechazó el salto.")
    except RadioRequestError:
        raise
    except Exception as error:
        raise RadioRequestError("No se pudo saltar la canción actual.") from error


async def update_default_playlist(video: dict, remove: bool = False) -> None:
    endpoint, token = _radio_request_config()
    payload = {
        "video_id": video["video_id"],
        "metadata": {
            key: video.get(key)
            for key in ("title", "channel", "url", "duration")
            if video.get(key) is not None
        },
    }
    path = "/default-remove" if remove else "/default-add"
    request = Request(
        endpoint + path,
        data=dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    try:
        response = await _call_radio_with_retry(
            request,
            timeout=10,
            error_message="No se pudo contactar la radio.",
            allow_http_error=True,
        )
        if getattr(response, "status", 200) >= 300:
            raise RadioRequestError("La playlist rechazó la operación.")
    except HTTPError as error:
        if error.code == 409:
            raise RadioRequestError("La canción ya está en la playlist.") from error
        if error.code == 404:
            raise RadioRequestError("La canción no está en la playlist.") from error
        raise RadioRequestError("No se pudo modificar la playlist.") from error
    except RadioRequestError:
        raise
    except Exception as error:
        raise RadioRequestError("No se pudo contactar la radio.") from error


async def request_default_playlist() -> list[dict]:
    endpoint, token = _radio_request_config()
    request = Request(
        endpoint + "/default-playlist",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        response = await _call_radio_with_retry(request, timeout=5, error_message="No se pudo consultar la playlist por defecto.")
        return loads(response.read().decode("utf-8"))
    except RadioRequestError:
        raise
    except (ValueError) as error:
        raise RadioRequestError("No se pudo consultar la playlist por defecto.") from error
