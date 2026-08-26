from json import dump, load

from highrise import Position, User
from services.roles import has_role


class PositionManager:
    def __init__(self, positions_file: str, data_file: str):
        self.positions_file = positions_file
        self.data_file = data_file

    async def save_named_position(self, bot, user_id: str, position_name: str, access: str) -> str:
        position = await bot.get_user_position(user_id)
        if not position:
            return "<#FF6666>📍 No pude obtener tu posición actual."

        with open(self.positions_file, "r", encoding="utf-8") as file:
            data = load(file)
        data.setdefault("posiciones", {})[position_name.lower()] = {
            "x": position.x,
            "y": position.y,
            "z": position.z,
            "facing": position.facing,
            "access": access,
        }
        with open(self.positions_file, "w", encoding="utf-8") as file:
            dump(data, file, indent=4)
        return f"<#66FF99>📍 Posición '{position_name.lower()}' guardada correctamente."

    def get_named_position_data(self, position_name: str) -> dict | None:
        with open(self.positions_file, "r", encoding="utf-8") as file:
            return load(file).get("posiciones", {}).get(position_name.lower())

    def delete_named_position(self, position_name: str) -> str:
        position_name = position_name.lower()
        with open(self.positions_file, "r", encoding="utf-8") as file:
            data = load(file)
        positions = data.setdefault("posiciones", {})
        if position_name not in positions:
            return f"<#FFCC66>🔎 No existe una posición guardada con el nombre '{position_name}'."
        del positions[position_name]
        with open(self.positions_file, "w", encoding="utf-8") as file:
            dump(data, file, indent=4)
        return f"<#66FF99>🗑️ Posición '{position_name}' eliminada correctamente."

    def position_from_data(self, position_data: dict) -> Position:
        return Position(
            position_data["x"], position_data["y"], position_data["z"], position_data["facing"]
        )

    async def can_use_private_position(self, bot, user: User) -> bool:
        return await has_role(bot, user, {"owner", "mod", "vip"})

    def save_bot_position(self, position: Position) -> None:
        with open(self.data_file, "r+", encoding="utf-8") as file:
            data = load(file)
            data["bot_position"] = {
                "x": position.x, "y": position.y, "z": position.z, "facing": position.facing
            }
            file.seek(0)
            dump(data, file)
            file.truncate()

    def get_bot_position(self) -> Position:
        with open(self.data_file, "r", encoding="utf-8") as file:
            position = load(file)["bot_position"]
        return Position(position["x"], position["y"], position["z"], position["facing"])

    async def set_bot_position(self, bot, user_id: str) -> str:
        position = await bot.get_user_position(user_id)
        if not position:
            return "No se pudo actualizar la posición del bot."

        self.save_bot_position(position)
        temporary_position = Position(position.x, position.y + 0.0000001, position.z, facing=position.facing)
        await bot.highrise.teleport(bot.bot_id, temporary_position)
        await bot.highrise.teleport(bot.bot_id, position)
        await bot.highrise.walk_to(position)
        return "Posición del bot actualizada."