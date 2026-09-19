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

ICECAST_HOST = os.getenv("ICECAST_HOST", "icecast")
ICECAST_PORT = int(os.getenv("ICECAST_PORT", "8000"))
ICECAST_SOURCE = os.getenv("ICECAST_SOURCE", "source")
ICECAST_PASSWORD = os.getenv("ICECAST_PASSWORD", "")
ICECAST_MOUNT = os.getenv("ICECAST_MOUNT", "stream").strip("/")

CACHE = Path(os.getenv("AUTODJ_CACHE_DIR", "/data/cache"))
DEFAULT = Path(os.getenv("AUTODJ_DEFAULT_DIR", "/data/default_music"))
QUEUE_FILE = Path(os.getenv("AUTODJ_QUEUE_FILE", "/data/request_queue.json"))
PLAYLIST = Path(os.getenv("AUTODJ_PLAYLIST_FILE", "/data/default_playlist.json"))
COOKIES = os.getenv("YOUTUBE_COOKIES_PATH", "/app/cookies.txt")

SAMPLE_RATE = 44100
CHANNELS = 2
queue = deque()
lock = threading.RLock()
skip_event = threading.Event()
state = {"current": None, "started_at": None, "status": "idle", "last_default_id": None}
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


def play_file(path: Path):
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "warning",
        "-re",
        "-i", str(path),
        "-vn",
        "-c:a", "libmp3lame",
        "-b:a", "128k",
        "-ar", str(SAMPLE_RATE),
        "-ac", str(CHANNELS),
        "-content_type", "audio/mpeg",
        "-f", "mp3",
        icecast_url(),
    ]

    return subprocess.Popen(command)


def stop_decoder(process):
    if process is None:
        return

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
    while True:
        item = None
        process = None
        request_ref = None
        try:
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
                print(
                    "[AUTODJ] Solicitud pendiente; descartando DEFAULT antes de reproducir.",
                    flush=True,
                )
                continue

            item["metadata"] = metadata(item)

            with lock:
                state["current"] = item
                state["started_at"] = time.time()
                state["status"] = "playing"
                if item.get("default_track"):
                    state["last_default_id"] = (
                        item.get("video_id") or item.get("file_path")
                    )

            print(
                f"[AUTODJ] {'DEFAULT' if item.get('default_track') else 'REQUEST'}: "
                f"{item['metadata'].get('title', 'Pista')}",
                flush=True,
            )

            process = play_file(Path(item["file_path"]))

            while True:
                if skip_event.is_set():
                    break

                if item.get("default_track") and has_requests():
                    print(
                        "[AUTODJ] Solicitud prioritaria detectada.",
                        flush=True,
                    )
                    break

                if process.poll() is not None:
                    break

                time.sleep(0.25)

            stop_decoder(process)
            process = None

            skip_event.clear()

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

            if process is not None:
                stop_decoder(process)

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
                snapshot["queue"] = list(queue)
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

    stored_queue = load(QUEUE_FILE, [])
    if isinstance(stored_queue, list):
        queue.extend(
            item for item in stored_queue
            if isinstance(item, dict) and item.get("video_id")
        )

    threading.Thread(target=player_loop, daemon=True).start()
    print(f"[AUTODJ] API escuchando en {HOST}:{PORT}", flush=True)
    ThreadingHTTPServer((HOST, PORT), API).serve_forever()
