import io

import radio_player


class FakeOutput:
    def __init__(self):
        self.data = bytearray()

    def write(self, chunk):
        if isinstance(chunk, (bytes, bytearray)) and b"boom" in chunk:
            raise BrokenPipeError("Broken pipe")
        self.data.extend(chunk)

    def flush(self):
        pass


class FakeDecoder:
    def __init__(self, payload: bytes):
        self.stdout = io.BytesIO(payload)


def test_stream_track_handles_broken_pipe():
    decoder = FakeDecoder(b"hello")
    output = FakeOutput()

    tail = radio_player.stream_track(decoder.stdout, output, bytearray())

    assert tail == bytearray()


def test_ensure_output_process_recreates_dead_process():
    class DeadProcess:
        def __init__(self):
            self.stdin = io.BytesIO()

        def poll(self):
            return 1

    dead_process = DeadProcess()
    replacement = object()

    original = radio_player.create_output_process
    radio_player.create_output_process = lambda: replacement

    try:
        result = radio_player.ensure_output_process(dead_process)
        assert result is replacement
    finally:
        radio_player.create_output_process = original


def test_output_is_healthy_rejects_dead_process():
    class DeadProcess:
        def __init__(self):
            self.stdin = io.BytesIO()

        def poll(self):
            return 1

    assert radio_player.output_is_healthy(DeadProcess()) is False


def test_skip_guard_rejects_same_track_replay():
    current = {"video_id": "abc123def45", "stream_url": "https://example.com/track.mp3"}
    next_item = {"video_id": "abc123def45", "stream_url": "https://example.com/track.mp3"}

    assert radio_player.is_same_track(current, next_item) is True
    assert radio_player.should_advance_after_skip(current, next_item) is False
