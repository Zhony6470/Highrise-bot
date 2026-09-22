from highrise import BaseBot, User
from typing import Optional


ROLES = {"mod", "vip", "designer", "user"}


async def handle_role(bot: BaseBot, user: User, message: str) -> Optional[str]:
    if user.id != bot.owner_id and not await bot.is_mod(user.id):
        return "<#FF6666>🛡️ Solo el dueño o los moderadores pueden asignar roles."

    parts = message.split()
    if len(parts) == 1:
        return await bot.send_saved_roles_to_inbox(user)
    if len(parts) != 3:
        return "<#FFCC66>🛡️ Uso: !role o !role @usuario <mod|vip|designer|user>"

    username = parts[1].lstrip("@").strip()
    role = parts[2].lower()
    if not username:
        return "<#FF6666>❌ Usuario inválido."
    if role not in ROLES:
        return "<#FF6666>❌ Rol inválido. Usa: mod, vip, designer o user."

    target_id = None

    # Primero buscamos por nombre en la Web API para que funcione
    # aunque el usuario no esté actualmente en la sala.
    try:
        users_response = await bot.webapi.get_users(username=username)
        matched_user = next(
            (
                public_user
                for public_user in users_response.users
                if public_user.username.casefold() == username.casefold()
            ),
            None,
        )
        if matched_user is not None:
            target_id = matched_user.id
            username = matched_user.username
    except Exception as error:
        print(f"[ROLES] Error buscando @{username} en Web API: {error}")

    # Fallback para usuarios que sí están en la sala.
    if target_id is None:
        try:
            room_users = (await bot.highrise.get_room_users()).content
            room_user = next(
                (
                    room_user
                    for room_user, _ in room_users
                    if room_user.username.casefold() == username.casefold()
                ),
                None,
            )
            if room_user is not None:
                target_id = room_user.id
                username = room_user.username
        except Exception as error:
            print(f"[ROLES] Error buscando @{username} en la sala: {error}")

    if target_id == bot.owner_id:
        return "<#FFCC66>👑 El dueño no puede cambiarse de rol."

    try:
        # Aunque no tengamos el ID todavía, RoleManager conserva el rol
        # por username y lo migra al ID cuando el usuario entre a la sala.
        await bot.role_manager.set_role(bot, target_id, role, username)
    except Exception as error:
        print(f"[ROLES] Error asignando el rol {role} a @{username}: {error}")
        return "<#FF6666>⚠️ No se pudo guardar el rol del usuario."

    if target_id:
        message = f"<#66FF99>✅ @{username} ahora tiene el rol {role}."
    else:
        message = (
            f"<#66FF99>✅ Rol {role} guardado para @{username}. "
            "Se aplicará cuando entre a la sala."
        )
    await bot.highrise.chat(message)
    return None


COMMANDS = {"!role": handle_role}
