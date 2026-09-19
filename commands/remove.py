from highrise import BaseBot, User


CATEGORIES = {
    "aura",
    "bag",
    "blush",
    "body",
    "dress",
    "earrings",
    "emote",
    "eye",
    "eyebrow",
    "fishing_rod",
    "freckle",
    "fullsuit",
    "glasses",
    "gloves",
    "hair_back",
    "hair_front",
    "handbag",
    "hat",
    "jacket",
    "lashes",
    "mole",
    "mouth",
    "necklace",
    "nose",
    "rod",
    "shirt",
    "shoes",
    "shorts",
    "skirt",
    "sock",
    "tattoo",
    "watch",
}


async def handle_remove(bot: BaseBot, user: User, message: str) -> str:
    if user.id != bot.owner_id and not await bot.is_mod(user.id):
        return "<#FF6666>🧥 Solo el dueño o los moderadores pueden modificar el vestuario."

    parts = message.split()
    if len(parts) >= 2 and parts[1].startswith("@"):
        parts = [parts[0], *parts[2:]]
    if len(parts) != 2:
        return "<#FFCC66>🧥 Uso: !remove @BotUsuario <categoria>"

    category = parts[1].lower()
    if category not in CATEGORIES:
        return "<#FF6666>❌ Categoría inválida."

    if hasattr(bot, "avatar_manager"):
        return await bot.avatar_manager.remove_category(category)

    try:
        outfit = (await bot.highrise.get_my_outfit()).outfit
        filtered_outfit = [
            item
            for item in outfit
            if item.id.split("-", 1)[0].lower() != category
        ]

        if len(filtered_outfit) == len(outfit):
            return f"<#FFCC66>👕 El bot no usa ninguna prenda de la categoría '{category}'."

        result = await bot.highrise.set_outfit(filtered_outfit)
        if result is not None:
            print(f"Error de Highrise eliminando la categoría '{category}': {result}")
            return "<#FF6666>⚠️ No se pudo modificar el vestuario."
        return f"<#66FF99>✨ Categoría '{category}' eliminada correctamente."
    except Exception as error:
        print(f"Error eliminando la categoría '{category}': {error}")
        return "<#FF6666>⚠️ No se pudo modificar el vestuario."


COMMANDS = {"!remove": handle_remove, "/remove": handle_remove}
