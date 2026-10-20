import json
from common.bot_manager import normalize_bot_reference,parse_target_username
from common.bot_filter import is_known_bot
from services.emotes import EmotesManager
from services.roles import RoleManager

def test_bot_reference():
    assert normalize_bot_reference(" @Zeta_Bot ")=="zeta_bot"
    assert parse_target_username("!emote @Zeta_Bot dance")=="zeta_bot"
def test_emotes():
    m=EmotesManager([{"emote":"e1","command":"Scuba Dance"}])
    assert m.get_by_name("scuba dance")["emote"]=="e1"
    assert m.get_by_index(0)["command"]=="Scuba Dance"
def test_roles_ids(tmp_path):
    p=tmp_path/"roles.json"; p.write_text(json.dumps({"users":{"user-123":"mod"}}))
    assert RoleManager(str(p)).roles["user-123"]=="mod"


def test_known_bot_filter(monkeypatch):
    monkeypatch.delenv("HIGHRISE_BOT_IDS", raising=False)
    monkeypatch.delenv("HIGHRISE_BOT_USERNAMES", raising=False)
    bot = type("Bot", (), {"bot_id": "own-id", "bot_username": "BotJuegos"})()
    assert is_known_bot(bot, "own-id", "someone")
    assert is_known_bot(bot, "other-id", "Zeta_Bot")
    assert is_known_bot(bot, "other-id", "Dj.Z")
    assert is_known_bot(bot, "other-id", "BotJuegos")
    assert not is_known_bot(bot, "player-id", "RealPlayer")


def test_configured_external_bot_filter(monkeypatch):
    monkeypatch.setenv("HIGHRISE_BOT_IDS", "bot-123, bot-456")
    monkeypatch.setenv("HIGHRISE_BOT_USERNAMES", "SomeOtherBot, AnotherBot")
    bot = type("Bot", (), {"bot_id": "own-id", "bot_username": "BotJuegos"})()
    assert is_known_bot(bot, "bot-123", "unknown")
    assert is_known_bot(bot, "unknown-id", "SomeOtherBot")
