from highrise import BaseBot, User


async def handle_color(bot: BaseBot, user: User, message: str) -> str | None:
    if user.id != bot.owner_id and not await bot.is_mod(user.id):
        return "<#FF6666>🎨 Solo el dueño o los moderadores pueden cambiar el color del vestuario."

    parts = message.split()
    if len(parts) >= 2 and parts[1].startswith("@"):
        parts = [parts[0], *parts[2:]]
    if len(parts) != 3:
        return "<#FFCC66>🎨 Uso: !color @BotUsuario <categoria> <numero_de_paleta>"

    category = parts[1].lower()
    try:
        color_palette = int(parts[2])
    except ValueError:
        return "<#FFCC66>🔢 El número de paleta debe ser un número válido."

    if hasattr(bot, "avatar_manager"):
        return await bot.avatar_manager.change_color(category, color_palette)
    return "<#FF6666>⚠️ Este bot no tiene gestor de avatar habilitado."


COMMANDS = {"!color": handle_color}
