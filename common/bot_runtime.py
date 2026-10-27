from __future__ import annotations

from highrise import Position


class BotRuntimeMixin:
    """Shared Highrise helpers used by every bot."""

    async def is_mod(self, user_id: str) -> bool:
        if user_id == getattr(self, "owner_id", None):
            return True
        try:
            permissions = await self.highrise.get_room_privilege(user_id)
            return bool(getattr(permissions, "moderator", False) or getattr(permissions, "designer", False))
        except Exception as error:
            print(f"[PERMISSIONS] Error comprobando {user_id}: {error}")
            return False

    async def get_user_position(self, user_id: str) -> Position | None:
        try:
            room_users = await self.highrise.get_room_users()
        except Exception as error:
            print(f"[ROOM] Error obteniendo usuarios: {error}")
            return None
        for user, position in room_users.content:
            if user.id == user_id:
                return position if isinstance(position, Position) else None
        return None

    async def get_user_id(self, username: str) -> str | None:
        target = username.strip().lstrip("@").casefold()
        if not target:
            return None
        try:
            room_users = await self.highrise.get_room_users()
        except Exception as error:
            print(f"[ROOM] Error buscando @{target}: {error}")
            return None
        for user, _ in room_users.content:
            if user.username.casefold() == target:
                return user.id
        return None
