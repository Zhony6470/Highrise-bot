import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from commands.role import handle_role
from services.roles import RoleManager


class RoleDeletionTests(unittest.TestCase):
    def test_delete_offline_user_resolves_id_from_saved_username(self):
        users = {"user-123": ["mod", "vip"]}
        usernames = {"user-123": "TargetUser"}
        data = {"users": users, "usernames": usernames}

        with patch("services.roles.load_json", return_value=data), patch(
            "services.roles.save_json"
        ) as save:
            manager = RoleManager("roles.json")
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
        self.assertNotIn("user-123", save.call_args.args[1]["users"])

    def test_delete_one_role_keeps_other_roles_for_offline_user(self):
        data = {
            "users": {"user-123": ["mod", "vip"]},
            "usernames": {"user-123": "TargetUser"},
        }

        with patch("services.roles.load_json", return_value=data), patch(
            "services.roles.save_json"
        ):
            manager = RoleManager("roles.json")
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
        data = {
            "users": {"user-123": ["mod"]},
            "usernames": {"user-123": "AnotherUser"},
        }

        with patch("services.roles.load_json", return_value=data), patch(
            "services.roles.save_json"
        ) as save:
            manager = RoleManager("roles.json")
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
        save.assert_not_called()

    def test_delete_legacy_vip_by_username_persists_removal(self):
        data = {
            "vip_users": ["user-123"],
            "users": {},
            "usernames": {"user-123": "TargetUser"},
        }

        with patch("services.roles.load_json", return_value=data), patch(
            "services.roles.save_json"
        ) as save:
            manager = RoleManager("roles.json")
            deleted = asyncio.run(
                manager.delete_role(
                    None,
                    user_id=None,
                    username="targetuser",
                    role="vip",
                    apply_privilege=False,
                )
            )

        self.assertTrue(deleted)
        self.assertNotIn("user-123", manager._legacy_vip_users)
        self.assertEqual(save.call_args.args[1]["vip_users"], [])

    def test_role_command_removes_offline_user_by_username(self):
        data = {
            "users": {"user-123": ["vip"]},
            "usernames": {"user-123": "TargetUser"},
        }

        class FakeWebAPI:
            async def get_users(self, username):
                return SimpleNamespace(users=[])

        class FakeHighrise:
            async def get_room_users(self):
                return SimpleNamespace(content=[])

        bot = SimpleNamespace(
            owner_id="owner-id",
            role_manager=None,
            webapi=FakeWebAPI(),
            highrise=FakeHighrise(),
        )
        owner = SimpleNamespace(id="owner-id")

        with patch("services.roles.load_json", return_value=data), patch(
            "services.roles.save_json"
        ):
            bot.role_manager = RoleManager("roles.json")
            response = asyncio.run(
                handle_role(bot, owner, "!role @TargetUser delete")
            )

        self.assertIn("eliminado", response)
        self.assertNotIn("user-123", bot.role_manager.roles)

    def test_role_command_does_not_claim_success_for_unknown_user(self):
        data = {
            "users": {"user-123": ["vip"]},
            "usernames": {"user-123": "AnotherUser"},
        }

        class FakeWebAPI:
            async def get_users(self, username):
                return SimpleNamespace(users=[])

        class FakeHighrise:
            async def get_room_users(self):
                return SimpleNamespace(content=[])

        bot = SimpleNamespace(
            owner_id="owner-id",
            role_manager=None,
            webapi=FakeWebAPI(),
            highrise=FakeHighrise(),
        )
        owner = SimpleNamespace(id="owner-id")

        with patch("services.roles.load_json", return_value=data), patch(
            "services.roles.save_json"
        ):
            bot.role_manager = RoleManager("roles.json")
            response = asyncio.run(
                handle_role(bot, owner, "!role @MissingUser delete")
            )

        self.assertIn("No encontré roles guardados", response)
        self.assertEqual(bot.role_manager.roles, {"user-123": ["vip"]})


if __name__ == "__main__":
    unittest.main()
