from highrise import BaseBot, User


async def handle_get_outfit(bot: BaseBot, user: User, message: str = "") -> str | None:
    if user.id != bot.owner_id and not await bot.is_mod(user.id):
        return "<#FF6666>👔 Solo el dueño o los moderadores pueden consultar el vestuario del bot."

    try:
        outfit_response = await bot.highrise.get_my_outfit()
        outfit_items = outfit_response.outfit
    except Exception as error:
        print(f"Error obteniendo el vestuario: {error}")
        return "<#FF6666>⚠️ No se pudo obtener el vestuario del bot."

    if not outfit_items:
        return "<#FFCC66>🧺 El bot no tiene prendas equipadas."

    return "<#66CCFF>👔 Vestuario actual:\n" + "\n".join(
        f"<#FFFFFF>• {item.id}" for item in outfit_items
    )


COMMANDS = {"/getoutfit": handle_get_outfit}
