import json
from types import SimpleNamespace
from unittest.mock import patch

import services.youtube as youtube_service


def test_search_youtube_falls_back_to_yt_dlp_when_api_key_missing(monkeypatch):
    monkeypatch.setattr(youtube_service, "YOUTUBE_API_KEY", None)

    class FakeCompletedProcess:
        stdout = json.dumps({
            "entries": [{
                "id": "abc12345678",
                "title": "Song title",
                "channel": "Test channel",
                "duration": 123,
            }]
        })

    with patch("services.youtube.subprocess.run", return_value=FakeCompletedProcess()) as mocked_run:
        result = youtube_service.search_youtube("song name")

    assert result == {
        "video_id": "abc12345678",
        "title": "Song title",
        "channel": "Test channel",
        "url": "https://www.youtube.com/watch?v=abc12345678",
        "duration": 123,
    }
    assert mocked_run.called
