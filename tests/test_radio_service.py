import asyncio
import json
from urllib.error import HTTPError, URLError
from unittest.mock import patch

import pytest

import services.radio as radio_service


def test_request_default_playlist_requires_config(monkeypatch):
    monkeypatch.delenv("RADIO_PLAYER_URL", raising=False)
    monkeypatch.delenv("RADIO_PLAYER_TOKEN", raising=False)

    with pytest.raises(radio_service.RadioRequestError, match="radio no está configurada"):
        asyncio.run(radio_service.request_default_playlist())


def test_request_default_playlist_reads_valid_response(monkeypatch):
    monkeypatch.setenv("RADIO_PLAYER_URL", "http://example.com/radio")
    monkeypatch.setenv("RADIO_PLAYER_TOKEN", "secret")

    class FakeResponse:
        def read(self):
            return json.dumps([
                {"video_id": "abc12345678", "title": "Track title"}
            ]).encode("utf-8")

    with patch("services.radio.urlopen", return_value=FakeResponse()) as mocked_urlopen:
        result = asyncio.run(radio_service.request_default_playlist())

    assert result == [{"video_id": "abc12345678", "title": "Track title"}]
    assert mocked_urlopen.called


def test_request_playback_retries_transient_api_failures(monkeypatch):
    monkeypatch.setenv("RADIO_PLAYER_URL", "http://example.com/radio")
    monkeypatch.setenv("RADIO_PLAYER_TOKEN", "secret")

    class FakeResponse:
        status = 202

    calls = {"count": 0}

    def fake_urlopen(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise URLError("temporary")
        return FakeResponse()

    with patch("services.radio.urlopen", side_effect=fake_urlopen):
        asyncio.run(radio_service.request_playback("abc12345678", {"title": "Track"}))

    assert calls["count"] == 2


def test_update_default_playlist_preserves_http_conflict_errors(monkeypatch):
    monkeypatch.setenv("RADIO_PLAYER_URL", "http://example.com/radio")
    monkeypatch.setenv("RADIO_PLAYER_TOKEN", "secret")

    def fake_urlopen(*args, **kwargs):
        raise HTTPError("http://example.com/radio/default-add", 409, "already exists", hdrs=None, fp=None)

    with patch("services.radio.urlopen", side_effect=fake_urlopen):
        with pytest.raises(radio_service.RadioRequestError, match="ya está en la playlist"):
            asyncio.run(radio_service.update_default_playlist({"video_id": "abc12345678", "title": "Track"}))
