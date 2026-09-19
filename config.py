import os


ROOM_ID = os.environ.get("ROOM_ID", "")
API_KEY = os.environ.get("API_KEY", "")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "bots", "bot1", "data", "data.json")
EMOTES_FILE = os.path.join(BASE_DIR, "common", "emotes.json")
POSITIONS_FILE = os.path.join(BASE_DIR, "bots", "bot1", "data", "posiciones.json")
ROLES_FILE = os.path.join(BASE_DIR, "roles.json")

DEFAULT_DATA = {
    "users": {},
    "bot_position": {"x": 0, "y": 0, "z": 0, "facing": "FrontRight"},
}