import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from commands.role import handle_role
from services.roles import RoleManager


class RoleDeletionTests(unittest.TestCase):
    def make_manager(self, users, usernames):
        data = {"users": users, "usernames": usernames}
        with patch("services.roles.load_json", return_value=data):
            return RoleManager("roles.json")

    def test_delete_offline_user_resolves_id_from_saved_username(self):
        manager = self.make_manager(
            {"user-123": ["mod", "vip"]},
            {"user-123": "TargetUser"},
        )

        deleted = asyncio.run(
            manager.delete_role(
                None,
                user_id=None,
                username="targetuser",
                role=None,
                apply_privilege=False,
            )
        )

        self.assertTrue(deleted)
        self.assertNotIn("user-123", manager.roles)
        self.assertNotIn("user-123", manager.usernames)

    def test_delete_one_role_keeps_other_roles_for_offline_user(self):
        manager = self.make_manager(
            {"user-123": ["mod", "vip"]},
            {"user-123": "TargetUser"},
        )

        deleted = asyncio.run(
            manager.delete_role(
                None,
                user_id=None,
                username="@TARGETUSER",
                role="vip",
                apply_privilege=False,
            )
        )

        self.assertTrue(deleted)
        self.assertEqual(manager.roles["user-123"], ["mod"])

    def test_unknown_username_does_not_report_a_deletion(self):
        manager = self.make_manager(
            {"user-123": ["mod"]},
            {"user-123": "AnotherUser"},
        )

        deleted = asyncio.run(
            manager.delete_role(
                None,
                user_id=None,
                username="MissingUser",
                role=None,
                apply_privilege=False,
            )
        )

        self.assertFalse(deleted)
        self.assertEqual(manager.roles, {"user-123": ["mod"]})

    def test_role_command_removes_offline_user_by_username(self):
        manager = self.make_manager(
            {"user-123": ["vip"]},
            {"user-123": "TargetUser"},
        )

        class FakeWebAPI:
            async def get_users(self, username):
                return SimpleNamespace(users=[])

        class FakeHighrise:
            async def get_room_users(self):
                return SimpleNamespace(content=[])

        bot = SimpleNamespace(
            owner_id="owner-id",
            role_manager=manager,
            webapi=FakeWebAPI(),
            highrise=FakeHighrise(),
        )
        owner = SimpleNamespace(id="owner-id")

        response = asyncio.run(
            handle_role(bot, owner, "!role @TargetUser delete")
        )

        self.assertIn("eliminado", response)
        self.assertNotIn("user-123", manager.roles)

    def test_role_command_does_not_claim_success_for_unknown_user(self):
        manager = self.make_manager(
            {"user-123": ["vip"]},
            {"user-123": "AnotherUser"},
        )

        class FakeWebAPI:
            async def get_users(self, username):
                return SimpleNamespace(users=[])

        class FakeHighrise:
            async def get_room_users(self):
                return SimpleNamespace(content=[])

        bot = SimpleNamespace(
            owner_id="owner-id",
            role_manager=manager,
            webapi=FakeWebAPI(),
            highrise=FakeHighrise(),
        )
        owner = SimpleNamespace(id="owner-id")

        response = asyncio.run(
            handle_role(bot, owner, "!role @MissingUser delete")
        )

        self.assertIn("No encontré roles guardados", response)
        self.assertEqual(manager.roles, {"user-123": ["vip"]})


if __name__ == "__main__":
    unittest.main()
