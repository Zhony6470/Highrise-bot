import json
import os
import queue as queue_module
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

    with download_lock:
        # Re comprobar después de adquirir el lock: otra tarea puede haber
        # terminado la descarga mientras esperábamos.
        matches = list(CACHE.glob(video_id + ".*"))
        if matches:
            return matches[0]

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
                bufsize=0,
                # Heredar stderr permite ver en Docker los errores reales de FFmpeg
                # si Icecast cierra la conexión o el encoder falla.
                stderr=None,
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


PCM_CHUNK_BYTES = 16384
# Mantener varios segundos de PCM listos evita que un pequeño jitter del
# decoder se convierta en un hueco audible para los clientes.
# Buscamos recuperar el comportamiento estable que teníamos: ~7 s de
# latencia fija, en lugar de intentar reproducir casi pegados al tiempo real.
PCM_BUFFER_SECONDS = 8.0
PCM_INITIAL_BUFFER_SECONDS = 7.0
PCM_BUFFER_CHUNKS = max(
    1,
    int(PCM_BUFFER_SECONDS / (PCM_CHUNK_BYTES / (SAMPLE_RATE * CHANNELS * 2))),
)
PCM_INITIAL_BUFFER_CHUNKS = max(
    1,
    int(PCM_INITIAL_BUFFER_SECONDS / (PCM_CHUNK_BYTES / (SAMPLE_RATE * CHANNELS * 2))),
)
PCM_CHUNK_SECONDS = PCM_CHUNK_BYTES / (SAMPLE_RATE * CHANNELS * 2)


class PCMDecoderReader:
    """Lee PCM en un hilo independiente para mantener un colchón real de audio."""

    def __init__(self, process):
        self.process = process
        self.buffer = queue_module.Queue(maxsize=PCM_BUFFER_CHUNKS)
        self.eof = threading.Event()
        self.stop_event = threading.Event()
        self.error = None
        self.thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="autodj-pcm-reader",
        )

    def start(self):
        self.thread.start()

    def _run(self):
        try:
            stdout = self.process.stdout
            if stdout is None:
                self.error = RuntimeError("El decoder FFmpeg no tiene stdout.")
                return

            while not self.stop_event.is_set():
                chunk = stdout.read(PCM_CHUNK_BYTES)
                if not chunk:
                    self.eof.set()
                    return

                while not self.stop_event.is_set():
                    try:
                        self.buffer.put(chunk, timeout=0.1)
                        break
                    except queue_module.Full:
                        # El reproductor ya tiene suficiente audio. Dejamos
                        # bloqueado al productor hasta que pueda avanzar.
                        continue
        except Exception as error:
            if not self.stop_event.is_set():
                self.error = error
        finally:
            self.eof.set()

    def get(self, timeout=0.25):
        try:
            return self.buffer.get(timeout=timeout)
        except queue_module.Empty:
            return None

    def buffered_chunks(self):
        return self.buffer.qsize()

    def stop(self):
        self.stop_event.set()
        try:
            self.process.terminate()
        except Exception:
            pass
        self.thread.join(timeout=1.5)
        self.clear()

    def clear(self):
        try:
            while True:
                self.buffer.get_nowait()
        except queue_module.Empty:
            pass


def start_decoder(path: Path):
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "warning",
        # El decoder corre ligeramente por delante y el loop de reproducción
        # entrega PCM a velocidad real. Esto crea un pequeño colchón contra
        # jitter/pausas del proceso sin introducir varios segundos de latencia.
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
        # Los avisos/errores del decoder deben quedar visibles en los logs
        # del contenedor para poder diagnosticar pistas defectuosas.
        stderr=None,
    )


def stop_decoder(process):
    if process is None:
        return

    # Primero detenemos FFmpeg y esperamos su salida. Cerrar stdout antes
    # puede provocar un SIGPIPE/Broken pipe innecesario mientras el proceso
    # todavía está intentando escribir audio.
    try:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=2)
    except Exception:
        try:
            process.kill()
            process.wait(timeout=1)
        except Exception:
            pass
    finally:
        try:
            if process.stdout:
                process.stdout.close()
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
        try:
            path = ensure_file(dict(item))
            request_id = item.get("request_id")
            with lock:
                if request_id:
                    for queued in queue:
                        if queued.get("request_id") == request_id:
                            queued["file_path"] = str(path)
                            break
                    save(QUEUE_FILE, list(queue))
            print(
                f"[AUTODJ] PRELOAD: {item.get('metadata', {}).get('title', item.get('title', 'Pista'))}",
                flush=True,
            )
        except Exception as error:
            print(f"[AUTODJ] Error precargando pista: {error}", flush=True)
        finally:
            with prefetch_lock:
                prefetching.discard(key)

    threading.Thread(target=worker, daemon=True, name="autodj-prefetch").start()


def prefetch_next(current_item: dict) -> None:
    """Mantiene preparada una sola pista siguiente sin bloquear la reproducción."""
    with lock:
        candidate = (
            queue[1]
            if active_request is not None and len(queue) > 1 and queue[0] is active_request
            else (queue[0] if queue else None)
        )

    if candidate is None:
        candidate = choose_default()

    if candidate:
        prefetch_item(candidate)


def player_loop():
    global active_request

    try:
        icecast_encoder.start()
    except Exception as error:
        print(f"[AUTODJ] No se pudo iniciar el encoder de Icecast: {error}", flush=True)

    while True:
        item = None
        decoder = None
        pcm_reader = None
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

            # Descargar la siguiente pista mientras la actual suena. Así, un
            # cambio de canción no deja al encoder sin audio durante los
            # segundos que yt-dlp necesita para resolver/descargar YouTube.
            prefetch_next(item)

            # El lector corre por delante y llena hasta ~8 s de PCM.
            # Esperamos ~7 s antes de empezar el primer envío de la pista.
            # Así recuperamos un colchón fijo frente a jitter del decoder,
            # en lugar de arrancar prácticamente pegados al tiempo real.
            pcm_reader = PCMDecoderReader(decoder)
            pcm_reader.start()

            target_initial_chunks = PCM_INITIAL_BUFFER_CHUNKS
            while (
                pcm_reader.buffered_chunks() < target_initial_chunks
                and not pcm_reader.eof.is_set()
                and not skip_event.is_set()
            ):
                time.sleep(0.01)

            # Usamos un reloj absoluto, no sleep() acumulativo. Si una
            # escritura tarda un poco más, el siguiente deadline se calcula
            # desde el reloj original y no se va desplazando cada canción.
            next_write_at = time.monotonic()

            while True:
                if skip_event.is_set():
                    pcm_reader.clear()
                    break

                if item.get("default_track") and has_requests():
                    print("[AUTODJ] Solicitud prioritaria detectada.", flush=True)
                    pcm_reader.clear()
                    break

                if not icecast_encoder.alive():
                    raise RuntimeError("El encoder persistente de Icecast se detuvo.")

                if pcm_reader.error is not None:
                    raise RuntimeError(f"Error leyendo PCM: {pcm_reader.error}")

                chunk = pcm_reader.get(timeout=0.25)
                if chunk:
                    now = time.monotonic()
                    if now > next_write_at + (PCM_CHUNK_SECONDS * 2):
                        print(
                            f"[AUTODJ] PCM CLOCK LATE: {now - next_write_at:.3f}s "
                            f"(buffer={pcm_reader.buffered_chunks()}/{PCM_BUFFER_CHUNKS})",
                            flush=True,
                        )
                        next_write_at = now

                    wait = next_write_at - now
                    if wait > 0:
                        time.sleep(wait)

                    write_started = time.monotonic()
                    icecast_encoder.write(chunk)
                    write_time = time.monotonic() - write_started

                    if write_time > PCM_CHUNK_SECONDS * 0.75:
                        print(
                            f"[AUTODJ] Encoder write lento: {write_time:.3f}s "
                            f"(buffer={pcm_reader.buffered_chunks()}/{PCM_BUFFER_CHUNKS})",
                            flush=True,
                        )

                    next_write_at += PCM_CHUNK_SECONDS
                    continue

                if pcm_reader.eof.is_set() and pcm_reader.buffered_chunks() == 0:
                    break

                print(
                    f"[AUTODJ] PCM UNDERRUN: buffer vacío "
                    f"(eof={pcm_reader.eof.is_set()})",
                    flush=True,
                )

            was_skipped = skip_event.is_set()
            elapsed_playback = (
                time.monotonic() - playback_started_at
                if playback_started_at is not None
                else 0
            )
            return_code = decoder.poll() if decoder is not None else None

            stop_decoder(decoder)
            decoder = None
            pcm_reader = None
            skip_event.clear()

            if request_item and request_ref and item.get("request_id"):
                if was_skipped:
                    set_request_result(item, "skipped")
                elif return_code == 0 or elapsed_playback >= 2:
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
            if pcm_reader is not None:
                pcm_reader.stop()
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
                # Resolver la URL mientras la pista actual sigue sonando.
                # Esto hace que !play/!skip no tenga que esperar a yt-dlp.
                prefetch_item(item)
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
