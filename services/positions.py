from highrise import Position, User
from services.roles import has_role
from services.storage import load_json, save_json


class PositionManager:
    def __init__(self, positions_file: str, data_file: str):
        self.positions_file = positions_file
        self.data_file = data_file

    async def save_named_position(self, bot, user_id: str, position_name: str, access: str) -> str:
        position = await bot.get_user_position(user_id)
        if not position:
            return "<#FF6666>📍 No pude obtener tu posición actual."

        data = load_json(self.positions_file)
        data.setdefault("posiciones", {})[position_name.lower()] = {
            "x": position.x,
            "y": position.y,
            "z": position.z,
            "facing": position.facing,
            "access": access,
        }
        save_json(self.positions_file, data)
        return f"<#66FF99>📍 Posición '{position_name.lower()}' guardada correctamente."

    def get_named_position_data(self, position_name: str) -> dict | None:
        return load_json(self.positions_file).get("posiciones", {}).get(position_name.lower())

    def delete_named_position(self, position_name: str) -> str:
        position_name = position_name.lower()
        data = load_json(self.positions_file)
        positions = data.setdefault("posiciones", {})
        if position_name not in positions:
            return f"<#FFCC66>🔎 No existe una posición guardada con el nombre '{position_name}'."
        del positions[position_name]
        save_json(self.positions_file, data)
        return f"<#66FF99>🗑️ Posición '{position_name}' eliminada correctamente."

    def position_from_data(self, position_data: dict) -> Position:
        return Position(
            position_data["x"], position_data["y"], position_data["z"], position_data["facing"]
        )

    async def can_use_private_position(self, bot, user: User) -> bool:
        return await has_role(bot, user, {"owner", "mod", "vip"})
