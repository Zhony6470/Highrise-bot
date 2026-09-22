from __future__ import annotations

from typing import Literal
from highrise import User

from services.storage import load_json, save_json


Role = Literal["owner", "mod", "vip", "designer", "user"]
ASSIGNABLE_ROLES = {"mod", "vip", "designer"}
STORED_ROLES = ASSIGNABLE_ROLES


class RoleManager:
    """Roles persistidos por ID; un usuario puede tener varios roles a la vez."""

    def __init__(self, roles_file):
        self.roles_file = roles_file
        self.usernames = {}
        self.roles = {}
        self._legacy_vip_users = set()
        self._load_roles()

    @staticmethod
    def _normalize_roles(value) -> list[str]:
        if isinstance(value, str):
            values = [value]
        elif isinstance(value, (list, tuple, set)):
            values = list(value)
        else:
            values = []

        result = []
        for role in values:
            role = str(role).strip().lower()
            if role in STORED_ROLES and role not in result:
                result.append(role)
        return result

    def get_saved_roles(self, user_id: str = "", username: str = "") -> list[str]:
        username_key = username.strip().lstrip("@").casefold()
        value = self.roles.get(user_id) if user_id else None
        if value is None and username_key:
            value = self.roles.get(username_key)
        return self._normalize_roles(value)

    async def get_user_roles(self, bot, user: User) -> set[str]:
        if user.id == bot.owner_id:
            return {"owner"}

        saved = self.get_saved_roles(user.id, user.username)
        username_key = user.username.casefold()

        # Si el rol estaba guardado por username, lo migramos al ID estable.
        if user.id not in self.roles and username_key in self.roles:
            self.roles[user.id] = saved
            self.roles.pop(username_key, None)
            self.usernames[user.id] = user.username
            self._save_roles()

        if saved:
            return set(saved)

        try:
            privilege = await bot.highrise.get_room_privilege(user.id)
        except Exception as error:
            print(f"[ROLES] privilegios @{user.username}: {error}")
            privilege = None

        result = set()
        if privilege and getattr(privilege, "moderator", False):
            result.add("mod")
        if privilege and getattr(privilege, "designer", False):
            result.add("designer")
        if user.id in self._legacy_vip_users:
            result.add("vip")
        return result

    async def get_user_role(self, bot, user: User) -> Role:
        roles = await self.get_user_roles(bot, user)
        if "owner" in roles:
            return "owner"
        if "mod" in roles:
            return "mod"
        if "designer" in roles:
            return "designer"
        if "vip" in roles:
            return "vip"
        return "user"

    async def _apply_room_privileges(self, bot, user_id: str, roles: set[str]) -> bool:
        if not user_id:
            return True

        try:
            privilege = await bot.highrise.get_room_privilege(user_id)
            privilege.moderator = "mod" in roles
            privilege.designer = "designer" in roles
            await bot.highrise.change_room_privilege(user_id, privilege)
            return True
        except Exception as error:
            print(
                f"[ROLES] No se pudo sincronizar privilegios de sala "
                f"para @{user_id}: {error}"
            )
            return False

    async def set_role(
        self,
        bot,
        user_id,
        role: Role,
        username: str = "",
        apply_privilege: bool = True,
    ):
        username_key = username.strip().lstrip("@").casefold()
        if role not in ASSIGNABLE_ROLES:
            return False

        if user_id:
            key = user_id
        elif username_key:
            key = username_key
        else:
            return False

        current = self.get_saved_roles(user_id, username)
        if role not in current:
            current.append(role)
        self.roles[key] = current

        if username and user_id:
            self.usernames[key] = username
        elif not user_id:
            self.usernames.pop(key, None)

        self._save_roles()

        if not user_id or not apply_privilege:
            return True

        return await self._apply_room_privileges(bot, user_id, set(current))

    async def delete_role(
        self,
        bot,
        user_id,
        username: str = "",
        role: str | None = None,
    ):
        """Quita un rol concreto o todos los roles si role es None."""
        username_key = username.strip().lstrip("@").casefold()
        key = user_id or username_key
        if not key:
            return False

        current = self.get_saved_roles(user_id, username)

        if role is None or role == "user":
            remaining = []
        else:
            remaining = [item for item in current if item != role]

        if remaining:
            self.roles[key] = remaining
        else:
            self.roles.pop(key, None)
            self.usernames.pop(key, None)

        self._legacy_vip_users.discard(user_id)
        self._legacy_vip_users.discard(username_key)
        self._save_roles()

        if not user_id:
            return True

        return await self._apply_room_privileges(bot, user_id, set(remaining))

    async def apply_saved_role(self, bot, user):
        roles = set(self.get_saved_roles(user.id, user.username))
        if roles:
            await self._apply_room_privileges(bot, user.id, roles)

    def _load_roles(self):
        data = load_json(self.roles_file, default={})
        if not isinstance(data, dict):
            data = {}

        self._legacy_vip_users = set(data.get("vip_users", []))
        self.usernames = {
            str(key): str(value)
            for key, value in (data.get("usernames", {}) or {}).items()
        }

        raw = data.get("users", {})
        if isinstance(raw, dict):
            for key, value in raw.items():
                normalized = self._normalize_roles(value)
                if normalized:
                    self.roles[str(key)] = normalized

    def _save_roles(self):
        data = load_json(self.roles_file, default={})
        data = data if isinstance(data, dict) else {}
        data["users"] = self.roles
        data["usernames"] = self.usernames
        save_json(self.roles_file, data)


async def get_user_role(bot, user):
    return await bot.role_manager.get_user_role(bot, user)


async def get_user_roles(bot, user):
    return await bot.role_manager.get_user_roles(bot, user)


async def has_role(bot, user, allowed_roles):
    roles = await get_user_roles(bot, user)
    return bool(roles.intersection(set(allowed_roles)))
