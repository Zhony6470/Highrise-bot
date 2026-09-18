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
BLOCK = 16384

queue = deque()
lock = threading.RLock()
priority_event = threading.Event()
skip_event = threading.Event()
state = {"current": None, "started_at": None, "status": "idle"}


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
        return list(queue)


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


def decoder(path: Path):
    return subprocess.Popen(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-i", str(path),
            "-f", "s16le",
            "-ar", str(SAMPLE_RATE),
            "-ac", str(CHANNELS),
            "pipe:1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )


class IcecastOutput:
    """Una sola salida FFmpeg persistente durante toda la vida del AutoDJ."""

    def __init__(self):
        self.process = None
        self.lock = threading.RLock()

    def _start(self):
        url = (
            f"icecast://{quote(ICECAST_SOURCE, safe='')}:"
            f"{quote(ICECAST_PASSWORD, safe='')}@"
            f"{ICECAST_HOST}:{ICECAST_PORT}/"
            f"{quote(ICECAST_MOUNT, safe='/')}"
        )
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "warning",
            "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", str(CHANNELS),
            "-i", "pipe:0",
            "-c:a", "libmp3lame", "-b:a", "128k",
            "-ar", str(SAMPLE_RATE), "-ac", str(CHANNELS),
            "-content_type", "audio/mpeg",
            "-f", "mp3", url,
        ]
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE)
        print("[AUTODJ] salida Icecast conectada", flush=True)

    def connect(self):
        with self.lock:
            if self.process and self.process.poll() is None:
                return
            self._start()

    def write(self, pcm: bytes):
        while True:
            try:
                self.connect()
                self.process.stdin.write(pcm)
                self.process.stdin.flush()
                return
            except (BrokenPipeError, OSError):
                print("[AUTODJ] Icecast desconectado; reconectando sin repetir el bloque.", flush=True)
                self.close()
                time.sleep(1)

    def close(self):
        with self.lock:
            process = self.process
            self.process = None
            if not process:
                return
            try:
                process.stdin.close()
            except Exception:
                pass
            try:
                process.terminate()
                process.wait(timeout=2)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass


def choose_default() -> dict | None:
    playlist = load(PLAYLIST, [])
    items = [
        dict(item)
        for item in playlist
        if isinstance(item, dict) and item.get("video_id")
    ]

    if not items:
        items = [
            {
                "file_path": str(path),
                "metadata": {
                    "title": path.stem,
                    "channel": "Highrise Radio",
                },
            }
            for path in DEFAULT.iterdir()
            if path.is_file()
        ]

    if not items:
        return None

    # Evita repetir inmediatamente la misma pista cuando hay alternativas.
    with lock:
        previous = state.get("last_default_id")

    candidates = [item for item in items if item.get("video_id") != previous]
    if not candidates:
        candidates = [item for item in items if item.get("file_path") != previous] or items

    return random.choice(candidates)


def next_item() -> dict | None:
    with lock:
        if queue:
            item = queue.popleft()
            save(QUEUE_FILE, list(queue))
            return item

    item = choose_default()
    if item:
        item["default_track"] = True
    return item


def stop_decoder(process):
    try:
        if process.stdout:
            process.stdout.close()
    except Exception:
        pass
    try:
        process.wait(timeout=2)
    except Exception:
        try:
            process.kill()
            process.wait(timeout=1)
        except Exception:
            pass


def player_loop():
    output = IcecastOutput()

    while True:
        item = None
        process = None
        try:
            item = next_item()
            if not item:
                with lock:
                    state["status"] = "idle"
                time.sleep(1)
                continue

            item = dict(item)
            item["file_path"] = str(ensure_file(item))
            item["metadata"] = metadata(item)

            with lock:
                state["current"] = item
                state["started_at"] = time.time()
                state["status"] = "playing"
                if item.get("default_track"):
                    state["last_default_id"] = item.get("video_id") or item.get("file_path")

            print(
                f"[AUTODJ] {'DEFAULT' if item.get('default_track') else 'REQUEST'}: "
                f"{item['metadata'].get('title', 'Pista')}",
                flush=True,
            )

            process = decoder(Path(item["file_path"]))

            while True:
                if skip_event.is_set():
                    break

                # Las solicitudes interrumpen únicamente una pista DEFAULT.
                # Una solicitud en curso nunca es interrumpida por otra solicitud.
                if item.get("default_track") and priority_event.is_set():
                    print("[AUTODJ] Solicitud prioritaria detectada.", flush=True)
                    break

                pcm = process.stdout.read(BLOCK)
                if not pcm:
                    break
                output.write(pcm)

            stop_decoder(process)
            process = None

            # Consumimos el evento que provocó la transición. La cola ya contiene
            # la solicitud y será lo siguiente que reproduzca next_item().
            priority_event.clear()
            skip_event.clear()

            with lock:
                state["current"] = None
                state["started_at"] = None
                state["status"] = "idle"

        except Exception as error:
            print(f"[AUTODJ] error: {error}", flush=True)
            if process is not None:
                stop_decoder(process)
            priority_event.clear()
            skip_event.clear()
            with lock:
                state["current"] = None
                state["started_at"] = None
                state["status"] = "recovering"
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
                current = dict(state["current"]) if state.get("current") else None
                if current:
                    snapshot["current"] = current
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
                video_id = data["video_id"]
                item = {
                    "video_id": video_id,
                    "metadata": data.get("metadata", {}),
                    "requested_track": True,
                }
                with lock:
                    queue.append(item)
                    save(QUEUE_FILE, list(queue))
                    if state.get("current", {}).get("default_track"):
                        priority_event.set()
                return self.reply(200, {"ok": True, "queued": item})

            if self.path == "/skip":
                skip_event.set()
                return self.reply(200, {"ok": True})

            if self.path in ("/default-add", "/default-remove"):
                playlist = load(PLAYLIST, [])
                video_id = data["video_id"]

                if self.path == "/default-add":
                    if any(item.get("video_id") == video_id for item in playlist):
                        return self.reply(409, {"error": "already_exists"})
                    playlist.append({
                        "video_id": video_id,
                        "metadata": data.get("metadata", {}),
                    })
                else:
                    old_length = len(playlist)
                    playlist = [
                        item for item in playlist
                        if item.get("video_id") != video_id
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
    queue.extend(load(QUEUE_FILE, []))

    threading.Thread(target=player_loop, daemon=True).start()
    print(f"[AUTODJ] API escuchando en {HOST}:{PORT}", flush=True)
    ThreadingHTTPServer((HOST, PORT), API).serve_forever()
