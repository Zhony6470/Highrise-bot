import os
import asyncio


async def handle_owner_command(bot, command: str, user_id: str) -> str | None:
    if command == "!randomall":
        room_users = await bot.highrise.get_room_users()
        users_started = 0
        bot_usernames = {
            str(getattr(bot, "bot_username", "")).lower(),
            str(os.getenv("DJ_BOT_USERNAME", "Dj.Z")).lower(),
        }
        for room_user, _ in room_users.content:
            if (
                room_user.id == bot.bot_id
                or room_user.username.lower() in bot_usernames
            ):
                continue
            previous_task = bot.emote_tasks.pop(room_user.id, None)
            if previous_task:
                previous_task.cancel()
            bot.emote_tasks[room_user.id] = asyncio.create_task(
                bot.random_emote_loop(room_user.id)
            )
            users_started += 1
        return f"<#66FF99>🎭 Emotes aleatorios activados para {users_started} usuarios."

    return None