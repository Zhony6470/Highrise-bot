from highrise import BaseBot, User


async def handle_get_outfit(bot: BaseBot, user: User, message: str = "") -> str | None:
    if user.id != bot.owner_id and not await bot.is_mod(user.id):
        return "<#FF6666>👔 Solo el dueño o los moderadores pueden consultar el vestuario del bot."

    if message.strip().split() and message.strip().split()[1:2] and message.strip().split()[1].startswith("@"):
        message = " ".join(message.strip().split()[2:])

    return await bot.avatar_manager.get_outfit_summary()


COMMANDS = {"!getoutfit": handle_get_outfit, "/getoutfit": handle_get_outfit}
