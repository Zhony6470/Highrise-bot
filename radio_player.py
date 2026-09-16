import hmac
import json
import os
import queue
import re
import shutil
import subprocess
import time
from array import array
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock, Thread
from urllib.parse import urlparse

HOST = os.environ.get("RADIO_HOST", "0.0.0.0")
PORT = int(os.environ.get("RADIO_PORT", "8090"))
TOKEN = os.environ.get("RADIO_PLAYER_TOKEN", "")
if not TOKEN:
    raise RuntimeError("RADIO_PLAYER_TOKEN no está configurado")
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")

# Ruta opcional a las cookies exportadas para mitigar bloqueos en VPS
COOKIES_PATH = os.environ.get(
    "YOUTUBE_COOKIES_PATH",
    os.path.join(os.path.dirname(__file__), "cookies.txt"),
)
USE_YOUTUBE_COOKIES = os.environ.get("YOUTUBE_USE_COOKIES", "0") == "1"
RUNTIME_COOKIES_PATH = os.path.join("/tmp", "yt-dlp-cookies.txt")

playback_queue = deque()
queue_lock = Lock()
SAMPLE_RATE = 44100
CHANNELS = 2
SAMPLE_WIDTH = 2
CROSSFADE_SECONDS = max(float(os.environ.get("RADIO_CROSSFADE_SECONDS", "3")), 0)
CROSSFADE_BYTES = int(SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH * CROSSFADE_SECONDS)
STREAM_PATH = "/stream"
STREAM_QUEUE_SIZE = 16


class LocalAudioPublisher:
    def __init__(self):
        self.clients = set()
        self.clients_lock = Lock()

    def subscribe(self):
        client = queue.Queue(maxsize=STREAM_QUEUE_SIZE)
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
            except queue.Full:
                try:
                    client.get_nowait()
                    client.put_nowait(chunk)
                except queue.Empty:
                    pass


audio_publisher = LocalAudioPublisher()

print(f"Radio player escuchando en {HOST}:{PORT}", flush=True)


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
    print("Publicando audio local para Liquidsoap...", flush=True)
    output = subprocess.Popen([
        "ffmpeg", "-hide_banner", "-loglevel", "warning", "-re",
        "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", str(CHANNELS), "-i", "pipe:0",
        "-c:a", "libmp3lame", "-b:a", "128k", "-f", "mp3", "pipe:1",
    ], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    Thread(target=publish_output, args=(output,), daemon=True).start()
    return output


def publish_output(output: subprocess.Popen) -> None:
    while output.stdout:
        chunk = output.stdout.read(64 * 1024)
        if not chunk:
            break
        audio_publisher.publish(chunk)


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
                item = playback_queue.popleft() if playback_queue else None
            if item is None:
                time.sleep(0.25)
                continue
            try:
                while True:
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
                        print("Conexión local cerrada. Recreando salida del stream...")
                        output = ensure_output_process(output)
                        stop_decoder(current)
                        current = None
                        time.sleep(1)
                        continue
                    with queue_lock:
                        next_item = playback_queue.popleft() if playback_queue else None
                    if next_item is None:
                        try:
                            output = ensure_output_process(output)
                            output.stdin.write(tail)
                            output.stdin.flush()
                        except (BrokenPipeError, OSError):
                            print("Conexión local cerrada mientras enviaba cola final.")
                            output = ensure_output_process(output)
                            stop_decoder(current)
                            current = None
                            time.sleep(1)
                            continue
                        break
                    next_decoder = decode_item(next_item)
                    prefix = next_decoder.stdout.read(CROSSFADE_BYTES) if CROSSFADE_BYTES else b""
                    try:
                        output = ensure_output_process(output)
                        output.stdin.write(mix_pcm(bytes(tail), prefix) if CROSSFADE_BYTES else prefix)
                        if len(prefix) > len(tail):
                            output.stdin.write(prefix[len(tail):])
                        output.stdin.flush()
                    except (BrokenPipeError, OSError):
                        print("Conexión local cerrada durante el crossfade.")
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
                playback_queue.append({
                    "video_id": video_id,
                    "stream_url": stream_url,
                    "metadata": metadata,
                })
            self.send_response(202)
            self.end_headers()
            self.wfile.write(b"queued\n")
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            self.send_error(400)

    def do_GET(self):
        if self.path != STREAM_PATH:
            self.send_error(404)
            return
        client = audio_publisher.subscribe()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Cache-Control", "no-cache, no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            while True:
                self.wfile.write(client.get())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            audio_publisher.unsubscribe(client)

    def log_message(self, *_):
        return


def run_server() -> None:
    Thread(target=worker, daemon=True).start()
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    run_server()