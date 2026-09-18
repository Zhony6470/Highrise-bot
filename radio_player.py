import hmac
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import tempfile
import time
from array import array
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Lock, Thread
from urllib.parse import quote, urlparse
from pathlib import Path

HOST = os.environ.get("RADIO_HOST", "0.0.0.0")
PORT = int(os.environ.get("RADIO_PORT", "8090"))
TOKEN = os.environ.get("RADIO_PLAYER_TOKEN", "")
ICECAST_HOST = os.environ.get("ICECAST_HOST", "")
ICECAST_PORT = os.environ.get("ICECAST_PORT", "")
ICECAST_PASSWORD = os.environ.get("ICECAST_PASSWORD", "")
ICECAST_SOURCE = os.environ.get("ICECAST_SOURCE", "source")
ICECAST_MOUNT = os.environ.get("ICECAST_MOUNT") or "stream"


def get_output_url() -> str:
    if ICECAST_HOST and ICECAST_PORT and ICECAST_PASSWORD:
        mount = ICECAST_MOUNT.strip("/")
        mount_path = f"/{quote(mount, safe='/')}" if mount else "/"
        username = quote(ICECAST_SOURCE, safe="")
        password = quote(ICECAST_PASSWORD, safe="")
        return f"icecast://{username}:{password}@{ICECAST_HOST}:{ICECAST_PORT}{mount_path}"
    return os.environ.get(
        "ICECAST_URL", "icecast://source:CHANGE_ME@127.0.0.1:8000/radio.mp3"
    )


OUTPUT_URL = get_output_url()
output_parts = urlparse(OUTPUT_URL)
if not output_parts.hostname or not output_parts.password:
    print(
        "Advertencia: la configuración de Icecast está incompleta; la API de radio se lanzará con la URL por defecto.",
        flush=True,
    )

# Ruta opcional a las cookies exportadas para mitigar bloqueos en VPS
COOKIES_PATH = os.environ.get(
    "YOUTUBE_COOKIES_PATH",
    os.path.join(os.path.dirname(__file__), "cookies.txt"),
)
USE_YOUTUBE_COOKIES = os.environ.get("YOUTUBE_USE_COOKIES", "0") == "1"
RUNTIME_COOKIES_PATH = os.path.join("/tmp", "yt-dlp-cookies.txt")

playback_queue = deque()
queue_lock = Lock()
state_lock = Lock()
current_item = None
current_started_at = None
active_decoder = None
skip_requested = False
priority_requested = False
priority_event = Event()
prefetched_item = None
pending_default = None
MAX_QUEUE_SIZE = 10
SAMPLE_RATE = 44100
CHANNELS = 2
SAMPLE_WIDTH = 2
RADIO_CROSSFADE_SECONDS = max(float(os.environ.get("RADIO_CROSSFADE_SECONDS", "0")), 0)
CROSSFADE_SECONDS = RADIO_CROSSFADE_SECONDS
CROSSFADE_BYTES = int(SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH * CROSSFADE_SECONDS)
YTDLP_CACHE_DIR = os.environ.get("YTDLP_CACHE_DIR", "/app/.cache")
YTDLP_SLEEP_REQUESTS = os.environ.get("YTDLP_SLEEP_REQUESTS", "0.75")
YTDLP_SLEEP_INTERVAL = os.environ.get("YTDLP_SLEEP_INTERVAL", "10")
YTDLP_MAX_SLEEP_INTERVAL = os.environ.get("YTDLP_MAX_SLEEP_INTERVAL", "20")
DEFAULT_MUSIC_DIR = Path(os.environ.get("DEFAULT_MUSIC_DIR", "/app/default_music"))
DEFAULT_CACHE_DIR = Path(os.environ.get("DEFAULT_CACHE_DIR", "/app/default_cache"))
DEFAULT_PLAYLIST_FILE = DEFAULT_MUSIC_DIR / "playlist.json"
REQUEST_QUEUE_FILE = DEFAULT_MUSIC_DIR / "request_queue.json"
DEFAULT_AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac"}
default_tracks = sorted(
    path for path in DEFAULT_MUSIC_DIR.glob("**/*")
    if path.is_file() and path.suffix.lower() in DEFAULT_AUDIO_EXTENSIONS
)
default_track_index = 0
default_playlist_index = 0
last_default_key = None
default_cache_lock = Lock()


def load_request_queue() -> list[dict]:
    try:
        data = json.loads(REQUEST_QUEUE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (FileNotFoundError, OSError, ValueError):
        return []


def save_request_queue() -> None:
    DEFAULT_MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    pending = [item for item in list(playback_queue) if not item.get("default_track")]
    with state_lock:
        playing = current_item
    if playing and not playing.get("default_track"):
        pending.insert(0, playing)
    temporary = REQUEST_QUEUE_FILE.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(pending, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(REQUEST_QUEUE_FILE)


playback_queue.extend(load_request_queue())

print(f"Radio player escuchando en {HOST}:{PORT}", flush=True)
print(f"Destino Icecast configurado: {OUTPUT_URL.rsplit('@', 1)[-1]}", flush=True)


def decode_video(video_id: str) -> subprocess.Popen:
    """Invoca yt-dlp con argumentos de emulación de cliente y cookies anti-bloqueo."""
    source = f"https://www.youtube.com/watch?v={video_id}"
    
    ytdlp_cmd = [
        "yt-dlp",
        "--no-playlist",
        "--cache-dir", YTDLP_CACHE_DIR,
        "--no-progress",
        "--js-runtimes", "deno:/usr/local/bin/deno",
        "--sleep-requests", YTDLP_SLEEP_REQUESTS,
        "--sleep-interval", YTDLP_SLEEP_INTERVAL,
        "--max-sleep-interval", YTDLP_MAX_SLEEP_INTERVAL,
        "-f", "bestaudio/best",
        "--extractor-args", "youtube:player_client=android,ios,web_embedded;skip=hls,dash",
        "-o", "-",
        source
    ]
    
    # Las cookies exportadas pueden caducar; solo usarlas si se solicitan.
    if USE_YOUTUBE_COOKIES and os.path.exists(COOKIES_PATH):
        try:
            shutil.copyfile(COOKIES_PATH, RUNTIME_COOKIES_PATH)
        except OSError as error:
            print(f"No se pudieron preparar las cookies de YouTube: {error}")
        else:
            ytdlp_cmd.insert(1, "--cookies")
            ytdlp_cmd.insert(2, RUNTIME_COOKIES_PATH)

    ytdlp = subprocess.Popen(ytdlp_cmd, stdout=subprocess.PIPE)
    decoder = subprocess.Popen([
        "ffmpeg", "-hide_banner", "-loglevel", "warning", "-threads", "1", "-i", "pipe:0",
        "-vn", "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", str(CHANNELS), "pipe:1",
    ], stdin=ytdlp.stdout, stdout=subprocess.PIPE)
    ytdlp.stdout.close()
    decoder.ytdlp = ytdlp
    return decoder


def decode_stream(stream_url: str) -> subprocess.Popen:
    decoder = subprocess.Popen([
        "ffmpeg", "-hide_banner", "-loglevel", "warning", "-threads", "1", "-i", stream_url,
        "-vn", "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", str(CHANNELS), "pipe:1",
    ], stdout=subprocess.PIPE)
    return decoder


def decode_file(file_path: str) -> subprocess.Popen:
    return subprocess.Popen([
        "ffmpeg", "-hide_banner", "-loglevel", "warning", "-threads", "1",
        "-i", file_path, "-vn", "-f", "s16le", "-ar", str(SAMPLE_RATE),
        "-ac", str(CHANNELS), "pipe:1",
    ], stdout=subprocess.PIPE)


def cached_default_path(video_id: str) -> Path:
    digest = hashlib.sha256(video_id.encode("utf-8")).hexdigest()[:16]
    return DEFAULT_CACHE_DIR / digest


def ensure_default_cache(item: dict) -> str:
    video_id = item["video_id"]
    cache_base = cached_default_path(video_id)
    with default_cache_lock:
        cached_files = list(DEFAULT_CACHE_DIR.glob(f"{cache_base.name}.*"))
        if cached_files:
            return str(cached_files[0])

        DEFAULT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        temp_dir = Path(tempfile.mkdtemp(prefix="default-download-", dir="/tmp"))
        try:
            command = [
                "yt-dlp", "--no-playlist", "--no-progress", "--no-part",
                "--cache-dir", YTDLP_CACHE_DIR,
                "--js-runtimes", "deno:/usr/local/bin/deno",
                "--sleep-requests", YTDLP_SLEEP_REQUESTS,
                "--sleep-interval", YTDLP_SLEEP_INTERVAL,
                "--max-sleep-interval", YTDLP_MAX_SLEEP_INTERVAL,
                "-f", "bestaudio/best",
                "--extractor-args", "youtube:player_client=android,ios,web_embedded;skip=hls,dash",
                "-o", str(temp_dir / "%(id)s.%(ext)s"), video_id,
            ]
            if USE_YOUTUBE_COOKIES and os.path.exists(COOKIES_PATH):
                shutil.copyfile(COOKIES_PATH, RUNTIME_COOKIES_PATH)
                command[1:1] = ["--cookies", RUNTIME_COOKIES_PATH]
            subprocess.run(command, check=True)
            downloaded = next(temp_dir.glob(f"{video_id}.*"), None)
            if downloaded is None:
                raise OSError("yt-dlp no generó el archivo de audio")
            target = DEFAULT_CACHE_DIR / f"{cache_base.name}{downloaded.suffix}"
            shutil.move(str(downloaded), str(target))
            return str(target)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


def decode_item(item: dict) -> subprocess.Popen:
    if item.get("file_path"):
        return decode_file(item["file_path"])
    if item.get("default_track") and item.get("video_id"):
        item["file_path"] = ensure_default_cache(item)
        return decode_file(item["file_path"])
    if item.get("stream_url"):
        return decode_stream(item["stream_url"])
    return decode_video(item["video_id"])


def next_default_item() -> dict | None:
    global default_track_index, default_playlist_index, last_default_key
    try:
        playlist = json.loads(DEFAULT_PLAYLIST_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        playlist = []
    if playlist:
        candidates = [dict(item) for item in playlist if item.get("video_id")]
        if len(candidates) > 1:
            candidates = [item for item in candidates if item.get("video_id") != last_default_key] or candidates
            random.shuffle(candidates)
        else:
            candidates = candidates or [dict(item) for item in playlist]
        item = dict(candidates[0])
        default_playlist_index += 1
        item["default_track"] = True
        last_default_key = item.get("video_id")
        return item
    if default_tracks:
        candidates = [path for path in default_tracks if str(path) != last_default_key] or list(default_tracks)
        random.shuffle(candidates)
        path = candidates[0]
        default_track_index += 1
        last_default_key = str(path)
        return {
            "file_path": str(path),
            "default_track": True,
            "metadata": {"title": path.stem, "channel": "Highrise Radio"},
        }
    return None


def load_default_playlist() -> list[dict]:
    try:
        data = json.loads(DEFAULT_PLAYLIST_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (FileNotFoundError, OSError, ValueError):
        return []


def save_default_playlist(playlist: list[dict]) -> None:
    DEFAULT_MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    DEFAULT_PLAYLIST_FILE.write_text(
        json.dumps(playlist, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def next_item_from_queue_or_default() -> dict | None:
    global pending_default
    with queue_lock:
        if playback_queue:
            item = playback_queue.popleft()
            save_request_queue()
            return item
        if pending_default is not None:
            item, pending_default = pending_default, None
            save_request_queue()
            return item
    return next_default_item()


def take_requested_item() -> dict | None:
    with queue_lock:
        for index, item in enumerate(playback_queue):
            if not item.get("default_track"):
                del playback_queue[index]
                save_request_queue()
                return item
        return None


def mix_pcm(left: bytes, right: bytes) -> bytes:
    left_samples = array("h")
    right_samples = array("h")
    left_samples.frombytes(left[:len(left) - len(left) % SAMPLE_WIDTH])
    right_samples.frombytes(right[:len(right) - len(right) % SAMPLE_WIDTH])
    count = min(len(left_samples), len(right_samples))
    mixed = array("h")
    for index in range(count):
        fade_in = index / max(count - 1, 1)
        value = int(left_samples[index] * (1 - fade_in) + right_samples[index] * fade_in)
        mixed.append(max(-32768, min(32767, value)))
    return mixed.tobytes()


def stop_decoder(decoder: subprocess.Popen | None) -> None:
    if decoder and decoder.stdout:
        decoder.stdout.close()
    for process in (decoder, getattr(decoder, "ytdlp", None)):
        if process and process.poll() is None:
            process.terminate()


class PrefetchedTrack:
    def __init__(self, item: dict):
        self.item = item
        self.decoder = decode_item(item)
        self.file = tempfile.NamedTemporaryFile(prefix="radio-prefetch-", suffix=".pcm", delete=False)
        self.path = self.file.name
        self.done = False
        self.error = None
        self.thread = Thread(target=self._read, daemon=True)
        self.thread.start()

    def _read(self) -> None:
        try:
            while True:
                chunk = self.decoder.stdout.read(64 * 1024)
                if not chunk:
                    break
                self.file.write(chunk)
            self.file.flush()
        except (OSError, ValueError) as error:
            self.error = error
        finally:
            self.file.close()
            self.done = True

    def wait(self) -> None:
        self.thread.join()
        if self.error:
            raise self.error

    def stream(self, output, tail: bytearray, should_stop=None) -> bytearray:
        with open(self.path, "rb") as source:
            return stream_track(source, output, tail, should_stop=should_stop)

    def cleanup(self) -> None:
        stop_decoder(self.decoder)
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass


def create_output_process() -> subprocess.Popen:
    print("Conectando salida de audio a Icecast...", flush=True)
    return subprocess.Popen([
        "ffmpeg", "-hide_banner", "-loglevel", "warning", "-threads", "1", "-re",
        "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", str(CHANNELS), "-i", "pipe:0",
        "-c:a", "libmp3lame", "-b:a", "128k", "-content_type", "audio/mpeg",
        "-flush_packets", "1", "-f", "mp3", OUTPUT_URL,
    ], stdin=subprocess.PIPE)


def output_is_healthy(output: subprocess.Popen | None) -> bool:
    if output is None:
        return False
    stdin = getattr(output, "stdin", None)
    if output.poll() is not None:
        return False
    if stdin is None or stdin.closed:
        return False
    return True


def close_output_process(output: subprocess.Popen | None) -> None:
    if output is None:
        return
    stdin = getattr(output, "stdin", None)
    if stdin is not None and not stdin.closed:
        try:
            stdin.close()
        except Exception:
            pass
    try:
        output.terminate()
        output.wait(timeout=2)
    except Exception:
        pass


def ensure_output_process(output: subprocess.Popen | None) -> subprocess.Popen:
    if output_is_healthy(output):
        return output

    if output is not None:
        close_output_process(output)

    return create_output_process()


def write_output_chunk(output, chunk: bytes) -> None:
    if not chunk:
        return
    try:
        output.write(chunk)
    except BrokenPipeError:
        close_output_process(output)
        raise


def stream_track(
    decoder,
    output,
    tail: bytearray,
    initial_chunk: bytes = b"",
    should_stop=None,
    transition_buffer: int | None = None,
) -> bytearray:
    try:
        chunks = [initial_chunk] if initial_chunk else []
        buffer_limit = transition_buffer if transition_buffer is not None else CROSSFADE_BYTES
        while True:
            if should_stop and should_stop():
                raise OSError("salto solicitado")
            chunk = chunks.pop(0) if chunks else decoder.read(64 * 1024)
            if not chunk:
                break
            if buffer_limit <= 0:
                write_output_chunk(output, chunk)
            else:
                tail.extend(chunk)
                if len(tail) > buffer_limit:
                    window = tail[:-buffer_limit]
                    if window:
                        write_output_chunk(output, window)
                    del tail[:-buffer_limit]
        try:
            output.flush()
        except BrokenPipeError:
            close_output_process(output)
            raise
    except (BrokenPipeError, OSError, ValueError):
        raise
    return tail


def is_same_track(item_a: dict | None, item_b: dict | None) -> bool:
    if item_a is None or item_b is None:
        return item_a is item_b
    a_key = item_a.get("video_id") or item_a.get("stream_url") or item_a.get("file_path")
    b_key = item_b.get("video_id") or item_b.get("stream_url") or item_b.get("file_path")
    if not a_key or not b_key:
        return item_a == item_b
    return a_key == b_key


def should_advance_after_skip(current_item: dict | None, next_item: dict | None) -> bool:
    if next_item is None:
        return False
    if current_item is None:
        return True
    return not is_same_track(current_item, next_item)


def set_current(item: dict | None) -> None:
    global current_item, current_started_at
    with state_lock:
        current_item = item
        current_started_at = time.time() if item else None
    save_request_queue()


def radio_state() -> dict:
    def public_item(item: dict) -> dict:
        metadata = item.get("metadata", {})
        return {
            "video_id": item.get("video_id"),
            "stream_url": item.get("stream_url"),
            "title": metadata.get("title") or "Pista desconocida",
            "channel": metadata.get("channel"),
            "duration": metadata.get("duration"),
            "default_track": bool(item.get("default_track")),
            "requested_track": bool(item.get("requested_track")),
        }

    with state_lock:
        current = public_item(current_item) if current_item else None
        started_at = current_started_at
        queue = ([public_item(prefetched_item)] if prefetched_item else [])
        queue.extend(public_item(item) for item in playback_queue)
    if current and started_at:
        current["elapsed"] = max(0, int(time.time() - started_at))
    return {"current": current, "queue": queue}


def play_queue() -> None:
    global active_decoder, skip_requested, priority_requested, prefetched_item
    output = None
    current_decoder = None
    current_prepared = None
    next_prepared = None
    item = None
    try:
        while True:
            if item is None:
                item = next_item_from_queue_or_default()
                if item is None:
                    time.sleep(0.25)
                    continue

            try:
                next_item = None
                if current_prepared is None:
                    current_decoder = decode_item(item)
                    with state_lock:
                        active_decoder = current_decoder
                    initial_chunk = current_decoder.stdout.read(64 * 1024)
                    if not initial_chunk:
                        raise OSError("El decodificador no entregó audio")
                else:
                    current_prepared.wait()
                    if current_prepared.error:
                        raise current_prepared.error
                    initial_chunk = b""

                set_current(item)
                next_item = next_item_from_queue_or_default()
                if next_item and next_prepared is None:
                    next_prepared = PrefetchedTrack(next_item)
                    with state_lock:
                        prefetched_item = next_item
                    print(
                        f"Precargando siguiente pista: "
                        f"{next_item.get('metadata', {}).get('title', 'pista desconocida')}",
                        flush=True,
                    )

                output = ensure_output_process(output)
                stop_for_skip = lambda: (
                    skip_requested and (next_prepared is None or next_prepared.done)
                ) or (
                    priority_event.is_set()
                    and item.get("default_track", False)
                )
                if current_prepared is None:
                    stream_track(
                        current_decoder.stdout,
                        output.stdin,
                        bytearray(),
                        initial_chunk,
                        stop_for_skip,
                        transition_buffer=CROSSFADE_BYTES,
                    )
                else:
                    current_prepared.stream(
                        output.stdin,
                        bytearray(),
                        stop_for_skip,
                    )

                if current_decoder:
                    stop_decoder(current_decoder)
                    current_decoder = None
                if current_prepared:
                    current_prepared.cleanup()
                    current_prepared = None

                # Requests always outrank a default track, including one
                # that was already prefetched.
                if next_prepared and next_item and next_item.get("default_track"):
                    requested_item = take_requested_item()
                    if requested_item is not None:
                        next_prepared.cleanup()
                        pending_default = next_item
                        next_item = requested_item
                        next_prepared = PrefetchedTrack(next_item)
                        with state_lock:
                            prefetched_item = next_item

                if next_prepared:
                    next_prepared.wait()
                    if next_prepared.error:
                        raise next_prepared.error
                    if next_item.get("default_track"):
                        requested_item = take_requested_item()
                        if requested_item is not None:
                            next_prepared.cleanup()
                            pending_default = next_item
                            next_item = requested_item
                            next_prepared = PrefetchedTrack(next_item)
                            next_prepared.wait()
                            if next_prepared.error:
                                raise next_prepared.error
                    item = next_item
                    current_prepared = next_prepared
                    next_prepared = None
                    with state_lock:
                        prefetched_item = None
                    skip_requested = False
                    priority_event.clear()
                    print(f"Comienza la siguiente pista: {item.get('metadata', {}).get('title', 'pista desconocida')}", flush=True)
                else:
                    output.stdin.flush()
                    item = None
            except (BrokenPipeError, OSError, ValueError, subprocess.SubprocessError) as error:
                if isinstance(error, BrokenPipeError):
                    close_output_process(output)
                    output = None
                if item and not item.get("default_track") and not priority_requested and not skip_requested:
                    with queue_lock:
                        playback_queue.appendleft(item)
                        save_request_queue()
                if skip_requested and next_prepared and next_prepared.done and not next_prepared.error:
                    if not should_advance_after_skip(item, next_item):
                        print("Skip ignorado: la pista siguiente es la misma que la actual.", flush=True)
                        skip_requested = False
                        next_prepared.cleanup()
                        next_prepared = None
                        if next_item and next_item.get("default_track"):
                            pending_default = next_item
                        elif next_item:
                            with queue_lock:
                                playback_queue.appendleft(next_item)
                                save_request_queue()
                        item = None
                        continue
                    if current_decoder:
                        stop_decoder(current_decoder)
                        current_decoder = None
                    if current_prepared:
                        current_prepared.cleanup()
                        current_prepared = None
                    if next_item and next_item.get("default_track"):
                        requested_item = take_requested_item()
                        if requested_item is not None:
                            next_prepared.cleanup()
                            pending_default = next_item
                            next_item = requested_item
                            next_prepared = PrefetchedTrack(next_item)
                            next_prepared.wait()
                            if next_prepared.error:
                                raise next_prepared.error
                    item = next_item
                    current_prepared = next_prepared
                    next_prepared = None
                    skip_requested = False
                    with state_lock:
                        prefetched_item = None
                    print(f"Canción saltada. Comienza: {item.get('metadata', {}).get('title', 'pista desconocida')}", flush=True)
                    continue
                if next_prepared and next_item:
                    next_prepared.cleanup()
                    next_prepared = None
                    if next_item.get("default_track"):
                        pending_default = next_item
                    elif not next_item.get("default_track"):
                        with queue_lock:
                            playback_queue.appendleft(next_item)
                            save_request_queue()
                if skip_requested:
                    print("No había una pista siguiente lista; se mantiene la cola.", flush=True)
                    skip_requested = False
                elif priority_requested:
                    print("Pista por defecto interrumpida por una solicitud de !play.", flush=True)
                    priority_requested = False
                    priority_event.clear()
                    if next_prepared:
                        next_prepared.cleanup()
                        next_prepared = None
                        if next_item and next_item.get("default_track"):
                            pending_default = next_item
                    requested_item = take_requested_item()
                    if requested_item is not None:
                        item = requested_item
                        print(
                            f"Comienza la solicitud: {item.get('metadata', {}).get('title', 'pista desconocida')}",
                            flush=True,
                        )
                        continue
                else:
                    source = item.get("stream_url") or item.get("video_id") or "desconocido"
                    print(f"Error reproduciendo {source}: {error}", flush=True)
                item = None
            finally:
                if current_decoder:
                    stop_decoder(current_decoder)
                    current_decoder = None
                with state_lock:
                    active_decoder = None
        
    finally:
        stop_decoder(current_decoder)
        if current_prepared:
            current_prepared.cleanup()
        if next_prepared:
            next_prepared.cleanup()
        if output is not None:
            output.terminate()


def worker() -> None:
    play_queue()


class Handler(BaseHTTPRequestHandler):
    def _authorized(self) -> bool:
        authorization = self.headers.get("Authorization", "")
        return hmac.compare_digest(authorization, f"Bearer {TOKEN}")

    def do_GET(self):
        if self.path in {"/health", "/ping"}:
            response = json.dumps({"ok": True, "service": "radio_player", "status": "running"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(response)
            return
        if self.path == "/default-playlist" and self._authorized():
            response = json.dumps(load_default_playlist()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(response)
            return
        if self.path != "/status" or not self._authorized():
            self.send_error(401)
            return
        response = json.dumps(radio_state()).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(response)

    def do_POST(self):
        if not self._authorized():
            self.send_error(401)
            return
        if self.path == "/skip":
            global active_decoder, skip_requested, priority_requested
            skip_requested = True
            self.send_response(202)
            self.end_headers()
            self.wfile.write(b"skipping\n")
            return
        if self.path in {"/default-add", "/default-remove"}:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length))
            video_id = payload.get("video_id")
            if not isinstance(video_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
                self.send_error(400, "video_id invalido")
                return
            playlist = load_default_playlist()
            if self.path == "/default-add":
                if any(item.get("video_id") == video_id for item in playlist):
                    self.send_error(409, "la cancion ya esta en la playlist")
                    return
                item = {"video_id": video_id, "default_track": True, "metadata": payload.get("metadata", {})}
                playlist.append(item)
                save_default_playlist(playlist)
            else:
                playlist = [item for item in playlist if item.get("video_id") != video_id]
                save_default_playlist(playlist)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok\n")
            return
        if self.path != "/play":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length))
            video_id = payload.get("video_id")
            stream_url = payload.get("stream_url")
            if video_id is None and stream_url is None:
                raise ValueError("fuente de reproducción ausente")
            if video_id is not None and (
                not isinstance(video_id, str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id)
            ):
                raise ValueError("video_id inválido")
            if stream_url is not None:
                parsed_stream = urlparse(stream_url) if isinstance(stream_url, str) else None
                if (
                    parsed_stream is None
                    or parsed_stream.scheme not in {"http", "https"}
                    or not parsed_stream.hostname
                ):
                    raise ValueError("stream_url inválida")
            metadata = payload.get("metadata", {})
            if not isinstance(metadata, dict):
                raise ValueError("metadata inválida")
            metadata = {
                key: value for key, value in metadata.items()
                if key in {"title", "channel", "url"} and isinstance(value, str)
            }
            duration = payload.get("metadata", {}).get("duration")
            if isinstance(duration, (int, float)):
                metadata["duration"] = int(duration)
            with queue_lock:
                if len(playback_queue) >= MAX_QUEUE_SIZE:
                    self.send_error(429, "cola de reproducción llena")
                    return
                playback_queue.append({
                    "video_id": video_id,
                    "stream_url": stream_url,
                    "requested_track": bool(payload.get("requested_track", True)),
                    "metadata": metadata,
                })
                save_request_queue()
            global active_decoder, priority_requested, current_item
            if current_item and current_item.get("default_track"):
                priority_requested = True
                priority_event.set()
                with state_lock:
                    decoder = active_decoder
                stop_decoder(decoder)
            self.send_response(202)
            self.end_headers()
            self.wfile.write(b"queued\n")
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            self.send_error(400)

    def log_message(self, *_):
        return


def run_server() -> None:
    if not TOKEN:
        raise RuntimeError("RADIO_PLAYER_TOKEN no está configurado")
    Thread(target=worker, daemon=True).start()
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    run_server()