from highrise import BaseBot, User


async def handle_color(bot: BaseBot, user: User, message: str) -> str | None:
    if user.id != bot.owner_id and not await bot.is_mod(user.id):
        return "<#FF6666>🎨 Solo el dueño o los moderadores pueden cambiar el color del vestuario."

    parts = message.split()
    if len(parts) != 3:
        return "<#FFCC66>🎨 Uso: !color <categoria> <numero_de_paleta>"

    category = parts[1].lower()
    try:
        color_palette = int(parts[2])
    except ValueError:
        return "<#FFCC66>🔢 El número de paleta debe ser un número válido."

    try:
        outfit = (await bot.highrise.get_my_outfit()).outfit
        found_item = False

        for outfit_item in outfit:
            item_category = outfit_item.id.split("-", 1)[0].lower()
            if item_category == category:
                outfit_item.active_palette = color_palette
                found_item = True

        if not found_item:
            return f"<#FFCC66>👕 El bot no usa ningún artículo de la categoría '{category}'."

        result = await bot.highrise.set_outfit(outfit)
        if result is not None:
            print(f"Error de Highrise cambiando el color: {result}")
            return "<#FF6666>⚠️ No se pudo cambiar el color del vestuario."
        return f"<#66FF99>✨ Color de '{category}' actualizado correctamente."
    except Exception as error:
        print(f"Error cambiando el color del vestuario: {error}")
        return "<#FF6666>⚠️ No se pudo cambiar el color del vestuario."


COMMANDS = {"!color": handle_color}
