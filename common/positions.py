from __future__ import annotations

from highrise import Position


class PositionManagerCommon:
    """Gestión común de posición por bot."""

    def __init__(self, bot, data_file: str):
        self.bot = bot
        self.data_file = data_file

    def _key(self) -> str:
        bot_name = getattr(self.bot, "bot_username", "default")
        return f"bot_position_{str(bot_name).lower()}"

    def load_state(self):
        try:
            from services.storage import load_json
            return load_json(self.data_file)
        except Exception:
            return {}

    def save_state(self, data):
        from services.storage import save_json
        save_json(self.data_file, data)

    def save_position(self, position: Position) -> None:
        data = self.load_state()
        data[self._key()] = {"x": position.x, "y": position.y, "z": position.z, "facing": position.facing}
        self.save_state(data)

    def get_saved_position(self) -> Position | None:
        data = self.load_state()
        pos = data.get(self._key()) or data.get("bot_position")
        if not pos:
            return None
        if self._key() not in data and "bot_position" in data:
            data[self._key()] = pos
            self.save_state(data)
        return Position(pos["x"], pos["y"], pos["z"], pos["facing"])

    async def set_current_position(self, user_id: str) -> str:
        pos = await self.bot.get_user_position(user_id)
        if not pos:
            return "<#FF6666>📍 No pude obtener la posición actual."
        self.save_position(pos)
        return "<#66FF99>📍 Posición del bot guardada correctamente."

    async def return_home(self) -> str:
        pos = self.get_saved_position()
        if not pos:
            return "<#FFCC66>📍 No hay posición guardada para este bot."
        await self.bot.highrise.teleport(self.bot.bot_id, pos)
        return "<#66FF99>🏠 El bot volvió a su posición guardada."
