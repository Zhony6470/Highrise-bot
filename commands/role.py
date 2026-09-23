from highrise import BaseBot, User
from typing import Optional


ROLES = {"mod", "vip", "designer", "user"}


async def handle_role(bot: BaseBot, user: User, message: str) -> Optional[str]:
    if user.id != bot.owner_id and not await bot.is_mod(user.id):
        return "<#FF6666>🛡️ Solo el dueño o los moderadores pueden asignar roles."

    parts = message.split()
    if len(parts) == 1:
        return await bot.send_saved_roles_to_inbox(user)
    if len(parts) not in {3, 4}:
        return (
            "<#FFCC66>🛡️ Uso: !role o !role @usuario "
            "<mod|vip|designer|delete [mod|vip|designer]>"
        )

    username = parts[1].lstrip("@").strip()
    role = parts[2].lower()
    delete_role = parts[3].lower() if len(parts) == 4 else None

    if not username:
        return "<#FF6666>❌ Usuario inválido."

    if role == "user":
        return "<#FFCC66>🛡️ Para quitar un rol usa: !role @usuario delete [rol]."

    if role not in {"mod", "vip", "designer", "delete"}:
        return "<#FF6666>❌ Rol inválido. Usa: mod, vip, designer o delete."

    if role != "delete" and len(parts) == 4:
        return "<#FFCC66>🛡️ Para asignar un rol usa: !role @usuario <mod|vip|designer>."

    if role == "delete" and delete_role not in {None, "mod", "vip", "designer", "user"}:
        return "<#FF6666>❌ Rol a eliminar inválido. Usa: mod, vip, designer o delete."

    target_id = None
    in_room = False

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

    if target_id:
        try:
            room_users = (await bot.highrise.get_room_users()).content
            in_room = any(room_user.id == target_id for room_user, _ in room_users)
        except Exception as error:
            print(f"[ROLES] Error comprobando presencia de @{username}: {error}")

    try:
        if role == "delete":
            applied = await bot.role_manager.delete_role(
                bot, target_id, username, delete_role
            )
            deleted_text = (
                "todos los roles"
                if delete_role in {None, "user"}
                else f"el rol {delete_role}"
            )

            if not in_room:
                return (
                    f"<#66FF99>🗑️ {deleted_text.capitalize()} eliminado(s) "
                    f"para @{username}. No queda guardado en la base de datos."
                )

            if applied:
                if delete_role in {None, "user"}:
                    message = f"<#66FF99>🗑️ @{username} volvió a ser user."
                else:
                    message = (
                        f"<#66FF99>🗑️ @{username} ya no tiene el rol "
                        f"{delete_role}."
                    )
            else:
                message = (
                    f"<#FFCC66>🗑️ {deleted_text.capitalize()} eliminado(s) "
                    f"de la base de datos para @{username}, pero no pude "
                    "sincronizar el privilegio de sala."
                )
        else:
            applied = await bot.role_manager.set_role(
                bot, target_id, role, username, apply_privilege=in_room
            )
            if in_room and not applied:
                return (
                    f"<#FFCC66>⚠️ @{username} quedó guardado con el rol {role}, "
                    "pero no pude sincronizar los privilegios de sala."
                )

            if in_room:
                roles = bot.role_manager.get_saved_roles(target_id, username)
                message = (
                    f"<#66FF99>✅ @{username} ahora tiene: "
                    f"{', '.join(roles)}."
                )
            else:
                roles = bot.role_manager.get_saved_roles(target_id, username)
                message = (
                    f"<#66FF99>✅ Rol {role} guardado para @{username}. "
                    f"Roles actuales: {', '.join(roles)}. "
                    "Se aplicarán cuando entre a la sala."
                )
    except Exception as error:
        print(f"[ROLES] Error procesando rol {role} para @{username}: {error}")
        return "<#FF6666>⚠️ No se pudo guardar el rol del usuario."

    await bot.highrise.chat(message)
    return None


COMMANDS = {"!role": handle_role}
