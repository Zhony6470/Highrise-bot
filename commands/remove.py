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

    return await bot.avatar_manager.remove_category(category)


COMMANDS = {"!remove": handle_remove, "/remove": handle_remove}
