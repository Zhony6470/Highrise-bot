from highrise import BaseBot, User


async def handle_userinfo(bot: BaseBot, user: User, message: str) -> str:
    parts = message.split()
    if len(parts) == 1:
        user_id = user.id
    elif len(parts) == 2:
        username = parts[1].lstrip("@")
        if not username:
            return "<#FFCC66>👤 Debes indicar un usuario válido."

        user_id = None
        matched_user = None
        try:
            users_response = await bot.webapi.get_users(username=username)
            matched_user = next(
                (public_user for public_user in users_response.users
                 if public_user.username.lower() == username.lower()),
                None,
            )
        except Exception as error:
            print(f"Error buscando el usuario en Web API: {error}")

        if matched_user is None:
            try:
                room_users = (await bot.highrise.get_room_users()).content
                room_user = next(
                    (room_user for room_user, _ in room_users
                     if room_user.username.lower() == username.lower()),
                    None,
                )
                if room_user is not None:
                    user_id = room_user.id
            except Exception as error:
                print(f"Error buscando el usuario en la sala: {error}")

        if matched_user is None and user_id is None:
            return "<#FFCC66>🔎 Usuario no encontrado."
        if matched_user is not None:
            user_id = matched_user.id
    else:
        return "<#FFCC66>👤 Uso: !userinfo o !userinfo @usuario"

    try:
        user_response = await bot.webapi.get_user(user_id)
        user_data = user_response.user
    except Exception as error:
        print(f"Error obteniendo el perfil {user_id} en Web API: {error}")
        return "<#FF6666>⚠️ No se pudo obtener el perfil completo de ese usuario."

    joined_at = user_data.joined_at.strftime("%d/%m/%Y %H:%M:%S")
    return (
        f"<#66CCFF>👤 Perfil de {user_data.username}\n"
        f"<#FFFFFF>👥 Seguidores: {user_data.num_followers}\n"
        f"<#FFFFFF>🤝 Amigos: {user_data.num_friends}\n"
        f"<#FFFFFF>💫 Siguiendo: {user_data.num_following}\n"
        f"<#FFFFFF>📅 Se unió: {joined_at}"
    )


COMMANDS = {"!userinfo": handle_userinfo}
