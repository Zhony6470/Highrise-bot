import hashlib
import hmac
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
from pathlib import Path
from threading import Event, Lock, Thread
from urllib.parse import quote, urlparse


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
        "ICECAST_URL",
        "icecast://source:CHANGE_ME@127.0.0.1:8000/radio.mp3",
    )


OUTPUT_URL = get_output_url()

COOKIES_PATH = os.environ.get(
    "YOUTUBE_COOKIES_PATH",
    os.path.join(os.path.dirname(__file__), "cookies.txt"),
)
USE_YOUTUBE_COOKIES = os.environ.get("YOUTUBE_USE_COOKIES", "0") == "1"
RUNTIME_COOKIES_PATH = "/tmp/yt-dlp-cookies.txt"

SAMPLE_RATE = 44100
CHANNELS = 2
SAMPLE_WIDTH = 2
FRAME_BYTES = CHANNELS * SAMPLE_WIDTH

CROSSFADE_SECONDS = max(
    float(os.environ.get("RADIO_CROSSFADE_SECONDS", "5")),
    0,
)
CROSSFADE_BYTES = int(SAMPLE_RATE * FRAME_BYTES * CROSSFADE_SECONDS)

MAX_QUEUE_SIZE = 10
YTDLP_CACHE_DIR = os.environ.get("YTDLP_CACHE_DIR", "/app/.cache")
YTDLP_SLEEP_REQUESTS = os.environ.get("YTDLP_SLEEP_REQUESTS", "0.75")
YTDLP_SLEEP_INTERVAL = os.environ.get("YTDLP_SLEEP_INTERVAL", "10")
YTDLP_MAX_SLEEP_INTERVAL = os.environ.get("YTDLP_MAX_SLEEP_INTERVAL", "20")

DEFAULT_MUSIC_DIR = Path(os.environ.get("DEFAULT_MUSIC_DIR", "/app/default_music"))
DEFAULT_CACHE_DIR = Path(os.environ.get("DEFAULT_CACHE_DIR", "/app/default_cache"))
DEFAULT_PLAYLIST_FILE = DEFAULT_MUSIC_DIR / "playlist.json"
REQUEST_QUEUE_FILE = DEFAULT_MUSIC_DIR / "request_queue.json"
DEFAULT_AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac"}

playback_queue = deque()
queue_lock = Lock()
state_lock = Lock()

current_item = None
current_started_at = None

# Estos eventos son la única forma de pedir una interrupción al hilo de reproducción.
# Nunca cerramos desde HTTP el stdout del decoder que está reproduciendo.
skip_event = Event()
priority_event = Event()

prefetched_item = None
pending_default = None

default_tracks = sorted(
    path
    for path in DEFAULT_MUSIC_DIR.glob("**/*")
    if path.is_file() and path.suffix.lower() in DEFAULT_AUDIO_EXTENSIONS
)
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
    with queue_lock:
        pending = [item for item in playback_queue if not item.get("default_track")]
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
print(
    f"Destino Icecast configurado: {OUTPUT_URL.rsplit('@', 1)[-1]}",
    flush=True,
)


def youtube_base_args() -> list[str]:
    return [
        "--no-playlist",
        "--cache-dir",
        YTDLP_CACHE_DIR,
        "--no-progress",
        "--js-runtimes",
        "deno:/usr/local/bin/deno",
        "--sleep-requests",
        YTDLP_SLEEP_REQUESTS,
        "--sleep-interval",
        YTDLP_SLEEP_INTERVAL,
        "--max-sleep-interval",
        YTDLP_MAX_SLEEP_INTERVAL,
        "-f",
        "bestaudio/best",
        "--extractor-args",
        "youtube:player_client=android,ios,web_embedded;skip=hls,dash",
    ]


def youtube_cookie_args() -> list[str]:
    if not USE_YOUTUBE_COOKIES or not os.path.exists(COOKIES_PATH):
        return []
    try:
        shutil.copyfile(COOKIES_PATH, RUNTIME_COOKIES_PATH)
    except OSError as error:
        print(f"No se pudieron preparar las cookies de YouTube: {error}", flush=True)
        return []
    return ["--cookies", RUNTIME_COOKIES_PATH]


def decode_video(video_id: str) -> subprocess.Popen:
    source = f"https://www.youtube.com/watch?v={video_id}"
    command = ["yt-dlp", *youtube_base_args(), *youtube_cookie_args(), "-o", "-", source]
    ytdlp = subprocess.Popen(command, stdout=subprocess.PIPE)
    decoder = subprocess.Popen(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-threads",
            "1",
            "-i",
            "pipe:0",
            "-vn",
            "-f",
            "s16le",
            "-ar",
            str(SAMPLE_RATE),
            "-ac",
            str(CHANNELS),
            "pipe:1",
        ],
        stdin=ytdlp.stdout,
        stdout=subprocess.PIPE,
    )
    ytdlp.stdout.close()
    decoder.ytdlp = ytdlp
    return decoder


def decode_stream(stream_url: str) -> subprocess.Popen:
    return subprocess.Popen(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-threads",
            "1",
            "-i",
            stream_url,
            "-vn",
            "-f",
            "s16le",
            "-ar",
            str(SAMPLE_RATE),
            "-ac",
            str(CHANNELS),
            "pipe:1",
        ],
        stdout=subprocess.PIPE,
    )


def decode_file(file_path: str) -> subprocess.Popen:
    return subprocess.Popen(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-threads",
            "1",
            "-i",
            file_path,
            "-vn",
            "-f",
            "s16le",
            "-ar",
            str(SAMPLE_RATE),
            "-ac",
            str(CHANNELS),
            "pipe:1",
        ],
        stdout=subprocess.PIPE,
    )


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
                "yt-dlp",
                *youtube_base_args(),
                "--no-part",
                *youtube_cookie_args(),
                "-o",
                str(temp_dir / "%(id)s.%(ext)s"),
                video_id,
            ]
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
    global last_default_key

    try:
        playlist = json.loads(DEFAULT_PLAYLIST_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        playlist = []

    if playlist:
        candidates = [dict(item) for item in playlist if item.get("video_id")]
        if len(candidates) > 1:
            candidates = [
                item
                for item in candidates
                if item.get("video_id") != last_default_key
            ] or candidates
            random.shuffle(candidates)

        if not candidates:
            return None

        item = candidates[0]
        item["default_track"] = True
        last_default_key = item.get("video_id")
        return item

    if default_tracks:
        candidates = [
            path for path in default_tracks if str(path) != last_default_key
        ] or list(default_tracks)
        random.shuffle(candidates)
        path = candidates[0]
        last_default_key = str(path)
        return {
            "file_path": str(path),
            "default_track": True,
            "metadata": {
                "title": path.stem,
                "channel": "Highrise Radio",
            },
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
        json.dumps(playlist, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def pop_next_requested() -> dict | None:
    with queue_lock:
        for index, item in enumerate(playback_queue):
            if not item.get("default_track"):
                del playback_queue[index]
                break
        else:
            return None
    save_request_queue()
    return item


def pop_next_item() -> dict | None:
    global pending_default

    with queue_lock:
        if playback_queue:
            item = playback_queue.popleft()
        else:
            item = None

    if item is not None:
        save_request_queue()
        return item

    if pending_default is not None:
        item = pending_default
        pending_default = None
        return item

    return next_default_item()


def item_key(item: dict | None) -> str | None:
    if not item:
        return None
    return (
        item.get("video_id")
        or item.get("stream_url")
        or item.get("file_path")
    )


def same_item(a: dict | None, b: dict | None) -> bool:
    return item_key(a) is not None and item_key(a) == item_key(b)


def set_current(item: dict | None) -> None:
    global current_item, current_started_at
    with state_lock:
        current_item = item
        current_started_at = time.time() if item else None
    save_request_queue()


def stop_process(process: subprocess.Popen | None) -> None:
    if process is None:
        return

    # Terminar primero y cerrar stdout después evita Broken pipe durante !skip.
    children = [process, getattr(process, "ytdlp", None)]
    for child in children:
        try:
            if child and child.poll() is None:
                child.terminate()
        except Exception:
            pass

    for child in children:
        try:
            if child and child.poll() is None:
                child.wait(timeout=1)
        except Exception:
            pass

    try:
        if process.stdout and not process.stdout.closed:
            process.stdout.close()
    except Exception:
        pass


def mix_pcm(left: bytes, right: bytes) -> bytes:
    usable = min(len(left), len(right))
    usable -= usable % FRAME_BYTES
    if usable <= 0:
        return b""

    left_samples = array("h")
    right_samples = array("h")
    left_samples.frombytes(left[:usable])
    right_samples.frombytes(right[:usable])

    mixed = array("h")
    count = min(len(left_samples), len(right_samples))
    for index in range(count):
        fade_in = index / max(count - 1, 1)
        fade_out = 1.0 - fade_in
        value = int(
            left_samples[index] * fade_out
            + right_samples[index] * fade_in
        )
        mixed.append(max(-32768, min(32767, value)))
    return mixed.tobytes()


def read_exact(source, size: int) -> bytes:
    size -= size % FRAME_BYTES
    if size <= 0:
        return b""

    chunks = []
    remaining = size
    while remaining:
        chunk = source.read(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


class OutputSink:
    """Mantiene un único encoder conectado a Icecast durante la reproducción."""

    def __init__(self):
        self.process = None

    def _start(self):
        print("Conectando salida de audio a Icecast...", flush=True)
        self.process = subprocess.Popen(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "warning",
                "-threads",
                "1",
                "-re",
                "-f",
                "s16le",
                "-ar",
                str(SAMPLE_RATE),
                "-ac",
                str(CHANNELS),
                "-i",
                "pipe:0",
                "-c:a",
                "libmp3lame",
                "-b:a",
                "128k",
                "-content_type",
                "audio/mpeg",
                "-flush_packets",
                "1",
                "-f",
                "mp3",
                OUTPUT_URL,
            ],
            stdin=subprocess.PIPE,
            bufsize=0,
        )

    def ensure(self):
        if self.process is not None and self.process.poll() is None:
            return
        self.close()
        self._start()

    def write(self, data: bytes):
        if not data:
            return

        self.ensure()
        try:
            self.process.stdin.write(data)
        except (BrokenPipeError, OSError):
            # No repetir el mismo bloque PCM después de reconectar:
            # reenviarlo puede producir un fragmento duplicado al oyente.
            print(
                "Salida Icecast desconectada; reconectando sin repetir audio...",
                flush=True,
            )
            self.close()
            self._start()
            # El bloque que provocó el fallo se descarta deliberadamente.
            # El siguiente bloque continúa desde el punto correcto.

    def flush(self):
        if self.process and self.process.stdin and not self.process.stdin.closed:
            self.process.stdin.flush()

    def close(self):
        process = self.process
        self.process = None
        if process is None:
            return
        try:
            if process.stdin and not process.stdin.closed:
                process.stdin.close()
        except Exception:
            pass
        try:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=2)
        except Exception:
            pass


def stream_decoder(
    decoder,
    output: OutputSink,
    tail: bytearray,
    stop_condition,
) -> tuple[bytearray, bool]:
    """Envía PCM manteniendo un buffer final para el crossfade.

    Devuelve (cola_pcm, interrumpida). No cierra el decoder desde otro hilo.
    """
    while True:
        if stop_condition():
            return tail, True

        chunk = decoder.stdout.read(64 * 1024)
        if not chunk:
            return tail, False

        if CROSSFADE_BYTES <= 0:
            output.write(chunk)
            continue

        tail.extend(chunk)
        if len(tail) > CROSSFADE_BYTES:
            ready = len(tail) - CROSSFADE_BYTES
            output.write(bytes(tail[:ready]))
            del tail[:ready]


class PreparedTrack:
    def __init__(self, item: dict):
        self.item = item
        self.decoder = decode_item(item)
        self.file = tempfile.NamedTemporaryFile(
            prefix="radio-prefetch-",
            suffix=".pcm",
            delete=False,
        )
        self.path = self.file.name
        self.done = False
        self.error = None
        self.offset = 0
        self.thread = Thread(target=self._fill, daemon=True)
        self.thread.start()

    def _fill(self):
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
            try:
                self.file.close()
            except Exception:
                pass
            self.done = True

    def wait(self):
        self.thread.join()
        if self.error:
            raise self.error

    def read_from_offset(self):
        source = open(self.path, "rb")
        if self.offset:
            source.seek(self.offset)
        return source

    def remaining_bytes(self) -> int:
        try:
            return max(0, os.path.getsize(self.path) - self.offset)
        except OSError:
            return 0

    def stream(self, output: OutputSink, stop_condition) -> tuple[bytearray, bool]:
        with self.read_from_offset() as source:
            tail = bytearray()
            interrupted = stream_file(source, output, tail, stop_condition)
            return tail, interrupted

    def cleanup(self):
        stop_process(self.decoder)
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass


def stream_file(source, output: OutputSink, tail: bytearray, stop_condition) -> bool:
    while True:
        if stop_condition():
            return True

        chunk = source.read(64 * 1024)
        if not chunk:
            return False

        if CROSSFADE_BYTES <= 0:
            output.write(chunk)
            continue

        tail.extend(chunk)
        if len(tail) > CROSSFADE_BYTES:
            ready = len(tail) - CROSSFADE_BYTES
            output.write(bytes(tail[:ready]))
            del tail[:ready]


def perform_crossfade(output: OutputSink, current_tail: bytes, prepared: PreparedTrack) -> bool:
    if CROSSFADE_BYTES <= 0 or not current_tail:
        return False

    prepared.wait()
    if prepared.error:
        raise prepared.error

    with open(prepared.path, "rb") as source:
        incoming = read_exact(source, len(current_tail))

    if not incoming:
        return False

    overlap = min(len(current_tail), len(incoming))
    overlap -= overlap % FRAME_BYTES
    if overlap <= 0:
        return False

    # Si la siguiente pista dura menos que el crossfade, no perdemos
    # el final de la pista actual que queda fuera del solapamiento.
    if len(current_tail) > overlap:
        output.write(current_tail[:-overlap])

    output.write(mix_pcm(current_tail[-overlap:], incoming[:overlap]))
    prepared.offset = overlap
    print(
        f"Crossfade aplicado: {overlap / (SAMPLE_RATE * FRAME_BYTES):.2f}s",
        flush=True,
    )
    return True


def choose_after_interruption(current: dict, prepared: PreparedTrack | None, prepared_item: dict | None):
    """Decide qué pista debe sonar después de !skip o una solicitud prioritaria."""
    global pending_default

    if priority_event.is_set() and current.get("default_track"):
        requested = pop_next_requested()
        if requested is not None:
            if prepared is not None:
                prepared.cleanup()
            if prepared_item and prepared_item.get("default_track"):
                pending_default = prepared_item
            return requested, None

    if prepared is not None and prepared_item is not None:
        return prepared_item, prepared

    return pop_next_item(), None


def radio_state() -> dict:
    def public_item(item):
        metadata = item.get("metadata", {}) if item else {}
        return {
            "video_id": item.get("video_id") if item else None,
            "stream_url": item.get("stream_url") if item else None,
            "title": metadata.get("title") or "Pista desconocida",
            "channel": metadata.get("channel"),
            "duration": metadata.get("duration"),
            "default_track": bool(item and item.get("default_track")),
            "requested_track": bool(item and item.get("requested_track")),
        }

    with state_lock:
        current = public_item(current_item) if current_item else None
        started_at = current_started_at
        queued_prefetch = public_item(prefetched_item) if prefetched_item else None

    with queue_lock:
        queued = list(playback_queue)

    result_queue = []
    if queued_prefetch:
        result_queue.append(queued_prefetch)
    result_queue.extend(public_item(item) for item in queued)

    if current and started_at:
        current["elapsed"] = max(0, int(time.time() - started_at))

    return {"current": current, "queue": result_queue}


def play_queue():
    global prefetched_item, pending_default

    output = OutputSink()

    current = None
    current_decoder = None
    current_prepared = None

    next_prepared = None
    next_item = None

    try:
        while True:
            # ------------------------------------------------------------
            # 1. Obtener la pista actual.
            # ------------------------------------------------------------
            if current is None:
                current = pop_next_item()
                if current is None:
                    time.sleep(0.25)
                    continue

                try:
                    current_decoder = decode_item(current)
                except Exception as error:
                    print(
                        f"Error preparando {current.get('video_id', 'pista')}: {error}",
                        flush=True,
                    )
                    current = None
                    time.sleep(0.5)
                    continue

                current_prepared = None
                set_current(current)

            # ------------------------------------------------------------
            # 2. Preparar UNA sola siguiente pista en segundo plano.
            #    Se completa antes de necesitarla para el crossfade.
            # ------------------------------------------------------------
            if next_prepared is None:
                candidate = pop_next_item()
                if candidate is not None:
                    try:
                        next_prepared = PreparedTrack(candidate)
                        next_item = candidate
                        with state_lock:
                            prefetched_item = candidate
                        print(
                            f"Precargando siguiente pista: "
                            f"{candidate.get('metadata', {}).get('title', 'pista desconocida')}",
                            flush=True,
                        )
                    except Exception as error:
                        print(
                            f"Error precargando pista: {error}",
                            flush=True,
                        )
                        next_prepared = None
                        next_item = None
                        with state_lock:
                            prefetched_item = None

            # ------------------------------------------------------------
            # 3. Reproducir la pista actual.
            #    La petición HTTP SOLO activa eventos. Nunca mata el
            #    decoder desde otro hilo.
            # ------------------------------------------------------------
            def should_stop():
                return skip_event.is_set() or (
                    priority_event.is_set()
                    and current is not None
                    and current.get("default_track", False)
                )

            output.ensure()

            try:
                if current_decoder is not None:
                    tail = bytearray()
                    interrupted = stream_decoder(
                        current_decoder,
                        output,
                        tail,
                        should_stop,
                    )
                    stop_process(current_decoder)
                    current_decoder = None
                elif current_prepared is not None:
                    tail, interrupted = current_prepared.stream(
                        output,
                        should_stop,
                    )
                    current_prepared.cleanup()
                    current_prepared = None
                else:
                    raise OSError("estado interno: no existe decoder para la pista actual")
            except (BrokenPipeError, OSError, ValueError, subprocess.SubprocessError):
                stop_process(current_decoder)
                current_decoder = None
                if current_prepared is not None:
                    current_prepared.cleanup()
                    current_prepared = None
                raise

            # ------------------------------------------------------------
            # 4. Interrupción: !skip o !play durante playlist por defecto.
            # ------------------------------------------------------------
            if interrupted:
                old_current = current
                # El tail de una pista interrumpida se descarta. Solo se usa
                # para crossfade cuando la pista termina de forma natural.

                if priority_event.is_set() and old_current.get("default_track"):
                    priority_event.clear()

                    # La solicitud puede estar ya en next_prepared. En ese
                    # caso ya fue retirada de playback_queue por la precarga.
                    if (
                        next_prepared is not None
                        and next_item is not None
                        and not next_item.get("default_track")
                    ):
                        current = next_item
                        current_prepared = next_prepared
                        current_decoder = None

                        next_prepared = None
                        next_item = None
                        with state_lock:
                            prefetched_item = None

                        set_current(current)
                        print(
                            f"Comienza la solicitud: "
                            f"{current.get('metadata', {}).get('title', 'pista desconocida')}",
                            flush=True,
                        )
                        skip_event.clear()
                        continue

                    requested = pop_next_requested()

                    if requested is not None:
                        # La pista por defecto que estaba precargada no se pierde.
                        if next_prepared is not None and next_item is not None:
                            if next_item.get("default_track"):
                                pending_default = next_item
                            else:
                                with queue_lock:
                                    playback_queue.appendleft(next_item)
                                save_request_queue()
                            next_prepared.cleanup()

                        next_prepared = None
                        next_item = None
                        with state_lock:
                            prefetched_item = None

                        current = requested
                        current_decoder = decode_item(current)
                        current_prepared = None
                        set_current(current)

                        print(
                            f"Comienza la solicitud: "
                            f"{current.get('metadata', {}).get('title', 'pista desconocida')}",
                            flush=True,
                        )

                        # Un !skip que haya llegado simultáneamente no debe
                        # saltarse también la nueva solicitud.
                        skip_event.clear()
                        continue

                    # No encontramos una solicitud; continuar normalmente.
                    skip_event.clear()

                if skip_event.is_set():
                    skip_event.clear()

                # !skip significa: pasar exactamente a la siguiente pista.
                if next_prepared is not None and next_item is not None:
                    current = next_item
                    current_prepared = next_prepared
                    current_decoder = None
                    next_prepared = None
                    next_item = None

                    with state_lock:
                        prefetched_item = None

                    set_current(current)
                    print(
                        f"Canción saltada. Comienza: "
                        f"{current.get('metadata', {}).get('title', 'pista desconocida')}",
                        flush=True,
                    )
                    continue

                current = pop_next_item()
                current_prepared = None
                current_decoder = None

                with state_lock:
                    prefetched_item = None

                if current is None:
                    set_current(None)
                    continue

                current_decoder = decode_item(current)
                set_current(current)
                print(
                    f"Canción saltada. Comienza: "
                    f"{current.get('metadata', {}).get('title', 'pista desconocida')}",
                    flush=True,
                )
                continue

            # ------------------------------------------------------------
            # 5. Final normal: hacer crossfade con la siguiente pista
            #    SOLO si está completamente preparada.
            # ------------------------------------------------------------
            if next_prepared is not None and next_item is not None:
                did_crossfade = False

                if tail:
                    try:
                        did_crossfade = perform_crossfade(
                            output,
                            bytes(tail),
                            next_prepared,
                        )
                    except Exception as error:
                        print(
                            f"Error en crossfade: {error}. "
                            f"Se continúa sin crossfade.",
                            flush=True,
                        )

                if not did_crossfade and tail:
                    output.write(bytes(tail))

                current = next_item
                current_prepared = next_prepared
                current_decoder = None

                next_prepared = None
                next_item = None

                with state_lock:
                    prefetched_item = None

                set_current(current)
                print(
                    f"Comienza la siguiente pista: "
                    f"{current.get('metadata', {}).get('title', 'pista desconocida')}",
                    flush=True,
                )
                continue

            # ------------------------------------------------------------
            # 6. No había siguiente preparada.
            #    Sacamos la cola final y en la próxima iteración buscamos
            #    otra pista.
            # ------------------------------------------------------------
            if tail:
                output.write(bytes(tail))

            current = None
            current_decoder = None
            current_prepared = None
            set_current(None)

    except (BrokenPipeError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"Error en el reproductor: {error}", flush=True)

        stop_process(current_decoder)
        current_decoder = None

        # Si hubo un fallo de salida/decoder, devolvemos las pistas retiradas
        # a la cola para no perderlas. El encoder de Icecast se recreará
        # automáticamente en la siguiente escritura.
        if next_prepared is not None and next_item is not None:
            if next_item.get("default_track"):
                pending_default = next_item
            else:
                with queue_lock:
                    playback_queue.appendleft(next_item)
                save_request_queue()
            next_prepared.cleanup()
            next_prepared = None
            next_item = None

        if current_prepared is not None:
            current_prepared.cleanup()
            current_prepared = None

        if current is not None and not current.get("default_track"):
            with queue_lock:
                playback_queue.appendleft(current)
            save_request_queue()

        current = None
        with state_lock:
            prefetched_item = None

        time.sleep(0.5)
        Thread(target=play_queue, daemon=True).start()

    finally:
        stop_process(current_decoder)

        if current_prepared is not None:
            current_prepared.cleanup()

        if next_prepared is not None:
            next_prepared.cleanup()

        output.close()


def worker():
    play_queue()


class Handler(BaseHTTPRequestHandler):
    def _authorized(self) -> bool:
        authorization = self.headers.get("Authorization", "")
        return hmac.compare_digest(authorization, f"Bearer {TOKEN}")

    def do_GET(self):
        if self.path in {"/health", "/ping"}:
            response = json.dumps(
                {"ok": True, "service": "radio_player", "status": "running"}
            ).encode("utf-8")
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
        global priority_event

        if not self._authorized():
            self.send_error(401)
            return

        if self.path == "/skip":
            skip_event.set()
            self.send_response(202)
            self.end_headers()
            self.wfile.write(b"skipping\n")
            return

        if self.path in {"/default-add", "/default-remove"}:
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length))
                video_id = payload.get("video_id")
                if not isinstance(video_id, str) or not re.fullmatch(
                    r"[A-Za-z0-9_-]{11}",
                    video_id,
                ):
                    self.send_error(400, "video_id invalido")
                    return

                playlist = load_default_playlist()

                if self.path == "/default-add":
                    if any(item.get("video_id") == video_id for item in playlist):
                        self.send_error(409, "la cancion ya esta en la playlist")
                        return

                    playlist.append(
                        {
                            "video_id": video_id,
                            "default_track": True,
                            "metadata": payload.get("metadata", {}),
                        }
                    )
                else:
                    playlist = [
                        item
                        for item in playlist
                        if item.get("video_id") != video_id
                    ]

                save_default_playlist(playlist)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok\n")
                return
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                self.send_error(400)
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
                parsed_stream = (
                    urlparse(stream_url)
                    if isinstance(stream_url, str)
                    else None
                )
                if (
                    parsed_stream is None
                    or parsed_stream.scheme not in {"http", "https"}
                    or not parsed_stream.hostname
                ):
                    raise ValueError("stream_url inválida")

            metadata = payload.get("metadata", {})
            if not isinstance(metadata, dict):
                raise ValueError("metadata inválida")

            clean_metadata = {
                key: value
                for key, value in metadata.items()
                if key in {"title", "channel", "url"}
                and isinstance(value, str)
            }

            duration = metadata.get("duration")
            if isinstance(duration, (int, float)):
                clean_metadata["duration"] = int(duration)

            with queue_lock:
                if len(playback_queue) >= MAX_QUEUE_SIZE:
                    self.send_error(429, "cola de reproducción llena")
                    return

                playback_queue.append(
                    {
                        "video_id": video_id,
                        "stream_url": stream_url,
                        "requested_track": bool(
                            payload.get("requested_track", True)
                        ),
                        "metadata": clean_metadata,
                    }
                )

            save_request_queue()

            with state_lock:
                current = current_item

            if current and current.get("default_track"):
                priority_event.set()

            self.send_response(202)
            self.end_headers()
            self.wfile.write(b"queued\n")

        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            self.send_error(400)


    def log_message(self, *_):
        return


def run_server():
    if not TOKEN:
        raise RuntimeError("RADIO_PLAYER_TOKEN no está configurado")

    Thread(target=worker, daemon=True).start()
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    run_server()
