import json
import os
import random
import re
import shutil
import subprocess
import threading
import time
from array import array
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

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

SAMPLE_RATE = 44100
CHANNELS = 2
SAMPLE_WIDTH = 2
CROSSFADE_SECONDS = max(float(os.getenv("RADIO_CROSSFADE_SECONDS", "3")), 0)
CROSSFADE_BYTES = int(SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH * CROSSFADE_SECONDS)
STREAM_PATH = "/stream"
STREAM_QUEUE_SIZE = 16
MAX_PLAY_SECONDS = 360

queue = deque()
lock = threading.RLock()
skip_event = threading.Event()
state = {
    "current": None,
    "started_at": None,
    "status": "idle",
    "last_default_id": None,
    "last_request_results": [],
}
active_request = None


class LocalAudioPublisher:
    """Mantiene /stream vivo para Liquidsoap mientras cambian las pistas."""

    def __init__(self):
        self.clients = set()
        self.clients_lock = threading.Lock()

    def subscribe(self):
        client = __import__("queue").Queue(maxsize=STREAM_QUEUE_SIZE)
        with self.clients_lock:
            self.clients.add(client)
        return client

    def unsubscribe(self, client):
        with self.clients_lock:
            self.clients.discard(client)

    def publish(self, chunk: bytes):
        with self.clients_lock:
            clients = tuple(self.clients)

        for client in clients:
            try:
                client.put_nowait(chunk)
            except Exception:
                try:
                    client.get_nowait()
                    client.put_nowait(chunk)
                except Exception:
                    pass


audio_publisher = LocalAudioPublisher()


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        return default


def save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(path)


def metadata(item: dict) -> dict:
    return item.get("metadata") or {
        "title": item.get("title", "Pista desconocida"),
        "channel": item.get("channel", "Highrise Radio"),
        "duration": item.get("duration"),
    }


def authorized(handler) -> bool:
    return handler.headers.get("Authorization", "") == f"Bearer {TOKEN}"


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


def decode_file(path: Path) -> subprocess.Popen:
    return subprocess.Popen(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "warning",
            "-i", str(path),
            "-t", str(MAX_PLAY_SECONDS),
            "-vn",
            "-f", "s16le",
            "-ar", str(SAMPLE_RATE),
            "-ac", str(CHANNELS),
            "pipe:1",
        ],
        stdout=subprocess.PIPE,
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
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=2)
    except Exception:
        try:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=1)
        except Exception:
            pass


def create_output_process() -> subprocess.Popen:
    print("[AUTODJ] Iniciando encoder persistente para Liquidsoap.", flush=True)

    output = subprocess.Popen(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "warning",
            "-re",
            "-f", "s16le",
            "-ar", str(SAMPLE_RATE),
            "-ac", str(CHANNELS),
            "-i", "pipe:0",
            "-c:a", "libmp3lame",
            "-b:a", "128k",
            "-f", "mp3",
            "pipe:1",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )

    threading.Thread(
        target=publish_output,
        args=(output,),
        daemon=True,
    ).start()

    return output


def publish_output(output: subprocess.Popen) -> None:
    while output.stdout:
        chunk = output.stdout.read(64 * 1024)
        if not chunk:
            break
        audio_publisher.publish(chunk)


def ensure_output_process(output):
    if output is not None and output.poll() is None:
        return output

    if output is not None:
        try:
            output.terminate()
            output.wait(timeout=2)
        except Exception:
            pass

    return create_output_process()


def mix_pcm(left: bytes, right: bytes) -> bytes:
    usable_left = left[:len(left) - (len(left) % SAMPLE_WIDTH)]
    usable_right = right[:len(right) - (len(right) % SAMPLE_WIDTH)]

    left_samples = array("h")
    right_samples = array("h")
    left_samples.frombytes(usable_left)
    right_samples.frombytes(usable_right)

    count = min(len(left_samples), len(right_samples))
    mixed = array("h")

    for index in range(count):
        fade_in = index / max(count - 1, 1)
        value = int(
            left_samples[index] * (1 - fade_in)
            + right_samples[index] * fade_in
        )
        mixed.append(max(-32768, min(32767, value)))

    return mixed.tobytes()


def choose_default():
    playlist = load(PLAYLIST, [])

    if playlist:
        candidates = [
            item for item in playlist
            if isinstance(item, dict)
            and (item.get("video_id") or item.get("file_path"))
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

    if not DEFAULT.exists():
        return None

    files = [
        path for path in DEFAULT.iterdir()
        if path.is_file()
        and path.suffix.lower() in {
            ".mp3", ".wav", ".m4a", ".aac",
            ".ogg", ".flac", ".webm", ".opus",
        }
    ]

    if not files:
        return None

    with lock:
        last_id = state.get("last_default_id")

    candidates = [
        path for path in files
        if str(path) != str(last_id)
    ] or files

    path = random.choice(candidates)

    return {
        "file_path": str(path),
        "title": path.stem,
        "default_track": True,
        "metadata": {
            "title": path.stem,
            "channel": "Highrise Radio",
        },
    }


def next_item():
    with lock:
        if queue:
            return queue[0]

    return choose_default()


def has_requests() -> bool:
    with lock:
        return bool(queue)


def set_request_result(item: dict, status: str, error=None):
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


def stream_decoder(decoder, output, tail: bytearray):
    while True:
        if skip_event.is_set():
            return tail, "skip"

        if has_requests() and tail and state.get("current", {}).get("default_track"):
            return tail, "priority"

        chunk = decoder.stdout.read(64 * 1024)

        if not chunk:
            return tail, "eof"

        if CROSSFADE_BYTES == 0:
            output.stdin.write(chunk)
            continue

        tail.extend(chunk)

        if len(tail) > CROSSFADE_BYTES:
            output.stdin.write(tail[:-CROSSFADE_BYTES])
            del tail[:-CROSSFADE_BYTES]


def prepare_next_item():
    with lock:
        if queue:
            return dict(queue[0])

    return choose_default()


def play_loop():
    global active_request
    output = None
    current_decoder = None
    current_item = None
    current_request_ref = None
    current_started = None
    tail = bytearray()

    while True:
        try:
            if current_decoder is None:
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
                        current_request_ref = queue[0] if queue else None
                        active_request = current_request_ref
                else:
                    current_request_ref = None
                    with lock:
                        active_request = None

                item["file_path"] = str(ensure_file(item))
                item["metadata"] = metadata(item)
                with lock:
                    state["current"] = item
                    state["started_at"] = time.time()
                    state["status"] = "playing"
                    if item.get("default_track"):
                        state["last_default_id"] = item.get("video_id") or item.get("file_path")

                print(f"[AUTODJ] {'REQUEST' if request_item else 'DEFAULT'}: {item['metadata'].get('title', 'Pista')}", flush=True)
                output = ensure_output_process(output)
                current_decoder = decode_file(Path(item["file_path"]))
                initial = current_decoder.stdout.read(64 * 1024)
                if not initial:
                    raise RuntimeError("El decodificador no entregó audio.")

                current_item = item
                current_started = time.monotonic()
                tail = bytearray()

                if CROSSFADE_BYTES:
                    tail.extend(initial)
                    if len(tail) > CROSSFADE_BYTES:
                        output.stdin.write(tail[:-CROSSFADE_BYTES])
                        del tail[:-CROSSFADE_BYTES]
                else:
                    output.stdin.write(initial)

            reason = stream_decoder(current_decoder, output, tail)

            if reason == "skip":
                skip_event.clear()
                stop_decoder(current_decoder)
                current_decoder = None
                if current_request_ref and current_item and current_item.get("request_id"):
                    set_request_result(current_item, "played")
                    acknowledge_request(current_request_ref)
                current_item = None
                current_request_ref = None
                current_started = None
                tail = bytearray()
                with lock:
                    active_request = None
                    state["current"] = None
                    state["started_at"] = None
                    state["status"] = "idle"
                continue

            next_item_value = prepare_next_item()
            if not next_item_value:
                if tail:
                    output.stdin.write(tail)
                    output.stdin.flush()
                stop_decoder(current_decoder)
                current_decoder = None
                if current_request_ref and current_item and current_item.get("request_id"):
                    set_request_result(current_item, "played")
                    acknowledge_request(current_request_ref)
                current_item = None
                current_request_ref = None
                current_started = None
                tail = bytearray()
                with lock:
                    active_request = None
                    state["current"] = None
                    state["started_at"] = None
                    state["status"] = "idle"
                continue

            next_item_value = dict(next_item_value)
            next_request = not next_item_value.get("default_track")
            next_request_ref = None
            if next_request:
                with lock:
                    next_request_ref = queue[0] if queue else None

            next_item_value["file_path"] = str(ensure_file(next_item_value))
            next_item_value["metadata"] = metadata(next_item_value)
            next_decoder = decode_file(Path(next_item_value["file_path"]))
            prefix = next_decoder.stdout.read(CROSSFADE_BYTES if CROSSFADE_BYTES else 64 * 1024)
            if not prefix:
                stop_decoder(next_decoder)
                raise RuntimeError("La siguiente pista no entregó audio.")

            output = ensure_output_process(output)
            if CROSSFADE_BYTES and tail:
                output.stdin.write(mix_pcm(bytes(tail), prefix))
                if len(prefix) > len(tail):
                    output.stdin.write(prefix[len(tail):])
            else:
                output.stdin.write(prefix)
            output.stdin.flush()

            stop_decoder(current_decoder)
            current_decoder = next_decoder

            if current_request_ref and current_item and current_item.get("request_id"):
                elapsed = time.monotonic() - current_started if current_started else 0
                if elapsed >= 2:
                    set_request_result(current_item, "played")
                acknowledge_request(current_request_ref)

            current_item = next_item_value
            current_request_ref = next_request_ref if next_request else None
            current_started = time.monotonic()
            tail = bytearray()

            with lock:
                active_request = current_request_ref if next_request else None
                state["current"] = current_item
                state["started_at"] = time.time()
                state["status"] = "playing"
                if current_item.get("default_track"):
                    state["last_default_id"] = current_item.get("video_id") or current_item.get("file_path")

            print(f"[AUTODJ] {'REQUEST' if next_request else 'DEFAULT'}: {current_item['metadata'].get('title', 'Pista')}", flush=True)

        except Exception as error:
            print(f"[AUTODJ] error: {error}", flush=True)
            stop_decoder(current_decoder)
            current_decoder = None
            if current_request_ref and current_item and current_item.get("request_id"):
                set_request_result(current_item, "failed", str(error))
                acknowledge_request(current_request_ref)
            skip_event.clear()
            current_item = None
            current_request_ref = None
            current_started = None
            tail = bytearray()
            with lock:
                active_request = None
                state["current"] = None
                state["started_at"] = None
                state["status"] = "recovering"
            time.sleep(1)


class API(BaseHTTPRequestHandler):
    def reply(self, code: int, value) -> None:
        body = json.dumps(
            value,
            ensure_ascii=False,
        ).encode("utf-8")

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
            return self.reply(
                200,
                {"ok": True, "service": "autodj"},
            )

        if self.path == "/status":
            with lock:
                snapshot = dict(state)
                snapshot["current"] = (
                    dict(state["current"])
                    if state.get("current")
                    else None
                )
                started = state.get("started_at")
                snapshot["elapsed"] = (
                    time.time() - started
                    if started
                    else 0
                )
                snapshot["queue"] = queue_snapshot()

            return self.reply(200, snapshot)

        if self.path == "/queue":
            return self.reply(200, queue_snapshot())

        if self.path == "/default-playlist":
            return self.reply(
                200,
                load(PLAYLIST, []),
            )

        if self.path == STREAM_PATH:
            client = audio_publisher.subscribe()

            try:
                self.send_response(200)
                self.send_header("Content-Type", "audio/mpeg")
                self.send_header(
                    "Cache-Control",
                    "no-cache, no-store",
                )
                self.send_header("Connection", "close")
                self.end_headers()

                while True:
                    chunk = client.get()
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (
                BrokenPipeError,
                ConnectionResetError,
                OSError,
            ):
                pass
            finally:
                audio_publisher.unsubscribe(client)

            return

        return self.reply(404, {"error": "not_found"})

    def do_POST(self):
        if not authorized(self):
            return self.reply(401, {"error": "unauthorized"})

        try:
            data = self.body()

            if self.path == "/play":
                video_id = str(
                    data.get("video_id", "")
                ).strip()

                if not re.fullmatch(
                    r"[A-Za-z0-9_-]{11}",
                    video_id,
                ):
                    return self.reply(
                        400,
                        {"error": "invalid_video_id"},
                    )

                item = {
                    "video_id": video_id,
                    "metadata": data.get("metadata", {}),
                    "request_id": data.get("request_id"),
                    "requested_track": True,
                }

                with lock:
                    queue.append(item)
                    save(QUEUE_FILE, list(queue))

                return self.reply(
                    200,
                    {"ok": True, "queued": item},
                )

            if self.path == "/skip":
                with lock:
                    active = state.get("current") is not None

                if not active:
                    return self.reply(
                        200,
                        {"ok": True, "active": False},
                    )

                skip_event.set()

                return self.reply(
                    200,
                    {"ok": True, "active": True},
                )

            if self.path in (
                "/default-add",
                "/default-remove",
            ):
                playlist = load(PLAYLIST, [])

                if not isinstance(playlist, list):
                    playlist = []

                video_id = str(
                    data.get("video_id", "")
                ).strip()

                if not video_id:
                    return self.reply(
                        400,
                        {"error": "video_id_required"},
                    )

                if self.path == "/default-add":
                    if any(
                        isinstance(item, dict)
                        and item.get("video_id") == video_id
                        for item in playlist
                    ):
                        return self.reply(
                            409,
                            {"error": "already_exists"},
                        )

                    playlist.append(
                        {
                            "video_id": video_id,
                            "metadata": data.get(
                                "metadata",
                                {},
                            ),
                        }
                    )
                else:
                    old_length = len(playlist)

                    playlist = [
                        item
                        for item in playlist
                        if not (
                            isinstance(item, dict)
                            and item.get("video_id") == video_id
                        )
                    ]

                    if len(playlist) == old_length:
                        return self.reply(
                            404,
                            {"error": "not_found"},
                        )

                save(PLAYLIST, playlist)

                return self.reply(
                    200,
                    {
                        "ok": True,
                        "playlist": playlist,
                    },
                )

            return self.reply(
                404,
                {"error": "not_found"},
            )

        except Exception as error:
            return self.reply(
                400,
                {"error": str(error)},
            )

    def log_message(self, *_):
        return


if __name__ == "__main__":
    CACHE.mkdir(parents=True, exist_ok=True)
    DEFAULT.mkdir(parents=True, exist_ok=True)

    stored_results = load(
        RESULT_FILE,
        [],
    )

    if isinstance(stored_results, list):
        state["last_request_results"] = stored_results[-200:]
    elif isinstance(stored_results, dict):
        state["last_request_results"] = [stored_results]

    stored_queue = load(
        QUEUE_FILE,
        [],
    )

    if isinstance(stored_queue, list):
        queue.extend(
            item
            for item in stored_queue
            if isinstance(item, dict)
            and item.get("video_id")
        )

    threading.Thread(
        target=play_loop,
        daemon=True,
    ).start()

    print(
        f"[AUTODJ] API escuchando en {HOST}:{PORT}",
        flush=True,
    )

    ThreadingHTTPServer(
        (HOST, PORT),
        API,
    ).serve_forever()
