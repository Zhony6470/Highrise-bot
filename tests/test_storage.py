import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote
from unittest.mock import patch

from services import storage


class StorageNamespaceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.remote = {}
        self.calls = []
        self.root_patch = patch.object(storage, "ROOT_DIR", self.root)
        self.url_patch = patch.object(storage, "SUPABASE_URL", "https://example.supabase.co")
        self.key_patch = patch.object(storage, "SUPABASE_KEY", "test-key")
        self.root_patch.start()
        self.url_patch.start()
        self.key_patch.start()
        self.request_patch = patch.object(storage, "_supabase_request", self.fake_request)
        self.request_patch.start()

    def tearDown(self):
        self.request_patch.stop()
        self.key_patch.stop()
        self.url_patch.stop()
        self.root_patch.stop()
        self.temp_dir.cleanup()

    def fake_request(self, method, path, payload=None, params=""):
        self.calls.append((method, path, payload, params))
        if method == "GET":
            encoded = params.split("file_name=eq.", 1)[1].split("&", 1)[0]
            key = unquote(encoded)
            if key in self.remote:
                return [{"file_name": key, "content": self.remote[key]}]
            return []
        if method == "POST":
            self.remote[payload["file_name"]] = payload["content"]
            return [{"file_name": payload["file_name"]}]
        raise AssertionError(f"Unexpected method: {method}")

    def test_data_files_have_distinct_namespaced_keys(self):
        zeta = self.root / "bots" / "bot1" / "data" / "data.json"
        fun = self.root / "bots" / "fun" / "data" / "data.json"

        self.assertEqual(storage._storage_key(zeta), "bots/bot1/data/data.json")
        self.assertEqual(storage._storage_key(fun), "bots/fun/data/data.json")
        self.assertNotEqual(storage._storage_key(zeta), storage._storage_key(fun))

    def test_legacy_shared_record_is_copied_to_each_namespace_without_deletion(self):
        zeta = self.root / "bots" / "bot1" / "data" / "data.json"
        fun = self.root / "bots" / "fun" / "data" / "data.json"
        fun.parent.mkdir(parents=True)
        fun.write_text(
            '{"bot_position_botjuegos":{"x":4,"y":0,"z":8,"facing":"FrontLeft"}}',
            encoding="utf-8",
        )
        legacy = {
            "users": {"legacy-user": {"total_tips": 12}},
            "bot_position": {"x":1,"y":0,"z":2,"facing":"FrontRight"},
        }
        self.remote["data.json"] = legacy

        zeta_data = storage.load_json(zeta)
        fun_data = storage.load_json(fun)

        self.assertIn("legacy-user", zeta_data["users"])
        self.assertIn("legacy-user", fun_data["users"])
        self.assertIn("bot_position_botjuegos", fun_data)
        self.assertEqual(
            self.remote["bots/bot1/data/data.json"]["users"]["legacy-user"]["total_tips"],
            12,
        )
        self.assertEqual(
            self.remote["bots/fun/data/data.json"]["users"]["legacy-user"]["total_tips"],
            12,
        )
        self.assertEqual(self.remote["data.json"], legacy)

    def test_shared_roles_file_keeps_its_shared_key(self):
        roles = self.root / "roles.json"
        self.assertEqual(storage._storage_key(roles), "roles.json")

    def test_save_writes_namespaced_supabase_record_and_local_mirror(self):
        target = self.root / "bots" / "fun" / "data" / "data.json"
        data = {"users": {"user-1": {"total_tips": 7}}}

        storage.save_json(target, data)

        self.assertEqual(
            self.remote["bots/fun/data/data.json"],
            data,
        )
        self.assertEqual(
            __import__("json").loads(target.read_text(encoding="utf-8")),
            data,
        )

    def test_legacy_positions_key_is_migrated(self):
        target = self.root / "bots" / "bot1" / "data" / "posiciones.json"
        legacy = {"posiciones": {"vip": {"x": 1, "y": 2, "z": 3, "facing": "FrontLeft"}}}
        self.remote["posiciones.json"] = legacy

        loaded = storage.load_json(target)

        self.assertEqual(loaded, legacy)
        self.assertEqual(self.remote["bots/bot1/data/posiciones.json"], legacy)
        self.assertEqual(self.remote["posiciones.json"], legacy)


if __name__ == "__main__":
    unittest.main()
