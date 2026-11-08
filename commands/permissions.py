from highrise import BaseBot, User


async def handle_perm(bot: BaseBot, user: User, message: str) -> str:
    if user.id != bot.owner_id:
        return "<#FF6666>🔒 Solo el dueño puede administrar permisos."

    parts = message.split()

    # !perm sin usuario: enviar por privado la lista de usuarios
    # que tienen permiso avanzado.
    if len(parts) == 1:
        permissions = getattr(bot.role_manager, "permissions", {}) or {}

        if not permissions:
            content = "🔐 No hay usuarios con permiso avanzado."
        else:
            lines = ["🔐 Usuarios con permiso avanzado:"]
            for user_id, data in sorted(permissions.items(), key=lambda item: str(item[1].get("username", "")).casefold() if isinstance(item[1], dict) else ""):
                username = data.get("username", "") if isinstance(data, dict) else ""
                username = username.strip().lstrip("@")
                display_name = f"@{username}" if username else f"ID: {user_id}"
                lines.append(f"👤 {display_name}")
            lines.append("")
            lines.append(f"Total: {len(permissions)}")
            content = "\n".join(lines)

        try:
            conversations = await bot.highrise.get_conversations()
            conversation = next(
                (
                    item for item in conversations.conversations
                    if item.member_ids and user.id in item.member_ids
                ),
                None,
            )

            if conversation:
                result = await bot.highrise.send_message(conversation.id, content)
                if result is None:
                    return "<#66FF99>📨 Te envié la lista de permisos avanzados por mensaje privado."
                print(f"[PERM] Error enviando lista de permisos: {result}")
            else:
                result = await bot.highrise.send_message_bulk([user.id], content)
                if result is None:
                    return "<#66FF99>📨 Te envié la lista de permisos avanzados por mensaje privado."
                print(f"[PERM] No se pudo iniciar la conversación privada: {result}")
        except Exception as error:
            print(f"[PERM] Error enviando lista a la bandeja: {error}")

        return "<#FFCC66>📨 No pude enviar la lista a tu bandeja. Escríbeme primero por mensaje privado y vuelve a usar !perm."

    if len(parts) != 2 or not parts[1].startswith("@") or not parts[1][1:].strip():
        return "<#FFCC66>🔐 Uso: !perm o !perm @usuario"

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
