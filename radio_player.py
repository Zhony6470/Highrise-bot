import hmac
import json
import os
import re
import shutil
import subprocess
import time
from array import array
from base64 import b64encode
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock, Thread
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

HOST = os.environ.get("RADIO_HOST", "0.0.0.0")
PORT = int(os.environ.get("RADIO_PORT", "8090"))
TOKEN = os.environ.get("RADIO_PLAYER_TOKEN", "")
if not TOKEN:
    raise RuntimeError("RADIO_PLAYER_TOKEN no está configurado")
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
ICECAST_URL = os.environ.get(
    "ICECAST_URL", "icecast://source:CHANGE_ME@127.0.0.1:8000/radio.mp3"
)
ICECAST_HOST = os.environ.get("ICECAST_HOST", "")
ICECAST_PORT = os.environ.get("ICECAST_PORT", "")
ICECAST_PASSWORD = os.environ.get("ICECAST_PASSWORD", "")
ICECAST_SOURCE = os.environ.get("ICECAST_SOURCE", "")
ICECAST_MOUNT = os.environ.get("ICECAST_MOUNT", "stream")
SHOUTCAST_HOST = os.environ.get("SHOUTCAST_HOST", "")
SHOUTCAST_PORT = os.environ.get("SHOUTCAST_PORT", "")
SHOUTCAST_PASSWORD = os.environ.get("SHOUTCAST_PASSWORD", "")
SHOUTCAST_SOURCE = os.environ.get("SHOUTCAST_SOURCE", "source")
SHOUTCAST_MOUNT = os.environ.get("SHOUTCAST_MOUNT", "stream")


def get_output_url() -> str:
    if SHOUTCAST_HOST and SHOUTCAST_PORT and SHOUTCAST_PASSWORD:
        mount = SHOUTCAST_MOUNT.strip("/")
        mount_path = f"/{quote(mount, safe='/')}" if mount else "/"
        username = quote(SHOUTCAST_SOURCE, safe="")
        password = quote(SHOUTCAST_PASSWORD, safe="")
        return f"icecast://{username}:{password}@{SHOUTCAST_HOST}:{SHOUTCAST_PORT}{mount_path}"
    if ICECAST_HOST and ICECAST_PORT and ICECAST_PASSWORD:
        username = ICECAST_SOURCE or ""
        mount = ICECAST_MOUNT.strip("/")
        mount_path = f"/{quote(mount, safe='/')}" if mount else "/"
        return f"icecast://{username}:{quote(ICECAST_PASSWORD, safe='')}@{ICECAST_HOST}:{ICECAST_PORT}{mount_path}"
    return ICECAST_URL


OUTPUT_URL = get_output_url()

output_parts = urlparse(OUTPUT_URL)
if not output_parts.hostname or not output_parts.password:
    raise RuntimeError(
        "Falta la conexión de emisión: configura SHOUTCAST_HOST, SHOUTCAST_PORT "
        "y SHOUTCAST_PASSWORD (o las variables ICECAST_* equivalentes) en Render. "
        "No uses la URL pública de escucha como destino de emisión."
    )

# Ruta opcional a las cookies exportadas para mitigar bloqueos en VPS
COOKIES_PATH = os.environ.get(
    "YOUTUBE_COOKIES_PATH",
    os.path.join(os.path.dirname(__file__), "cookies.txt"),
)
USE_YOUTUBE_COOKIES = os.environ.get("YOUTUBE_USE_COOKIES", "0") == "1"
RUNTIME_COOKIES_PATH = os.path.join("/tmp", "yt-dlp-cookies.txt")

queue = deque()
queue_lock = Lock()
SAMPLE_RATE = 44100
CHANNELS = 2
SAMPLE_WIDTH = 2
CROSSFADE_SECONDS = max(float(os.environ.get("RADIO_CROSSFADE_SECONDS", "3")), 0)
CROSSFADE_BYTES = int(SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH * CROSSFADE_SECONDS)

print(f"Radio player escuchando en {HOST}:{PORT}", flush=True)
print(f"Destino de salida configurado: {OUTPUT_URL.rsplit('@', 1)[-1]}", flush=True)


def update_icecast_metadata(metadata: dict) -> None:
    if SHOUTCAST_HOST:
        return

    title = metadata.get("title", "").strip()
    channel = metadata.get("channel", "").strip()
    if not title:
        return

    parsed = urlparse(OUTPUT_URL)
    if not parsed.hostname or not parsed.password:
        print("Metadatos omitidos: faltan credenciales de emisión")
        return

    song = f"{title} - {channel}" if channel else title
    admin_scheme = os.environ.get("ICECAST_ADMIN_SCHEME", "http")
    metadata_url = (
        f"{admin_scheme}://{parsed.hostname}:{parsed.port or 80}/admin/metadata?"
        f"mount=/{quote(parsed.path.lstrip('/'))}&mode=updinfo&song={quote(song)}"
    )
    credentials = f"{parsed.username}:{parsed.password}".encode("utf-8")
    request = Request(
        metadata_url,
        headers={"Authorization": f"Basic {b64encode(credentials).decode('ascii')}"},
    )
    try:
        with urlopen(request, timeout=5):
            pass
    except HTTPError as error:
        if error.code != 404:
            print(f"No se pudieron actualizar los metadatos de Icecast: {error}")
    except (URLError, TimeoutError) as error:
        print(f"No se pudieron actualizar los metadatos de Icecast: {error}")


def decode_video(video_id: str) -> subprocess.Popen:
    """Invoca yt-dlp con argumentos de emulación de cliente y cookies anti-bloqueo."""
    source = f"https://www.youtube.com/watch?v={video_id}"
    
    ytdlp_cmd = [
        "yt-dlp",
        "--no-playlist",
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
        "ffmpeg", "-hide_banner", "-loglevel", "warning", "-i", "pipe:0",
        "-vn", "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", str(CHANNELS), "pipe:1",
    ], stdin=ytdlp.stdout, stdout=subprocess.PIPE)
    ytdlp.stdout.close()
    decoder.ytdlp = ytdlp
    return decoder


def decode_stream(stream_url: str) -> subprocess.Popen:
    decoder = subprocess.Popen([
        "ffmpeg", "-hide_banner", "-loglevel", "warning", "-i", stream_url,
        "-vn", "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", str(CHANNELS), "pipe:1",
    ], stdout=subprocess.PIPE)
    return decoder


def decode_item(item: dict) -> subprocess.Popen:
    if item.get("stream_url"):
        return decode_stream(item["stream_url"])
    return decode_video(item["video_id"])


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


def create_output_process() -> subprocess.Popen:
    print("Conectando salida de audio a MyRadioStream...", flush=True)
    return subprocess.Popen([
        "ffmpeg", "-hide_banner", "-loglevel", "warning", "-re",
        "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", str(CHANNELS), "-i", "pipe:0",
        "-c:a", "libmp3lame", "-b:a", "128k", "-content_type", "audio/mpeg",
        "-legacy_icecast", "1",
        "-f", "mp3", OUTPUT_URL,
    ], stdin=subprocess.PIPE)


def ensure_output_process(output: subprocess.Popen | None) -> subprocess.Popen:
    if output is not None and output.poll() is None:
        return output

    if output is not None:
        try:
            output.terminate()
            output.wait(timeout=2)
        except Exception:
            pass

    return create_output_process()


def stream_track(decoder, output, tail: bytearray, initial_chunk: bytes = b"") -> bytearray:
    try:
        chunks = [initial_chunk] if initial_chunk else []
        while True:
            chunk = chunks.pop(0) if chunks else decoder.read(64 * 1024)
            if not chunk:
                break
            if CROSSFADE_BYTES == 0:
                output.write(chunk)
            else:
                tail.extend(chunk)
                if len(tail) > CROSSFADE_BYTES:
                    output.write(tail[:-CROSSFADE_BYTES])
                    del tail[:-CROSSFADE_BYTES]
        output.flush()
    except (BrokenPipeError, OSError):
        raise
    return tail


def play_queue() -> None:
    output = None
    current = None
    try:
        while True:
            with queue_lock:
                item = queue.popleft() if queue else None
            if item is None:
                time.sleep(0.25)
                continue
            try:
                while True:
                    update_icecast_metadata(item["metadata"])
                    current = decode_item(item)
                    try:
                        initial_chunk = current.stdout.read(64 * 1024)
                        if not initial_chunk:
                            raise OSError("El decodificador no entregó audio")
                        output = ensure_output_process(output)
                        tail = stream_track(
                            current.stdout,
                            output.stdin,
                            bytearray(),
                            initial_chunk,
                        )
                    except (BrokenPipeError, OSError):
                        print("Conexión a Icecast cerrada. Recreando salida del stream...")
                        output = ensure_output_process(output)
                        stop_decoder(current)
                        current = None
                        time.sleep(1)
                        continue
                    with queue_lock:
                        next_item = queue.popleft() if queue else None
                    if next_item is None:
                        try:
                            output = ensure_output_process(output)
                            output.stdin.write(tail)
                            output.stdin.flush()
                        except (BrokenPipeError, OSError):
                            print("Conexión a Icecast cerrada mientras enviaba cola final.")
                            output = ensure_output_process(output)
                            stop_decoder(current)
                            current = None
                            time.sleep(1)
                            continue
                        break
                    update_icecast_metadata(next_item["metadata"])
                    next_decoder = decode_item(next_item)
                    prefix = next_decoder.stdout.read(CROSSFADE_BYTES) if CROSSFADE_BYTES else b""
                    try:
                        output = ensure_output_process(output)
                        output.stdin.write(mix_pcm(bytes(tail), prefix) if CROSSFADE_BYTES else prefix)
                        if len(prefix) > len(tail):
                            output.stdin.write(prefix[len(tail):])
                        output.stdin.flush()
                    except (BrokenPipeError, OSError):
                        print("Conexión a Icecast cerrada durante el crossfade.")
                        output = ensure_output_process(output)
                        stop_decoder(next_decoder)
                        stop_decoder(current)
                        current = None
                        time.sleep(1)
                        continue
                    stop_decoder(current)
                    current = next_decoder
            except Exception as error:
                source = item.get("stream_url") or item.get("video_id") or "desconocido"
                print(f"Error reproduciendo {source}: {error}")
            finally:
                stop_decoder(current)
                current = None
    finally:
        stop_decoder(current)
        if output is not None:
            output.terminate()


def worker() -> None:
    play_queue()


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        authorization = self.headers.get("Authorization", "")
        expected_authorization = f"Bearer {TOKEN}"
        if (
            self.path != "/play"
            or not hmac.compare_digest(authorization, expected_authorization)
        ):
            self.send_error(401)
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
            with queue_lock:
                queue.append({
                    "video_id": video_id,
                    "stream_url": stream_url,
                    "metadata": metadata,
                })
            self.send_response(202)
            self.end_headers()
            self.wfile.write(b"queued\n")
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            self.send_error(400)

    def log_message(self, *_):
        return


Thread(target=worker, daemon=True).start()
ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()