import os


ROOM_ID = os.environ.get("ROOM_ID", "")
API_KEY = os.environ.get("API_KEY", "")

ICECAST_SOURCE = os.environ.get("ICECAST_SOURCE", "source")
ICECAST_PASSWORD = os.environ.get("ICECAST_PASSWORD", "hackme")
ICECAST_HOST = os.environ.get("ICECAST_HOST", "localhost")
ICECAST_PORT = os.environ.get("ICECAST_PORT", "8000")
ICECAST_MOUNT = os.environ.get("ICECAST_MOUNT", "/stream")
RADIO_STREAM_URL = os.environ.get(
    "RADIO_STREAM_URL",
    f"http://{ICECAST_HOST}:{ICECAST_PORT}{ICECAST_MOUNT}",
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "data.json")
EMOTES_FILE = os.path.join(BASE_DIR, "emotes.json")
POSITIONS_FILE = os.path.join(BASE_DIR, "posiciones.json")
ROLES_FILE = os.path.join(BASE_DIR, "roles.json")

DEFAULT_DATA = {
    "users": {},
    "bot_position": {"x": 0, "y": 0, "z": 0, "facing": "FrontRight"},
}