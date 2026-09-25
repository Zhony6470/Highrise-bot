import json
import os
import socket
import threading
import time
import uuid
from pathlib import Path


class LiquidsoapController:
    def __init__(self, *, queue, lock, state, queue_file, result_writer,
                 metadata_fn, choose_default, ensure_file, save_fn):
        self.queue = queue
        self.lock = lock
        self.state = state
        self.queue_file = queue_file
        self.set_request_result = result_writer
        self.metadata = metadata_fn
        self.choose_default = choose_default
        self.ensure_file = ensure_file
        self.save = save_fn
        self.host = os.getenv("LIQUIDSOAP_HOST", "liquidsoap")
        self.port = int(os.getenv("LIQUIDSOAP_PORT", "1234"))
        self.marker_file = Path(os.getenv("LIQUIDSOAP_MARKER_FILE", "/data/liquidsoap_now.json"))
        self.request_source = "requests"
        self.default_source = "defaults"
        self.radio_source = "radio"
        self.sent_requests = set()
        self.sent_defaults = {}
        self.last_marker = None
        self.thread = None

    @staticmethod
    def _escape(value):
        return str(value or "").replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")

    def _command(self, command):
        with socket.create_connection((self.host, self.port), timeout=2.0) as sock:
            sock.settimeout(2.0)
            sock.sendall((command.rstrip("\n") + "\n").encode("utf-8"))
            chunks = []
            while True:
                try:
                    chunk = sock.recv(4096)
                except socket.timeout:
                    break
                if not chunk:
                    break
                chunks.append(chunk)
                if b"\nEND\n" in b"".join(chunks):
                    break
        return b"".join(chunks).decode("utf-8", errors="replace")

    def _uri(self, item):
        path = item.get("file_path")
        if not path:
            raise RuntimeError("Liquidsoap recibió una pista sin file_path.")
        token = item.setdefault("play_token", uuid.uuid4().hex)
        meta = [
            f'autodj_token="{self._escape(token)}"',
            f'video_id="{self._escape(item.get("video_id", ""))}"',
            f'request_id="{self._escape(item.get("request_id", ""))}"',
            f'default_track="{"true" if item.get("default_track") else "false"}"',
        ]
        title = self.metadata(item).get("title")
        if title:
            meta.append(f'title="{self._escape(title)}"')
        return f'annotate:{",".join(meta)}:{path}'

    def push(self, source_id, item):
        response = self._command(f"{source_id}.push {self._uri(item)}")
        if "END" not in response:
            raise RuntimeError(f"Liquidsoap no confirmó push: {response.strip()}")
        print(f"[AUTODJ] LIQUIDSOAP: encolada {self.metadata(item).get('title', 'Pista')} -> {source_id}", flush=True)

    def enqueue_request(self, item):
        token = item.setdefault("play_token", uuid.uuid4().hex)
        if token in self.sent_requests:
            return
        try:
            self.push(self.request_source, item)
            self.sent_requests.add(token)
        except Exception as error:
            print(f"[AUTODJ] LIQUIDSOAP: error encolando request: {error}", flush=True)

    def _default_key(self, item):
        return str(item.get("video_id") or item.get("file_path") or "")

    def ensure_defaults(self, target=3):
        while len(self.sent_defaults) < target:
            item = None
            for _ in range(12):
                candidate = self.choose_default()
                if candidate is None:
                    return
                if self._default_key(candidate) not in self.sent_defaults:
                    item = candidate
                    break
            if item is None:
                return
            try:
                item["default_track"] = True
                item["file_path"] = str(self.ensure_file(item))
                item["play_token"] = uuid.uuid4().hex
                self.push(self.default_source, item)
                self.sent_defaults[self._default_key(item)] = item
            except Exception as error:
                print(f"[AUTODJ] LIQUIDSOAP: error preparando DEFAULT: {error}", flush=True)
                return

    def _read_marker(self):
        try:
            raw = self.marker_file.read_text(encoding="utf-8").strip()
            return json.loads(raw) if raw else None
        except (FileNotFoundError, OSError, ValueError):
            return None

    def _handle_marker(self, marker):
        if not marker:
            return

        token = marker.get("autodj_token")
        video_id = marker.get("video_id")
        title = marker.get("title") or marker.get("filename") or "Pista desconocida"

        # Liquidsoap puede conservar solo metadata estándar en el callback
        # (por ejemplo, title). Por eso usamos token/video_id/título para
        # identificar una solicitud, en ese orden, y no dependemos únicamente
        # de autodj_token.
        marker_key = token or video_id or title
        if not marker_key or marker_key == self.last_marker:
            return
        self.last_marker = marker_key

        request_item = None
        with self.lock:
            for queued in self.queue:
                queued_title = self.metadata(queued).get("title")
                if token and queued.get("play_token") == token:
                    request_item = queued
                    break
                if video_id and queued.get("video_id") == video_id:
                    request_item = queued
                    break
                if title and queued_title == title:
                    request_item = queued
                    break
            self.state["current"] = {
                "video_id": marker.get("video_id"),
                "metadata": {
                    "video_id": marker.get("video_id"),
                    "title": title,
                    "requested_by": (
                        (request_item.get("metadata") or {}).get("requested_by")
                        if request_item else None
                    ),
                    "request_id": marker.get("request_id") or None,
                },
                "default_track": str(marker.get("default_track", "")).lower() == "true",
                "file_path": request_item.get("file_path") if request_item else marker.get("filename"),
                "play_token": token,
            }
            self.state["started_at"] = time.time()
            self.state["status"] = "playing"

        if request_item is not None:
            with self.lock:
                if self.queue and self.queue[0] is request_item:
                    self.queue.popleft()
                    self.save(self.queue_file, list(self.queue))
            self.set_request_result(request_item, "played")
            print(f"[AUTODJ] REQUEST: {title}", flush=True)
        else:
            for key, item in list(self.sent_defaults.items()):
                if item.get("play_token") == token:
                    self.sent_defaults.pop(key, None)
                    break
            with self.lock:
                self.state["last_default_id"] = marker.get("video_id") or marker.get("filename")
            print(f"[AUTODJ] DEFAULT: {title}", flush=True)
            self.ensure_defaults(3)

    def skip(self):
        # El estado local puede ir un instante por detrás del audio real.
        # El comando de Liquidsoap es la fuente de verdad para saltar la
        # pista que está sonando.
        response = self._command(f"{self.radio_source}.skip")
        if "END" not in response:
            raise RuntimeError(f"Liquidsoap no confirmó skip: {response.strip()}")

    def run(self):
        print(f"[AUTODJ] Liquidsoap controller: {self.host}:{self.port}", flush=True)
        while True:
            try:
                self._handle_marker(self._read_marker())
                self.ensure_defaults(3)
                with self.lock:
                    pending = list(self.queue)
                for item in pending:
                    if item.get("file_path"):
                        self.enqueue_request(item)
            except Exception as error:
                print(f"[AUTODJ] Liquidsoap controller error: {error}", flush=True)
            time.sleep(0.25)

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self.run, daemon=True, name="autodj-liquidsoap-controller")
        self.thread.start()
