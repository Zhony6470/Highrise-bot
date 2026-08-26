from highrise import BaseBot, User


async def handle_help(bot: BaseBot, user: User, message: str) -> list[str]:
    return await bot.get_command_help(user.id)


COMMANDS = {"!help": handle_help}