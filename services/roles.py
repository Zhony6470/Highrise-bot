from __future__ import annotations

from typing import Literal
from highrise import User

from services.storage import load_json, save_json


Role = Literal["owner", "mod", "vip", "designer", "user"]


class RoleManager:
    """Roles persistidos por ID; si aún no hay ID, se guardan temporalmente por username."""

    def __init__(self, roles_file):
        self.roles_file = roles_file
        self.usernames = {}
        self.roles = {}
        self._legacy_vip_users = set()
        self._load_roles()

    async def get_user_role(self, bot, user: User) -> Role:
        if user.id == bot.owner_id:
            return "owner"

        username_key = user.username.casefold()
        saved = self.roles.get(user.id) or self.roles.get(username_key)

        # Si el rol estaba guardado por username, lo migramos al ID estable.
        if saved and user.id not in self.roles and username_key in self.roles:
            self.roles[user.id] = saved
            self.roles.pop(username_key, None)
            self.usernames[user.id] = user.username
            self._save_roles()

        if saved in {"mod", "vip", "designer"}:
            return saved

        try:
            privilege = await bot.highrise.get_room_privilege(user.id)
        except Exception as error:
            print(f"[ROLES] privilegios @{user.username}: {error}")
            privilege = None

        if privilege and getattr(privilege, "moderator", False):
            return "mod"
        if privilege and getattr(privilege, "designer", False):
            return "designer"
        if user.id in self._legacy_vip_users or saved == "vip":
            return "vip"

        return "user"

    async def set_role(self, bot, user_id, role: Role, username: str = ""):
        username_key = username.strip().lstrip("@").casefold()

        if user_id:
            key = user_id
            if role == "user":
                self.roles.pop(key, None)
                self.usernames.pop(key, None)
            else:
                self.roles[key] = role
                if username:
                    self.usernames[key] = username
        elif username_key:
            # Permite asignar el rol aunque el usuario no esté en la sala.
            # Cuando entre, get_user_role() migrará esta entrada a su ID.
            if role == "user":
                self.roles.pop(username_key, None)
            else:
                self.roles[username_key] = role
            self.usernames.pop(username_key, None)
        else:
            return

        # El guardado persistente ocurre antes de intentar modificar
        # privilegios de sala. Así el rol no se pierde si el usuario está fuera.
        self._save_roles()

        if not user_id:
            return

        try:
            privilege = await bot.highrise.get_room_privilege(user_id)
            privilege.moderator = role == "mod"
            privilege.designer = role == "designer"
            await bot.highrise.set_room_privilege(user_id, privilege)
        except Exception as error:
            print(
                f"[ROLES] No se pudo aplicar privilegio de sala a "
                f"@{username or user_id}: {error}"
            )
            # El rol persistente ya quedó guardado. Se aplicará al entrar.

    async def apply_saved_role(self, bot, user):
        role = self.roles.get(user.id) or self.roles.get(user.username.casefold())
        if role in {"mod", "vip", "designer"}:
            await self.set_role(bot, user.id, role, user.username)

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
            for key, role in raw.items():
                if role in {"mod", "vip", "designer", "user"}:
                    self.roles[str(key)] = role

    def _save_roles(self):
        data = load_json(self.roles_file, default={})
        data = data if isinstance(data, dict) else {}
        data["users"] = self.roles
        data["usernames"] = self.usernames
        save_json(self.roles_file, data)


async def get_user_role(bot, user):
    return await bot.role_manager.get_user_role(bot, user)


async def has_role(bot, user, allowed_roles):
    return await get_user_role(bot, user) in allowed_roles
