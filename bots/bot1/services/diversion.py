import asyncio
from random import choice, randint

from highrise import User


FIGHT_EMOTES = (
    "emote-superpunch",
    "emote-kicking",
    "emote-swordfight",
    "emoji-punch",
)

SECRET_ADMIRER_MESSAGES = (
    "<#FF66CC>💌 Un admirador secreto le ha enviado un beso a @{target}. 💋",
    "<#FF99CC>🌟 @{target} recibió un beso anónimo lleno de cariño. 😘",
    "<#CC99FF>📣 ¡Alerta romántica! Alguien tiene los ojos puestos en @{target}. 💖",
    "<#FFCC66>👀 Un admirador secreto vio a @{target} y olvidó lo que iba a decir. 😳",
    "<#66CCFF>💫 @{target} acaba de recibir una dosis secreta de admiración. ✨",
)

LOW_LOVE_MESSAGES = (
    "<#FF6666>💔 Compatibilidad: {percent}%\n@{first} y @{second} son como el agua y el aceite. 🌊🫒",
    "<#FF9966>📉 El detector de química marca {percent}%\nMejor que sigan siendo amigos... o ni eso. 😂",
    "<#CC6666>🥶 Compatibilidad romántica: {percent}%\nEntre @{first} y @{second} hay más hielo que mariposas. ❄️",
    "<#FFCC66>🚧 Nivel de romance: {percent}%\nLa relación necesita señales, mapa y probablemente un milagro. 😅",
    "<#FF6666>🚩 Compatibilidad: {percent}%\n@{first} y @{second} juntos son una colección completa de red flags. 🚩",
    "<#CC6666>🪦 Química detectada: {percent}%\nEl romance murió antes de empezar. Mis condolencias. 😂",
    "<#FF9966>📵 Compatibilidad: {percent}%\n@{first} deja en visto a @{second} hasta en los sueños. 👀",
    "<#FF6666>🥀 Nivel de ternura: {percent}%\nEsto no es una historia de amor, es un documental de supervivencia. 😭",
    "<#CC6666>⚡ Compatibilidad: {percent}%\nSe atraen menos que dos imanes puestos al revés. 🧲",
    "<#FFCC66>🧯 Romance en llamas: {percent}%\nPero no de pasión... alguien traiga el extintor. 🔥",
    "<#FF6666>🎭 Compatibilidad: {percent}%\n@{first} y @{second} serían una pareja perfecta... para discutir por todo. 😈",
    "<#CC6666>🧊 El destino dice: {percent}%\nNi Cupido se atreve a intervenir en este caso. 🏹",
)

MEDIUM_LOVE_MESSAGES = (
    "<#FFFF66>💫 Compatibilidad: {percent}%\n@{first} y @{second} tienen química, pero el destino está indeciso. 👀",
    "<#FFCC66>⚖️ El detector marca {percent}%\nPodrían ser pareja... o dos personas que se saludan por compromiso. 😄",
    "<#CCFF66>🌱 Compatibilidad: {percent}%\nHay una pequeña chispa entre @{first} y @{second}; toca dejarla crecer. ✨",
    "<#FFCC66>🌶️ Compatibilidad: {percent}%\nHay tensión, miradas y una cantidad sospechosa de excusas para hablarse. 👀",
    "<#FFFF66>🎲 Química: {percent}%\n@{first} y @{second} son una apuesta arriesgada, pero alguien tiene que lanzarse. 😏",
    "<#CCFF66>💬 Compatibilidad: {percent}%\nPodrían ser novios si dejan de coquetear y empiezan a admitirlo. 😳",
    "<#FFCC66>🕯️ Nivel de romance: {percent}%\nLa llama existe, pero cualquiera de los dos podría apagarla por orgullo. 🔥",
    "<#FFFF66>⚠️ Compatibilidad: {percent}%\nNo son agua y aceite, pero tampoco precisamente chocolate y fresas. 😅",
    "<#CCFF66>🧪 Química: {percent}%\nLa fórmula funciona en teoría; falta comprobarla en la práctica. ✨",
    "<#FFCC66>👀 Compatibilidad: {percent}%\n@{first} y @{second} tienen algo... aunque todavía nadie sabe qué. 🤭",
)

HIGH_LOVE_MESSAGES = (
    "<#FF66CC>💖 Compatibilidad amorosa: {percent}%\n@{first} y @{second} harían una linda pareja. 💞",
    "<#FF99CC>💘 El detector de química marca {percent}%\n¡@{first} y @{second} tienen vibra de novios! 😍",
    "<#CC66FF>🔥 Nivel de atracción: {percent}%\n@{first} y @{second} podrían ser amantes de novela. 🎬",
    "<#FFCC66>💍 Compatibilidad matrimonial: {percent}%\n¡@{first} y @{second} ya casi están eligiendo las invitaciones! 👰",
    "<#66FF99>🌟 Resultado del destino: {percent}%\n@{first} y @{second} parecen la pareja protagonista de la sala. 🎭",
    "<#FF66CC>🌶️ Compatibilidad peligrosa: {percent}%\n@{first} y @{second} tienen tanta química que deberían venir con advertencia. 🔥",
    "<#FF99CC>💋 Nivel de coqueteo: {percent}%\nEstos dos no necesitan Cupido, necesitan que alguien les consiga una habitación... para hablar. 😏",
    "<#CC66FF>👑 Compatibilidad real: {percent}%\n@{first} y @{second} tienen vibra de reyes, drama y final feliz. 💍",
    "<#FFCC66>🍓 Química: {percent}%\nDulces, intensos y probablemente peligrosos cuando están juntos. 😈",
    "<#66FF99>💞 Resultado: {percent}%\n@{first} y @{second} son oficialmente demasiado adorables para esta sala. ✨",
    "<#FF66CC>🫦 Atracción: {percent}%\nLa tensión entre @{first} y @{second} ya se puede cortar con un cuchillo. 🔥",
    "<#CC99FF>💌 Compatibilidad: {percent}%\nSi esto no es amor, al menos es un excelente comienzo de chisme. 👀",
    "<#FF99CC>💍 Pronóstico: {percent}%\nSe vienen mensajes de buenos días, celos y una boda improvisada. 😂",
)


async def handle_diversion_command(bot, user: User, message: str) -> bool:
    command = message.lower().strip()
    if command.startswith("!fight "):
        await handle_fight(bot, user, message)
        return True
    if command.startswith(("!kiss ", "!heart ")):
        await handle_affection(bot, user, message)
        return True
    if command.startswith("!love "):
        await handle_love(bot, user, message)
        return True
    return False


async def handle_fight(bot, user: User, message: str) -> None:
    parts = message.split()
    if len(parts) != 2 or not parts[1].startswith("@"):
        await bot.highrise.send_whisper(user.id, "🥊 Uso: !fight @usuario")
        return

    target_username = parts[1][1:]
    target_id = await bot.get_user_id(target_username)
    if not target_id:
        await bot.highrise.send_whisper(
            user.id, "<#FFCC66>🔎 Usuario no encontrado en la sala."
        )
        return
    if target_id == user.id or await bot.is_bot_user(target_id):
        await bot.highrise.send_whisper(
            user.id, "<#FF6666>🛡️ Los bots no pueden ser objetivos de este comando."
        )
        return

    for fighter_id in (user.id, target_id):
        previous_task = bot.emote_tasks.pop(fighter_id, None)
        if previous_task:
            previous_task.cancel()

    fight_task = asyncio.create_task(
        run_fight(bot, user, target_id, target_username)
    )
    bot.fight_tasks.add(fight_task)
    fight_task.add_done_callback(bot.fight_tasks.discard)
    await bot.highrise.chat(
        f"<#FF9966>🥊 ¡Comienza la pelea entre @{user.username} y "
        f"@{target_username}! 🔥"
    )


async def run_fight(bot, challenger: User, target_id: str, target_username: str) -> None:
    try:
        for _ in range(3):
            await asyncio.gather(
                bot.highrise.send_emote(choice(FIGHT_EMOTES), challenger.id),
                bot.highrise.send_emote(choice(FIGHT_EMOTES), target_id),
            )
            await asyncio.sleep(2.5)

        winner_id, winner_username, loser_id, loser_username = choice(
            (
                (challenger.id, challenger.username, target_id, target_username),
                (target_id, target_username, challenger.id, challenger.username),
            )
        )
        await asyncio.gather(
            bot.highrise.send_emote("emote-celebrate", winner_id),
            bot.highrise.send_emote("emoji-crying", loser_id),
        )
        await bot.highrise.chat(
            f"<#FFFF66>🏆 ¡La pelea terminó! Ganador/a: @{winner_username}! 🎉\n"
            f"<#FF99CC>😢 @{loser_username} tendrá que entrenar para la revancha."
        )
    except asyncio.CancelledError:
        pass
    except Exception as error:
        print(f"Error en la pelea: {error}")


async def handle_affection(bot, user: User, message: str) -> None:
    command = message.lower()
    parts = message.split()
    if len(parts) != 2 or not parts[1].startswith("@"):
        await bot.highrise.send_whisper(
            user.id, "💌 Uso: !kiss @usuario o !heart @usuario"
        )
        return

    target_username = parts[1][1:]
    target_id = await bot.get_user_id(target_username)
    if not target_id:
        await bot.highrise.send_whisper(
            user.id, "<#FFCC66>🔎 Usuario no encontrado en la sala."
        )
        return
    if target_id == user.id or await bot.is_bot_user(target_id):
        await bot.highrise.send_whisper(
            user.id, "<#FF6666>💌 Los bots no pueden ser objetivos de este comando."
        )
        return

    if command.startswith("!kiss "):
        sender_emote = "emote-kiss"
    else:
        sender_emote = "emote-heartfingers"

    try:
        await asyncio.gather(
            bot.highrise.send_emote("emoji-lying", target_id),
            bot.highrise.send_emote(sender_emote, user.id),
        )
        await bot.highrise.chat(
            choice(SECRET_ADMIRER_MESSAGES).format(target=target_username)
        )
    except Exception as error:
        print(f"Error en !kiss/!heart: {error}")
        await bot.highrise.send_whisper(
            user.id, "<#FF6666>💌 No se pudo enviar el gesto en este momento."
        )


async def handle_love(bot, user: User, message: str) -> None:
    parts = message.split()
    if len(parts) not in (2, 3) or not all(part.startswith("@") for part in parts[1:]):
        await bot.highrise.send_whisper(
            user.id, "💖 Uso: !love @usuario o !love @usuario1 @usuario2"
        )
        return

    if len(parts) == 2:
        first_username = user.username
        first_id = user.id
        second_username = parts[1][1:]
        second_id = await bot.get_user_id(second_username)
    else:
        first_username = parts[1][1:]
        second_username = parts[2][1:]
        first_id = await bot.get_user_id(first_username)
        second_id = await bot.get_user_id(second_username)

    if not first_id or not second_id:
        await bot.highrise.send_whisper(
            user.id, "<#FFCC66>🔎 Usuario no encontrado en la sala."
        )
        return
    if (
        first_id == second_id
        or await bot.is_bot_user(first_id)
        or await bot.is_bot_user(second_id)
    ):
        await bot.highrise.send_whisper(
            user.id, "<#FF6666>💖 Los bots no pueden participar en este comando."
        )
        return

    percent = randint(1, 100)
    await asyncio.gather(
        bot.highrise.send_emote("emote-heartfingers", first_id),
        bot.highrise.send_emote("emote-heartshape", second_id),
    )
    await bot.highrise.chat(get_love_message(percent, first_username, second_username))


def get_love_message(percent: int, first: str, second: str) -> str:
    if percent <= 33:
        messages = LOW_LOVE_MESSAGES
    elif percent <= 66:
        messages = MEDIUM_LOVE_MESSAGES
    else:
        messages = HIGH_LOVE_MESSAGES
    return choice(messages).format(percent=percent, first=first, second=second)
