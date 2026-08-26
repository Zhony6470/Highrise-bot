import asyncio


async def handle_owner_command(bot, command: str, user_id: str) -> str | None:
    if command == "!home":
        try:
            saved_position = bot.position_manager.get_bot_position()
            await bot.highrise.teleport(bot.bot_id, saved_position)
            return "<#66FF99>🏠 El bot volvió a su última posición guardada."
        except Exception as error:
            print(f"Error al volver a la posición guardada: {error}")
            return "<#FF6666>⚠️ No se pudo recuperar la posición guardada."

    if command == "!randomall":
        room_users = await bot.highrise.get_room_users()
        users_started = 0
        for room_user, _ in room_users.content:
            if room_user.id == bot.bot_id:
                continue
            previous_task = bot.emote_tasks.pop(room_user.id, None)
            if previous_task:
                previous_task.cancel()
            bot.emote_tasks[room_user.id] = asyncio.create_task(
                bot.random_emote_loop(room_user.id)
            )
            users_started += 1
        return f"<#66FF99>🎭 Emotes aleatorios activados para {users_started} usuarios."

    if command.startswith("!set"):
        return await bot.position_manager.set_bot_position(bot, user_id)

    return None