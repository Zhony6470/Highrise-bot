from highrise import BaseBot, User


async def handle_perm(bot: BaseBot, user: User, message: str) -> str:
    if user.id != bot.owner_id:
        return "<#FF6666>🔒 Solo el dueño puede administrar permisos."

    parts = message.split()
    if len(parts) != 2 or not parts[1].startswith("@") or not parts[1][1:].strip():
        return "<#FFCC66>🔐 Uso: !perm @usuario"

    username = parts[1][1:].strip()
    target_id = await bot.get_user_id(username)
    if not target_id:
        try:
            response = await bot.webapi.get_users(username=username)
            matched = next((item for item in response.users if item.username.casefold() == username.casefold()), None)
            if matched:
                target_id = matched.id
                username = matched.username
        except Exception as error:
            print(f"[PERM] Error buscando @{username}: {error}")

    if not target_id:
        return "<#FFCC66>🔎 Usuario no encontrado."
    if target_id == bot.owner_id:
        return "<#FFCC66>👑 El dueño ya tiene todos los permisos."

    bot.role_manager.grant_permission(target_id, username)
    return f"<#66FF99>🔐 Permiso avanzado otorgado a @{username}."


async def handle_rperm(bot: BaseBot, user: User, message: str) -> str:
    if user.id != bot.owner_id:
        return "<#FF6666>🔒 Solo el dueño puede administrar permisos."

    parts = message.split()
    if len(parts) != 2 or not parts[1].startswith("@") or not parts[1][1:].strip():
        return "<#FFCC66>🔐 Uso: !rperm @usuario"

    username = parts[1][1:].strip()
    target_id = await bot.get_user_id(username)
    if not target_id:
        try:
            response = await bot.webapi.get_users(username=username)
            matched = next((item for item in response.users if item.username.casefold() == username.casefold()), None)
            if matched:
                target_id = matched.id
                username = matched.username
        except Exception as error:
            print(f"[RPERM] Error buscando @{username}: {error}")

    if not target_id:
        return "<#FFCC66>🔎 Usuario no encontrado."

    bot.role_manager.revoke_permission(target_id, username)
    return f"<#66FF99>🔓 Permiso avanzado retirado a @{username}."


COMMANDS = {"!perm": handle_perm, "!rperm": handle_rperm}
