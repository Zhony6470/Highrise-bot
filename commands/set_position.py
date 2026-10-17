from highrise import BaseBot, User
from common.bot_manager import should_handle_for_bot


async def handle_set_position(bot: BaseBot, user: User, message: str) -> str:
    if not await should_handle_for_bot(bot, message):
        return None
    if user.id != bot.owner_id and not bot.role_manager.has_permission(user.id):
        return "<#FF6666>🔒 Necesitas el permiso avanzado para ajustar la posición del bot."

    result = await bot.position_manager_common.set_current_position(user.id)
    if "No pude obtener" in result:
        return result

    position = await bot.get_user_position(user.id)
    if position:
        await bot.highrise.teleport(bot.bot_id, position)
    return result


COMMANDS = {"!set": handle_set_position}
