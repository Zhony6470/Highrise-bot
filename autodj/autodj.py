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
# Solo la primera conexión necesita un colchón de arranque. Las pistas
# siguientes se preparan en paralelo antes de que termine la actual.
PCM_INITIAL_BUFFER_SECONDS = 1.5
PCM_NEXT_BUFFER_SECONDS = 2.0
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
    """Colchón PCM de una pista. El decoder produce por delante de la reproducción."""
    def __init__(self, process, max_chunks=None):
        self.process = process
        self.max_chunks = max_chunks or PCM_BUFFER_CHUNKS
        self.buffer = queue_module.Queue(maxsize=self.max_chunks)
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

    def wait_for_chunks(self, target_chunks, timeout=None):
        started = time.monotonic()
        while (
            self.buffered_chunks() < target_chunks
            and not self.eof.is_set()
            and not self.stop_event.is_set()
        ):
            if self.error is not None:
                return False
            if timeout is not None and time.monotonic() - started >= timeout:
                return False
            time.sleep(0.01)
        return self.buffered_chunks() >= target_chunks

    def stop(self):
        self.stop_event.set()
        try:
            if self.process.poll() is None:
                self.process.terminate()
        except Exception:
            pass
        self.thread.join(timeout=1.5)
        try:
            if self.process.poll() is None:
                self.process.kill()
        except Exception:
            pass
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
        stderr=None,
    )


def stop_decoder(process):
    if process is None:
        return

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


class PreparedTrack:
    """
    Prepara la siguiente pista fuera del reloj de reproducción.

    La pista siguiente puede estar descargando y decodificando mientras la
    actual sigue alimentando el encoder persistente. Al llegar al final,
    el writer cambia al buffer ya preparado sin volver a esperar 7 segundos.
    """

    def __init__(self, item: dict, initial=False):
        self.item = dict(item)
        self.initial = initial
        self.decoder = None
        self.reader = None
        self.error = None
        self.ready = threading.Event()
        self.cancel_event = threading.Event()
        self.lock = threading.RLock()
        self.thread = threading.Thread(
            target=self._prepare,
            daemon=True,
            name="autodj-track-preparer",
        )

    def start(self):
        self.thread.start()
        return self

    def _prepare(self):
        try:
            if self.cancel_event.is_set():
                return

            path = ensure_file(self.item)
            if self.cancel_event.is_set():
                return

            self.item["file_path"] = str(path)
            self.item["metadata"] = metadata(self.item)

            decoder = start_decoder(path)
            reader = PCMDecoderReader(decoder)
            with self.lock:
                self.decoder = decoder
                self.reader = reader

            reader.start()

            target_seconds = (
                PCM_INITIAL_BUFFER_SECONDS
                if self.initial
                else PCM_NEXT_BUFFER_SECONDS
            )
            target_chunks = max(1, int(target_seconds / PCM_CHUNK_SECONDS))

            if not reader.wait_for_chunks(target_chunks, timeout=20):
                if reader.error is not None:
                    raise RuntimeError(f"Error preparando PCM: {reader.error}")
                if not reader.eof.is_set():
                    raise RuntimeError(
                        f"No se pudo preparar {target_seconds:.1f}s de PCM antes del timeout."
                    )

            if self.cancel_event.is_set():
                return

            print(
                f"[AUTODJ] TRACK READY: "
                f"{self.item.get('metadata', {}).get('title', self.item.get('title', 'Pista'))} "
                f"(buffer={reader.buffered_chunks()}/{PCM_BUFFER_CHUNKS})",
                flush=True,
            )
            self.ready.set()

        except Exception as error:
            self.error = error
            print(f"[AUTODJ] Error preparando pista: {error}", flush=True)
        finally:
            if self.error is not None:
                self.ready.set()

    def wait_ready(self, timeout=None):
        self.ready.wait(timeout)
        return self.error is None and self.reader is not None

    def stop(self):
        self.cancel_event.set()
        with self.lock:
            reader = self.reader
            decoder = self.decoder
        if reader is not None:
            reader.stop()
        elif decoder is not None:
            stop_decoder(decoder)
        self.thread.join(timeout=0.5)

    def take_reader(self):
        with self.lock:
            reader = self.reader
            decoder = self.decoder
            self.reader = None
            self.decoder = None
        return decoder, reader


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


def candidate_for_current(current_item: dict):
    """Selecciona la siguiente pista sin bloquear el hilo de audio."""
    with lock:
        if current_item.get("default_track"):
            return queue[0] if queue else None
        if queue and queue[0] is active_request:
            return queue[1] if len(queue) > 1 else None
        return queue[0] if queue else None


def fallback_next_candidate():
    candidate = choose_default()
    if candidate:
        candidate["default_track"] = True
    return candidate


def should_interrupt_default():
    with lock:
        current = state.get("current") or {}
        return bool(current.get("default_track")) and bool(queue)


def player_loop():
    global active_request

    next_prepared = None

    try:
        icecast_encoder.start()
    except Exception as error:
        print(f"[AUTODJ] No se pudo iniciar el encoder de Icecast: {error}", flush=True)

    while True:
        current_source = None
        decoder = None
        pcm_reader = None
        request_ref = None
        request_item = False
        item = None
        playback_started_at = None

        try:
            if not icecast_encoder.alive():
                icecast_encoder.start()

            if next_prepared is None:
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

                current_source = PreparedTrack(item, initial=True).start()
            else:
                current_source = next_prepared
                next_prepared = None
                item = dict(current_source.item)
                request_item = not item.get("default_track")

                if request_item:
                    with lock:
                        request_ref = queue[0] if queue else None
                        active_request = request_ref

            if item.get("default_track") and queue_snapshot():
                current_source.stop()
                current_source = None
                with lock:
                    active_request = None
                continue

            if not current_source.wait_ready(timeout=30):
                raise RuntimeError(current_source.error or "La pista actual no pudo prepararse.")

            item = dict(current_source.item)
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

            decoder, pcm_reader = current_source.take_reader()
            if pcm_reader is None:
                raise RuntimeError("La pista preparada no tiene lector PCM.")

            playback_started_at = time.monotonic()

            # Preparar la siguiente pista desde el principio de la actual.
            next_candidate = candidate_for_current(item)
            if next_candidate is None:
                next_candidate = fallback_next_candidate()

            if next_candidate is not None:
                next_prepared = PreparedTrack(next_candidate, initial=False).start()

            # Solo la primera conexión necesita el pequeño colchón inicial.
            # Las siguientes ya están preparadas en paralelo.
            if not pcm_reader.wait_for_chunks(
                max(1, int(PCM_INITIAL_BUFFER_SECONDS / PCM_CHUNK_SECONDS)),
                timeout=5,
            ):
                if pcm_reader.error is not None:
                    raise RuntimeError(f"Error leyendo PCM: {pcm_reader.error}")

            next_write_at = time.monotonic()

            while True:
                if skip_event.is_set():
                    # Descartamos el buffer de la pista actual. El encoder
                    # sigue conectado y el siguiente buffer queda disponible.
                    pcm_reader.clear()
                    break

                if should_interrupt_default():
                    print(
                        "[AUTODJ] Solicitud prioritaria detectada; cambiando al siguiente buffer preparado.",
                        flush=True,
                    )
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
                    f"[AUTODJ] PCM UNDERRUN: buffer vacío (eof={pcm_reader.eof.is_set()})",
                    flush=True,
                )

            was_skipped = skip_event.is_set()
            elapsed_playback = (
                time.monotonic() - playback_started_at
                if playback_started_at is not None
                else 0
            )
            return_code = decoder.poll() if decoder is not None else None

            if pcm_reader is not None:
                pcm_reader.stop()
            pcm_reader = None
            decoder = None
            skip_event.clear()

            if request_item and request_ref and item.get("request_id"):
                if was_skipped:
                    set_request_result(item, "skipped")
                elif return_code == 0 or elapsed_playback >= 2:
                    set_request_result(item, "played")
                else:
                    set_request_result(
                        item,
                        "failed",
                        "FFmpeg terminó antes de reproducir la solicitud.",
                    )

            with lock:
                state["current"] = None
                state["started_at"] = None
                state["status"] = "idle"
                if request_item:
                    active_request = None

            if request_item:
                acknowledge_request(request_ref)

            # Si durante la reproducción apareció una solicitud, un DEFAULT
            # preparado ya no debe entrar después de ella.
            if (
                next_prepared is not None
                and next_prepared.item.get("default_track")
                and queue_snapshot()
            ):
                next_prepared.stop()
                next_prepared = None

            continue

        except Exception as error:
            print(f"[AUTODJ] error: {error}", flush=True)

            if pcm_reader is not None:
                pcm_reader.stop()
            elif decoder is not None:
                stop_decoder(decoder)

            if current_source is not None:
                try:
                    current_source.stop()
                except Exception:
                    pass

            if next_prepared is not None:
                try:
                    next_prepared.stop()
                except Exception:
                    pass
                next_prepared = None

            # Una solicitud fallida debe salir de la cola aunque no tenga
            # request_id. El request_id solo es necesario para guardar el
            # resultado; no debe bloquear el avance del reproductor.
            if request_item and request_ref:
                if item and item.get("request_id"):
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
