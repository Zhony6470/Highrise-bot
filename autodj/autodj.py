import json
import os
import random
import subprocess
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

HOST = os.getenv("AUTODJ_HOST", "0.0.0.0")
PORT = int(os.getenv("AUTODJ_PORT", "8090"))
TOKEN = os.getenv("AUTODJ_TOKEN", "")
if not TOKEN:
    raise RuntimeError("AUTODJ_TOKEN es obligatorio.")

ICECAST_HOST = os.getenv("ICECAST_HOST", "icecast")
ICECAST_PORT = int(os.getenv("ICECAST_PORT", "8000"))
ICECAST_SOURCE = os.getenv("ICECAST_SOURCE", "source")
ICECAST_PASSWORD = os.getenv("ICECAST_PASSWORD", "")
ICECAST_MOUNT = os.getenv("ICECAST_MOUNT", "stream").strip("/")

CACHE = Path(os.getenv("AUTODJ_CACHE_DIR", "/data/cache"))
DEFAULT = Path(os.getenv("AUTODJ_DEFAULT_DIR", "/data/default_music"))
QUEUE_FILE = Path(os.getenv("AUTODJ_QUEUE_FILE", "/data/request_queue.json"))
RESULT_FILE = Path(os.getenv("AUTODJ_RESULT_FILE", "/data/last_request_result.json"))
PLAYLIST = Path(os.getenv("AUTODJ_PLAYLIST_FILE", "/data/default_playlist.json"))
COOKIES = os.getenv("YOUTUBE_COOKIES_PATH", "/app/cookies.txt")

SAMPLE_RATE = 44100
CHANNELS = 2
MAX_PLAY_SECONDS = 360
queue = deque()
lock = threading.RLock()
skip_event = threading.Event()
state = {"current": None, "started_at": None, "status": "idle", "last_default_id": None, "last_request_results": []}
active_request = None


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
        if active_request is not None and items and items[0] is active_request:
            return items[1:]
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

    command = [
        "yt-dlp",
        "--no-playlist",
        "--no-part",
        "-f", "bestaudio/best",
        "--extractor-args", "youtube:player_client=ios,android,web_embedded",
        "-o", str(CACHE / "%(id)s.%(ext)s"),
    ]
    if Path(COOKIES).exists():
        command += ["--cookies", COOKIES]

    subprocess.run(
        command + [f"https://www.youtube.com/watch?v={video_id}"],
        check=True,
        timeout=180,
    )

    matches = list(CACHE.glob(video_id + ".*"))
    if not matches:
        raise RuntimeError("yt-dlp no generó el archivo de audio.")
    return matches[0]


def icecast_url():
    return (
        f"icecast://{quote(ICECAST_SOURCE, safe='')}:"
        f"{quote(ICECAST_PASSWORD, safe='')}@"
        f"{ICECAST_HOST}:{ICECAST_PORT}/"
        f"{quote(ICECAST_MOUNT, safe='/')}"
    )


class PersistentIcecastEncoder:
    """Encoder FFmpeg persistente: mantiene una sola conexión con Icecast."""

    def __init__(self):
        self.process = None
        self.lock = threading.RLock()

    def start(self):
        with self.lock:
            if self.process is not None and self.process.poll() is None:
                return

            command = [
                "ffmpeg", "-hide_banner", "-loglevel", "warning",
                "-nostdin",
                "-f", "s16le",
                "-ar", str(SAMPLE_RATE),
                "-ac", str(CHANNELS),
                "-i", "pipe:0",
                "-vn",
                "-c:a", "libmp3lame",
                "-b:a", "128k",
                "-ar", str(SAMPLE_RATE),
                "-ac", str(CHANNELS),
                "-content_type", "audio/mpeg",
                "-flush_packets", "1",
                "-f", "mp3",
                icecast_url(),
            ]
            self.process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print("[AUTODJ] Encoder FFmpeg persistente conectado a Icecast.", flush=True)

    def alive(self):
        with self.lock:
            return self.process is not None and self.process.poll() is None

    def write(self, data: bytes):
        if not data:
            return
        with self.lock:
            process = self.process
            if process is None or process.poll() is not None or process.stdin is None:
                raise RuntimeError("El encoder FFmpeg de Icecast no está disponible.")
            try:
                process.stdin.write(data)
                process.stdin.flush()
            except (BrokenPipeError, OSError) as error:
                raise RuntimeError(f"Se perdió la conexión del encoder con Icecast: {error}") from error

    def stop(self):
        with self.lock:
            process = self.process
            self.process = None
            if process is None:
                return
            try:
                if process.stdin:
                    process.stdin.close()
            except Exception:
                pass
            try:
                process.wait(timeout=3)
            except Exception:
                try:
                    process.kill()
                    process.wait(timeout=1)
                except Exception:
                    pass


icecast_encoder = PersistentIcecastEncoder()


def start_decoder(path: Path):
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "warning",
        "-re",
        "-i", str(path),
        "-t", str(MAX_PLAY_SECONDS),
        "-vn",
        "-f", "s16le",
        "-ar", str(SAMPLE_RATE),
        "-ac", str(CHANNELS),
        "pipe:1",
    ]
    return subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )


def stop_decoder(process):
    if process is None:
        return
    try:
        if process.stdout:
            process.stdout.close()
    except Exception:
        pass
    try:
        process.terminate()
        process.wait(timeout=2)
    except Exception:
        try:
            process.kill()
            process.wait(timeout=1)
        except Exception:
            pass


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


def next_item():
    with lock:
        if queue:
            return queue[0]

    return choose_default()


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


def acknowledge_request(item):
    with lock:
        if queue and queue[0] is item:
            queue.popleft()
            save(QUEUE_FILE, list(queue))


def has_requests() -> bool:
    with lock:
        return len(queue) > (1 if active_request is not None else 0)


def player_loop():
    global active_request

    try:
        icecast_encoder.start()
    except Exception as error:
        print(f"[AUTODJ] No se pudo iniciar el encoder de Icecast: {error}", flush=True)

    while True:
        item = None
        decoder = None
        request_ref = None
        request_item = False
        playback_started_at = None

        try:
            if not icecast_encoder.alive():
                icecast_encoder.start()

            item = next_item()
            if not item:
                with lock:
                    state["status"] = "idle"
                time.sleep(1)
                continue

            item = dict(item)
            request_item = not item.get("default_track")

            if request_item:
                with lock:
                    request_ref = queue[0] if queue else None
                    active_request = request_ref

            item["file_path"] = str(ensure_file(item))

            if item.get("default_track") and queue_snapshot():
                print("[AUTODJ] Solicitud pendiente; descartando DEFAULT antes de reproducir.", flush=True)
                with lock:
                    active_request = None
                continue

            item["metadata"] = metadata(item)

            with lock:
                state["current"] = item
                state["started_at"] = time.time()
                state["status"] = "playing"
                if item.get("default_track"):
                    state["last_default_id"] = item.get("video_id") or item.get("file_path")

            print(
                f"[AUTODJ] {'DEFAULT' if not request_item else 'REQUEST'}: "
                f"{item['metadata'].get('title', 'Pista')}",
                flush=True,
            )

            decoder = start_decoder(Path(item["file_path"]))
            playback_started_at = time.monotonic()

            while True:
                if skip_event.is_set():
                    break

                if item.get("default_track") and has_requests():
                    print("[AUTODJ] Solicitud prioritaria detectada.", flush=True)
                    break

                if not icecast_encoder.alive():
                    raise RuntimeError("El encoder persistente de Icecast se detuvo.")

                if decoder.poll() is not None:
                    break

                chunk = decoder.stdout.read(16384) if decoder.stdout else b""
                if chunk:
                    icecast_encoder.write(chunk)
                elif decoder.poll() is not None:
                    break
                else:
                    time.sleep(0.01)

            was_skipped = skip_event.is_set()
            elapsed_playback = (
                time.monotonic() - playback_started_at
                if playback_started_at is not None
                else 0
            )
            return_code = decoder.poll() if decoder is not None else None

            stop_decoder(decoder)
            decoder = None
            skip_event.clear()

            if request_item and request_ref and item.get("request_id"):
                if was_skipped or return_code == 0 or elapsed_playback >= 2:
                    set_request_result(item, "played")
                else:
                    set_request_result(item, "failed", "FFmpeg terminó antes de reproducir la solicitud.")

            with lock:
                state["current"] = None
                state["started_at"] = None
                state["status"] = "idle"
                if request_item:
                    active_request = None

            if request_item:
                acknowledge_request(request_ref)

        except Exception as error:
            print(f"[AUTODJ] error: {error}", flush=True)
            if decoder is not None:
                stop_decoder(decoder)

            if request_item and request_ref and item and item.get("request_id"):
                set_request_result(item, "failed", str(error))
                acknowledge_request(request_ref)

            skip_event.clear()

            with lock:
                state["current"] = None
                state["started_at"] = None
                state["status"] = "recovering"
                active_request = None

            time.sleep(1)


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
                return self.reply(200, {"ok": True, "queued": item})

            if self.path == "/skip":
                with lock:
                    active = state.get("current") is not None

                if not active:
                    return self.reply(200, {"ok": True, "active": False})

                skip_event.set()
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

    threading.Thread(target=player_loop, daemon=True).start()
    print(f"[AUTODJ] API escuchando en {HOST}:{PORT}", flush=True)
    try:
        ThreadingHTTPServer((HOST, PORT), API).serve_forever()
    finally:
        icecast_encoder.stop()
