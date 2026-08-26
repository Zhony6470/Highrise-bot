from json import dump, load
from typing import Literal

from highrise import User


Role = Literal["owner", "mod", "vip", "user"]


class RoleManager:
    def __init__(self, roles_file: str):
        self.roles_file = roles_file
        self.roles = self._load_roles()

    async def get_user_role(self, bot, user: User) -> Role:
        if user.id == bot.owner_id:
            return "owner"

        saved_role = self.roles.get(user.username.lower())
        if saved_role:
            return saved_role

        try:
            privileges = await bot.highrise.get_room_privilege(user.id)
        except Exception as error:
            print(f"Error obteniendo los privilegios de @{user.username}: {error}")
            privileges = None

        if privileges and getattr(privileges, "moderator", False):
            return "mod"
        if user.id in self._legacy_vip_users:
            return "vip"
        return "user"

    async def set_role(
        self, bot, user_id: str | None, role: Role, username: str
    ) -> None:
        username = username.lower()
        if role == "user":
            self.roles.pop(username, None)
        else:
            self.roles[username] = role
        self._save_roles()

        if not user_id:
            return

        if role in ("mod", "user"):
            permissions = await bot.highrise.get_room_privilege(user_id)
            permissions.moderator = role == "mod"
            await bot.highrise.change_room_privilege(user_id, permissions)

    async def apply_saved_role(self, bot, user: User) -> None:
        role = self.roles.get(user.username.lower())
        if role in ("mod", "user"):
            await self.set_role(bot, user.id, role, user.username)

    def _load_roles(self) -> dict[str, Role]:
        try:
            with open(self.roles_file, "r", encoding="utf-8") as file:
                data = load(file)
                self._legacy_vip_users = set(data.get("vip_users", []))
                return {
                    username.lower(): role
                    for username, role in data.get("users", {}).items()
                    if role in ("mod", "vip", "user")
                }
        except (FileNotFoundError, KeyError, TypeError):
            self._legacy_vip_users = set()
            return {}

    def _save_roles(self) -> None:
        with open(self.roles_file, "r+", encoding="utf-8") as file:
            data = load(file)
            data["users"] = self.roles
            file.seek(0)
            dump(data, file)
            file.truncate()


async def get_user_role(bot, user: User) -> Role:
    return await bot.role_manager.get_user_role(bot, user)


async def has_role(bot, user: User, allowed_roles: set[Role]) -> bool:
    return await get_user_role(bot, user) in allowed_roles
