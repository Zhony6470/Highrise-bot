import json
import re
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
        # Liquidsoap exposes the fallback radio under this command namespace.
        self.radio_source = "Highrise_Radio"
        self.sent_requests = set()
        self.sent_defaults = {}
        self.last_marker = None
        self.last_on_air_rid = None
        self.reconciled_requests = False
        self.thread = None

    @staticmethod
    def _escape(value):
        return str(value or "").replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")

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

    def _reconcile_requests(self):
        """Mark persisted AutoDJ requests already present in Liquidsoap.

        This prevents a controller restart from pushing the same request a
        second time into Liquidsoap's real queue.
        """
        try:
            rids = self._queue_rids(self.request_source)
            on_air = self._on_air_rid()
            if on_air:
                rids.insert(0, on_air)

            liquidsoap_items = []
            for rid in dict.fromkeys(rids):
                liquidsoap_items.append(self._request_metadata(rid))

            with self.lock:
                pending = list(self.queue)

            for item in pending:
                token = item.get("play_token")
                video_id = item.get("video_id")
                request_id = item.get("request_id")
                for meta in liquidsoap_items:
                    if (token and meta.get("autodj_token") == token) or (
                        video_id and meta.get("video_id") == video_id
                    ) or (request_id and meta.get("request_id") == request_id):
                        if token:
                            self.sent_requests.add(token)
                        break

            self.reconciled_requests = True
            print(
                f"[AUTODJ] LIQUIDSOAP: reconciliadas {len(liquidsoap_items)} requests existentes",
                flush=True,
            )
            return True
        except Exception as error:
            print(f"[AUTODJ] LIQUIDSOAP: no se pudo reconciliar requests: {error}", flush=True)
            return False

    def enqueue_request(self, item):
        if not self.reconciled_requests:
            return
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

    def _queue_rids(self, source_id):
        """Return every RID reported by a Liquidsoap request queue."""
        response = self._command(f"{source_id}.queue")
        return [
            token
            for token in response.split()
            if token and token != "END"
        ]

    def _queue_count(self, source_id):
        """Return the number of RIDs currently waiting in a Liquidsoap queue."""
        try:
            return len(self._queue_rids(source_id))
        except Exception as error:
            print(
                f"[AUTODJ] LIQUIDSOAP: no se pudo consultar {source_id}.queue: {error}",
                flush=True,
            )
            return None

    def ensure_defaults(self, target=3):
        """Keep the real Liquidsoap default queue populated.

        sent_defaults is only bookkeeping. The source of truth is
        defaults.queue, because a track can be consumed by Liquidsoap
        without the metadata callback preserving our custom annotate fields.
        """
        queued = self._queue_count(self.default_source)
        if queued is None:
            return

        while queued < target:
            item = None
            for _ in range(12):
                candidate = self.choose_default()
                if candidate is None:
                    return
                if self._default_key(candidate) not in self.sent_defaults:
                    item = candidate
                    break

            if item is None:
                item = self.choose_default()
                if item is None:
                    return

            try:
                item["default_track"] = True
                item["file_path"] = str(self.ensure_file(item))
                item["play_token"] = uuid.uuid4().hex
                self.push(self.default_source, item)
                self.sent_defaults[self._default_key(item)] = item
                queued += 1
            except Exception as error:
                print(
                    f"[AUTODJ] LIQUIDSOAP: error preparando DEFAULT: {error}",
                    flush=True,
                )
                return

    @staticmethod
    def _parse_metadata_response(response):
        metadata = {}
        for raw_line in response.splitlines():
            line = raw_line.strip()
            if not line or line == "END":
                continue
            match = re.match(r'^([A-Za-z0-9_]+)="(.*)"$', line)
            if not match:
                continue
            key, value = match.groups()
            metadata[key] = value.replace('\\\\"', '"').replace('\\\\\\\\', '\\\\')
        return metadata

    def _on_air_rid(self):
        response = self._command("request.on_air")
        for raw_line in response.splitlines():
            line = raw_line.strip()
            if line and line != "END":
                return line
        return None

    def _request_metadata(self, rid):
        return self._parse_metadata_response(self._command(f"request.metadata {rid}"))

    def _sync_on_air(self):
        """Synchronize AutoDJ state from Liquidsoap's actual on-air RID."""
        rid = self._on_air_rid()
        if not rid:
            return

        metadata = self._request_metadata(rid)
        token = metadata.get("autodj_token") or None
        video_id = metadata.get("video_id") or None
        request_id = metadata.get("request_id") or None
        title = metadata.get("title") or metadata.get("filename") or "Pista desconocida"
        default_track = metadata.get("default_track", "").lower() == "true"

        if rid == self.last_on_air_rid:
            return
        self.last_on_air_rid = rid

        request_item = None
        with self.lock:
            for queued in self.queue:
                if token and queued.get("play_token") == token:
                    request_item = queued
                    break
                if video_id and queued.get("video_id") == video_id:
                    request_item = queued
                    break
                if request_id and queued.get("request_id") == request_id:
                    request_item = queued
                    break

            requested_by = None
            if request_item:
                requested_by = (request_item.get("metadata") or {}).get("requested_by")

            self.state["current"] = {
                "video_id": video_id,
                "metadata": {
                    "video_id": video_id,
                    "title": title,
                    "requested_by": requested_by,
                    "request_id": request_id,
                    "autodj_token": token,
                },
                "default_track": default_track,
                "file_path": request_item.get("file_path") if request_item else metadata.get("filename"),
                "play_token": token,
                "liquidsoap_rid": rid,
            }
            self.state["started_at"] = time.time()
            self.state["status"] = "playing"

            if request_item is not None:
                try:
                    self.queue.remove(request_item)
                    self.save(self.queue_file, list(self.queue))
                except ValueError:
                    request_item = None

        if request_item is not None:
            self.set_request_result(request_item, "played")
            print(f"[AUTODJ] REQUEST: {title} (RID {rid})", flush=True)
        elif default_track:
            for key, item in list(self.sent_defaults.items()):
                if token and item.get("play_token") == token:
                    self.sent_defaults.pop(key, None)
                    break
            with self.lock:
                self.state["last_default_id"] = video_id or metadata.get("filename")
            print(f"[AUTODJ] DEFAULT: {title} (RID {rid})", flush=True)
            self.ensure_defaults(3)
        else:
            print(f"[AUTODJ] ON AIR: {title} (RID {rid})", flush=True)

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
            # Liquidsoap owns playback order, so remove the exact item that
            # started instead of requiring it to be queue[0].
            with self.lock:
                try:
                    self.queue.remove(request_item)
                    self.save(self.queue_file, list(self.queue))
                except ValueError:
                    pass
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
        # Liquidsoap is the source of truth for the track currently on air.
        response = self._command(f"{self.radio_source}.skip")
        if "END" not in response:
            raise RuntimeError(f"Liquidsoap no confirmó skip: {response.strip()}")

    def run(self):
        print(f"[AUTODJ] Liquidsoap controller: {self.host}:{self.port}", flush=True)
        while True:
            try:
                if not self.reconciled_requests and not self._reconcile_requests():
                    time.sleep(1.0)
                    continue
                self._sync_on_air()
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
