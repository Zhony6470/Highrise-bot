import asyncio
import json
import os
import re
import subprocess
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock, Thread
from urllib.parse import urlencode
from urllib.request import urlopen

HOST = os.environ.get("RADIO_HOST", "127.0.0.1")
PORT = int(os.environ.get("RADIO_PORT", "8090"))
TOKEN = os.environ["RADIO_PLAYER_TOKEN"]
YOUTUBE_API_KEY = os.environ["YOUTUBE_API_KEY"]
ICECAST_URL = os.environ.get(
    "ICECAST_URL", "icecast://source:CHANGE_ME@127.0.0.1:8000/radio.mp3"
)

queue = deque()
queue_lock = Lock()


def verify_creative_commons(video_id: str) -> bool:
    query = urlencode({
        "part": "snippet",
        "id": video_id,
        "key": YOUTUBE_API_KEY,
    })
    with urlopen(f"https://www.googleapis.com/youtube/v3/videos?{query}", timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    items = payload.get("items", [])
    return bool(items and items[0].get("snippet", {}).get("license") == "creativeCommon")


def play_video(video_id: str) -> None:
    if not verify_creative_commons(video_id):
        print(f"Rechazado: {video_id} no está marcado Creative Commons")
        return

    source = f"https://www.youtube.com/watch?v={video_id}"
    command = [
        "yt-dlp", "--no-playlist", "-f", "bestaudio/best", "-o", "-", source,
    ]
    ytdlp = subprocess.Popen(command, stdout=subprocess.PIPE)
    ffmpeg = subprocess.Popen([
        "ffmpeg", "-hide_banner", "-loglevel", "warning", "-i", "pipe:0",
        "-vn", "-c:a", "libmp3lame", "-b:a", "128k",
        "-content_type", "audio/mpeg", "-f", "mp3", ICECAST_URL,
    ], stdin=ytdlp.stdout)
    ytdlp.stdout.close()
    ffmpeg.wait()
    if ytdlp.poll() is None:
        ytdlp.terminate()


def worker() -> None:
    while True:
        with queue_lock:
            video_id = queue.popleft() if queue else None
        if video_id:
            try:
                play_video(video_id)
            except Exception as error:
                print(f"Error reproduciendo {video_id}: {error}")
        else:
            asyncio.run(asyncio.sleep(1))


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/play" or self.headers.get("Authorization") != f"Bearer {TOKEN}":
            self.send_error(401)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length))
            video_id = payload["video_id"]
            if not isinstance(video_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
                raise ValueError("video_id inválido")
            with queue_lock:
                queue.append(video_id)
            self.send_response(202)
            self.end_headers()
            self.wfile.write(b"queued\n")
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            self.send_error(400)

    def log_message(self, *_):
        return


Thread(target=worker, daemon=True).start()
ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
