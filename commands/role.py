from highrise import BaseBot, User


ROLES = {"mod", "vip", "user"}


async def handle_role(bot: BaseBot, user: User, message: str) -> str:
    if user.id != bot.owner_id and not await bot.is_mod(user.id):
        return "<#FF6666>🛡️ Solo el dueño o los moderadores pueden asignar roles."

    parts = message.split()
    if len(parts) != 3:
        return "<#FFCC66>🛡️ Uso: !role @usuario <mod|vip|user>"

    username = parts[1].lstrip("@")
    role = parts[2].lower()
    if role not in ROLES:
        return "<#FF6666>❌ Rol inválido. Usa: mod, vip o user."

    target_id = await bot.get_user_id(username)
    if target_id == bot.owner_id:
        return "<#FFCC66>👑 El dueño no puede cambiarse de rol."

    try:
        await bot.role_manager.set_role(bot, target_id, role, username)
    except Exception as error:
        print(f"Error asignando el rol {role} a @{username}: {error}")
        return "<#FF6666>⚠️ No se pudo cambiar el rol del usuario."

    await bot.highrise.chat(f"<#66FF99>✅ @{username} ahora tiene el rol {role}.")
    return None


COMMANDS = {"!role": handle_role}
