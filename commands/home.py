from highrise import BaseBot, User
from common.bot_manager import should_handle_for_bot


async def handle_home(bot: BaseBot, user: User, message: str) -> str:
    if not await should_handle_for_bot(bot, message):
        return None
    if user.id != bot.owner_id and not await bot.is_mod(user.id):
        return "<#FF6666>🔒 Solo el dueño o los moderadores pueden usar este comando."
    return await bot.position_manager_common.return_home()


COMMANDS = {"!home": handle_home}
