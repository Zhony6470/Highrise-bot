import json
import os
import random
import subprocess
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = os.getenv("AUTODJ_HOST", "0.0.0.0")
PORT = int(os.getenv("AUTODJ_PORT", "8090"))
TOKEN = os.getenv("AUTODJ_TOKEN", "")
if not TOKEN:
    raise RuntimeError("AUTODJ_TOKEN es obligatorio.")

CACHE = Path(os.getenv("AUTODJ_CACHE_DIR", "/data/cache"))
DEFAULT = Path(os.getenv("AUTODJ_DEFAULT_DIR", "/data/default_music"))
QUEUE_FILE = Path(os.getenv("AUTODJ_QUEUE_FILE", "/data/request_queue.json"))
RESULT_FILE = Path(os.getenv("AUTODJ_RESULT_FILE", "/data/last_request_result.json"))
PLAYLIST = Path(os.getenv("AUTODJ_PLAYLIST_FILE", "/data/default_playlist.json"))
COOKIES = os.getenv("YOUTUBE_COOKIES_PATH", "/app/cookies.txt")

queue = deque()
lock = threading.RLock()
state = {"current": None, "started_at": None, "status": "idle", "last_default_id": None, "last_request_results": []}

# Locks for concurrent yt-dlp downloads and background prefetch workers.
download_lock = threading.RLock()
prefetch_lock = threading.RLock()
prefetching = set()


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        return default


def save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def metadata(item: dict) -> dict:
    return item.get("metadata") or {
        "title": item.get("title", "Pista desconocida"),
        "channel": item.get("channel", "Highrise Radio"),
        "duration": item.get("duration"),
    }


def authorized(handler) -> bool:
    return not TOKEN or handler.headers.get("Authorization", "") == f"Bearer {TOKEN}"


def queue_snapshot():
    with lock:
        items = list(queue)
        return items


def ensure_file(item: dict) -> Path:
    existing = item.get("file_path")
    if existing and Path(existing).exists():
        return Path(existing)

    video_id = item.get("video_id")
    if not video_id:
        raise RuntimeError("La pista no tiene video_id.")

    CACHE.mkdir(parents=True, exist_ok=True)
    matches = list(CACHE.glob(video_id + ".*"))
    if matches:
        return matches[0]

    # No forzamos ios/android/web_embedded. YouTube puede rechazar
    # web_embedded cuando el propietario desactiva la reproducción externa,
    # aunque el video siga siendo visible normalmente.
    #
    # Primera opción: sesión pública sin cookies, usando los clientes por
    # defecto de yt-dlp. Esto evita que una cookie de sesión vieja rompa
    # videos públicos.
    profiles = [
        ("public-default", [
            "yt-dlp",
            "--no-playlist",
            "--no-part",
            "-f", "bestaudio/best",
            "--extractor-args", "youtube:player_client=default",
            "-o", str(CACHE / "%(id)s.%(ext)s"),
        ]),
    ]

    # Segunda opción: si el video necesita autenticación/cookies, permitir
    # clientes que aceptan cookies. No usamos web_embedded aquí porque solo
    # sirve para videos que permiten reproducción embebida.
    cookie_command = [
        "yt-dlp",
        "--no-playlist",
        "--no-part",
        "-f", "bestaudio/best",
        "--extractor-args", "youtube:player_client=default,web_safari",
        "-o", str(CACHE / "%(id)s.%(ext)s"),
    ]
    if Path(COOKIES).exists():
        cookie_command += ["--cookies", COOKIES]
        profiles.append(("cookies-default", cookie_command))

    with download_lock:
        # Re comprobar después de adquirir el lock: otra tarea puede haber
        # terminado la descarga mientras esperábamos.
        matches = list(CACHE.glob(video_id + ".*"))
        if matches:
            return matches[0]

        last_error = None
        for profile_name, command in profiles:
            try:
                print(
                    f"[AUTODJ] YT-DLP: intentando {profile_name} para {video_id}",
                    flush=True,
                )
                subprocess.run(
                    command + [f"https://www.youtube.com/watch?v={video_id}"],
                    check=True,
                    timeout=180,
                )
                matches = list(CACHE.glob(video_id + ".*"))
                if matches:
                    print(
                        f"[AUTODJ] YT-DLP: descarga OK con {profile_name} para {video_id}",
                        flush=True,
                    )
                    return matches[0]
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
                last_error = error
                # El primer perfil puede fallar por restricciones del cliente;
                # probamos el segundo antes de marcar la pista como fallida.
                continue

        raise RuntimeError(
            f"yt-dlp no pudo descargar {video_id} con los perfiles disponibles: {last_error}"
        )

    matches = list(CACHE.glob(video_id + ".*"))
    if not matches:
        raise RuntimeError("yt-dlp no generó el archivo de audio.")
    return matches[0]


def choose_default():
    playlist = load(PLAYLIST, [])
    if playlist:
        candidates = [
            item for item in playlist
            if item.get("video_id") or item.get("file_path")
        ]
        if candidates:
            with lock:
                last_id = state.get("last_default_id")

            if len(candidates) > 1 and last_id:
                filtered = [
                    item for item in candidates
                    if (item.get("video_id") or item.get("file_path")) != last_id
                ]
                if filtered:
                    candidates = filtered

            item = dict(random.choice(candidates))
            item["default_track"] = True
            return item

    files = [
        path for path in DEFAULT.iterdir()
        if path.is_file() and path.suffix.lower() in {
            ".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".webm", ".opus"
        }
    ]

    if not files:
        return None

    with lock:
        last_id = state.get("last_default_id")

    candidates = [path for path in files if str(path) != str(last_id)]

    if not candidates:
        candidates = files

    path = random.choice(candidates)

    return {
        "file_path": str(path),
        "title": path.stem,
        "default_track": True,
    }


def set_request_result(item: dict, status: str, error: str | None = None) -> None:
    request_id = item.get("request_id")
    if not request_id:
        return

    result = {
        "request_id": request_id,
        "status": status,
        "video_id": item.get("video_id"),
        "metadata": metadata(item),
    }
    if error:
        result["error"] = error

    with lock:
        results = state.setdefault("last_request_results", [])
        results.append(result)
        state["last_request_results"] = results[-200:]
        save(RESULT_FILE, state["last_request_results"])



def prefetch_item(item: dict) -> None:
    """Descarga en segundo plano la siguiente pista para evitar huecos entre canciones."""
    if not item:
        return

    video_id = item.get("video_id")
    file_path = item.get("file_path")
    key = video_id or file_path
    if not key:
        return

    with prefetch_lock:
        if key in prefetching:
            return
        prefetching.add(key)

    def worker():
        original_item = item
        resolved_item = original_item
        try:
            path = ensure_file(original_item)
            original_item["file_path"] = str(path)
            request_id = original_item.get("request_id")
            with lock:
                if request_id:
                    for queued in queue:
                        if queued.get("request_id") == request_id:
                            queued["file_path"] = str(path)
                            # Reutilizamos el mismo objeto para que el controller
                            # pueda enviarlo a Liquidsoap con file_path ya resuelto.
                            resolved_item = queued
                            break
                save(QUEUE_FILE, list(queue))
            print(
                f"[AUTODJ] PRELOAD: {resolved_item.get('metadata', {}).get('title', resolved_item.get('title', 'Pista'))}",
                flush=True,
            )
            if liquidsoap_controller is not None and not resolved_item.get("default_track"):
                liquidsoap_controller.enqueue_request(resolved_item)
        except Exception as error:
            print(f"[AUTODJ] Error precargando pista: {error}", flush=True)
        finally:
            with prefetch_lock:
                prefetching.discard(key)

    threading.Thread(target=worker, daemon=True, name="autodj-prefetch").start()


def _make_liquidsoap_controller():
    if os.getenv("AUTODJ_USE_LIQUIDSOAP", "0") != "1":
        return None
    from liquidsoap_controller import LiquidsoapController
    return LiquidsoapController(
        queue=queue, lock=lock, state=state, queue_file=QUEUE_FILE,
        result_writer=set_request_result, metadata_fn=metadata,
        choose_default=choose_default, ensure_file=ensure_file, save_fn=save,
    )


liquidsoap_controller = _make_liquidsoap_controller()

class API(BaseHTTPRequestHandler):
    def reply(self, code: int, value) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw)

    def do_GET(self):
        if not authorized(self):
            return self.reply(401, {"error": "unauthorized"})

        if self.path == "/health":
            return self.reply(200, {"ok": True, "service": "autodj"})

        if self.path == "/status":
            with lock:
                snapshot = dict(state)
                snapshot["current"] = (
                    dict(state["current"]) if state.get("current") else None
                )
                started = state.get("started_at")
                snapshot["elapsed"] = time.time() - started if started else 0
                snapshot["queue"] = queue_snapshot()
            return self.reply(200, snapshot)

        if self.path == "/queue":
            return self.reply(200, queue_snapshot())

        if self.path == "/default-playlist":
            return self.reply(200, load(PLAYLIST, []))

        return self.reply(404, {"error": "not_found"})

    def do_POST(self):
        if not authorized(self):
            return self.reply(401, {"error": "unauthorized"})

        try:
            data = self.body()

            if self.path == "/play":
                video_id = str(data.get("video_id", "")).strip()
                if not video_id:
                    return self.reply(400, {"error": "missing_video_id"})

                item = {
                    "video_id": video_id,
                    "metadata": data.get("metadata", {}),
                    "request_id": data.get("request_id"),
                    "requested_track": True,
                }

                with lock:
                    queue.append(item)
                    save(QUEUE_FILE, list(queue))
                # Resolver la URL mientras la pista actual sigue sonando.
                # Esto hace que !play/!skip no tenga que esperar a yt-dlp.
                prefetch_item(item)
                return self.reply(200, {"ok": True, "queued": item})

            if self.path == "/skip":
                if liquidsoap_controller is None:
                    return self.reply(503, {"error": "liquidsoap_controller_unavailable"})
                liquidsoap_controller.skip()
                return self.reply(200, {"ok": True, "active": True})

            if self.path in ("/default-add", "/default-remove"):
                playlist = load(PLAYLIST, [])
                if not isinstance(playlist, list):
                    playlist = []

                video_id = str(data["video_id"]).strip()
                if not video_id:
                    return self.reply(400, {"error": "video_id_required"})

                if self.path == "/default-add":
                    if any(
                        isinstance(item, dict) and item.get("video_id") == video_id
                        for item in playlist
                    ):
                        return self.reply(409, {"error": "already_exists"})

                    playlist.append({
                        "video_id": video_id,
                        "metadata": data.get("metadata", {}),
                    })
                else:
                    old_length = len(playlist)
                    playlist = [
                        item for item in playlist
                        if not isinstance(item, dict)
                        or item.get("video_id") != video_id
                    ]
                    if len(playlist) == old_length:
                        return self.reply(404, {"error": "not_found"})

                save(PLAYLIST, playlist)
                return self.reply(200, {"ok": True, "playlist": playlist})

            return self.reply(404, {"error": "not_found"})

        except Exception as error:
            return self.reply(400, {"error": str(error)})

    def log_message(self, *_):
        return


if __name__ == "__main__":
    CACHE.mkdir(parents=True, exist_ok=True)
    DEFAULT.mkdir(parents=True, exist_ok=True)

    stored_results = load(RESULT_FILE, [])
    if isinstance(stored_results, list):
        state["last_request_results"] = stored_results[-200:]
    elif isinstance(stored_results, dict):
        state["last_request_results"] = [stored_results]

    stored_queue = load(QUEUE_FILE, [])
    if isinstance(stored_queue, list):
        queue.extend(
            item for item in stored_queue
            if isinstance(item, dict) and item.get("video_id")
        )

    if liquidsoap_controller is None:
        raise RuntimeError("AUTODJ_USE_LIQUIDSOAP=1 es obligatorio para AutoDJ.")

    # Recover persisted !play requests after a container restart.
    for queued_item in list(queue):
        prefetch_item(queued_item)
    liquidsoap_controller.start()
    print(f"[AUTODJ] API escuchando en {HOST}:{PORT}", flush=True)
    ThreadingHTTPServer((HOST, PORT), API).serve_forever()
