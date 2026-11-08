from highrise import BaseBot, User
from common.bot_manager import should_handle_for_bot


async def handle_reset(bot: BaseBot, user: User, message: str) -> str | None:
    if not await should_handle_for_bot(bot, message):
        return None
    if user.id != bot.owner_id and not await bot.is_mod(user.id):
        return "<#FF6666>🔒 Solo el dueño o los moderadores pueden reiniciar el bot."

    if hasattr(bot, "restart_with_message"):
        await bot.restart_with_message()
    else:
        await bot.highrise.chat("<#FF6666>🔄 El bot se reiniciará en un momento...")
        await bot.restart_process()
    return None


COMMANDS = {"!reset": handle_reset}
