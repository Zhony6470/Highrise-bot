from services.storage import load_json, save_json

PERMISSION = "staff_advanced"


def has_permission(bot, user_id: str) -> bool:
    return bot.role_manager.has_permission(user_id)


async def require_permission(bot, user_id: str) -> bool:
    if user_id == bot.owner_id:
        return True
    return has_permission(bot, user_id)
