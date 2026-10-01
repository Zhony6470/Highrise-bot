import json
from common.bot_manager import normalize_bot_reference,parse_target_username
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
