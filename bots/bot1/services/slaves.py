import asyncio
import os
import random
from highrise import Position

ALLOWED_ROLES = {"vip", "mod", "owner", "designer"}
ORDER_EMOTES = {
    "sentado": ("idle-loop-sitfloor", "Sit"),
    "duerme": ("idle-floorsleeping", "Cozy Nap"),
}
SLAP_EMOTE = {"emote": "emote-slap", "command": "Slap", "duration": 2.7, "auth": "public"}
# Entrada 56 del catálogo actual (numeración desde 1).
RELEASE_EMOTE = {"emote": "emote-jumpb", "command": "Jump", "duration": 3.6, "auth": "public"}
SLAVE_MESSAGES = {
    "enslave": [
        "⛓️ @{owner} ha esclavizado a @{slave}. ¡Que empiece la aventura! 😈",
        "📣 ¡Atención! @{slave} ahora sigue las órdenes de @{owner}. ¡A portarse bien! 😂",
        "🔗 @{owner} ha reclamado a @{slave} como su ayudante personal. ¡Suerte a ambos! 😜",
    ],
    "release": [
        "🔓 @{slave} ha sido liberado/a por @{owner}. ¡Se acabó el servicio! 😄",
        "🎉 ¡Buenas noticias! @{slave} vuelve a ser libre. @{owner} le ha soltado las cadenas.",
        "🕊️ @{owner} ha liberado a @{slave}. ¡A disfrutar de la libertad!",
    ],
    "escape": [
        "🏃💨 ¡@{slave} se ha escapado de @{owner}! ¡La libertad triunfa! 🎉",
        "🚨 ¡Fuga exitosa! @{slave} ha dejado atrás a @{owner}. ¡Corre! 😂",
        "🕊️ ¡@{slave} rompió las cadenas y escapó de @{owner}!",
    ],
    "whip": [
        "🐎 ¡@{owner} ha usado el látigo! @{slave}, ¡a obedecer! 😈",
        "⚡ ¡Chas! @{owner} le ha dado un latigazo teatral a @{slave}.",
        "🎭 @{owner} hace sonar el látigo y @{slave} recibe el susto de su vida.",
    ],
    "sit": [
        "🪑 @{owner} ordena sentarse. ¡@{slave}, a descansar!",
        "📢 ¡Asiento inmediato para @{slave}! Orden de @{owner}.",
        "😌 @{slave} se sienta; @{owner} ha hablado.",
    ],
    "dance": [
        "💃 ¡@{owner} ordena bailar y @{slave} mueve el esqueleto!",
        "🎶 ¡Que suene la música! @{slave} baila por orden de @{owner}.",
        "🕺 @{slave} demuestra sus pasos. ¡Orden de @{owner} cumplida!",
    ],
    "sleep": [
        "😴 @{owner} manda a dormir a @{slave}. ¡Buenas noches!",
        "🌙 Se acabó la fiesta para @{slave}: orden de dormir de @{owner}.",
        "💤 @{slave} se va a dormir por orden de @{owner}.",
    ],
}


def _state(bot):
    if not hasattr(bot, "slave_links"):
        bot.slave_links = {}
    if not hasattr(bot, "slave_monitor_task"):
        bot.slave_monitor_task = None


async def _play_once(bot, target_id, emote):
    """Ejecuta un emote una sola vez, sin cambiar la lógica global de emotes."""
    task = getattr(bot, "emote_tasks", {}).pop(target_id, None)
    if task:
        task.cancel()
    await bot.highrise.send_emote(emote["emote"], target_id)


def _random_message(kind, owner, slave):
    return random.choice(SLAVE_MESSAGES[kind]).format(owner=owner, slave=slave)


async def _announce(bot, text):
    try:
        await bot.highrise.chat(text)
    except Exception as error:
        print(f"[SLAVE] No se pudo anunciar: {error}")


async def _is_allowed(bot, user):
    try:
        roles = await bot.role_manager.get_user_roles(bot, user)
        return bool(roles.intersection(ALLOWED_ROLES))
    except Exception as error:
        print(f"[SLAVE] No se pudieron consultar roles de @{user.username}: {error}")
        return user.id == bot.owner_id


async def _is_bot_target(bot, target_id, target_username):
    username = target_username.strip().casefold()
    known_names = {
        str(getattr(bot, "bot_username", "Zeta_Bot")).casefold(),
        os.getenv("DJ_BOT_USERNAME", "Dj.Z").casefold(),
        os.getenv("FUN_BOT_USERNAME", "Fun_Bot").casefold(),
        os.getenv("GHOST_WAVE_USERNAME", "Ghost_Wave").casefold(),
        os.getenv("GHOST_BOT_USERNAME", "Ghost_Wave").casefold(),
        os.getenv("BOT3_USERNAME", "BotJuegos").casefold(),
        os.getenv("BOT1_USERNAME", "Zeta_Bot").casefold(),
        "zeta_bot", "dj.z", "ghost_wave", "ghost wave", "fun_bot", "games_bot", "botjuegos",
    }
    for key, value in os.environ.items():
        if "USERNAME" in key.upper() and any(tag in key.upper() for tag in ("BOT", "GHOST", "DJ")) and value.strip():
            known_names.add(value.strip().casefold())
    if target_id == getattr(bot, "bot_id", None) or username in known_names:
        return True
    # Protección adicional para bots con nombres identificables.
    if "ghost" in username or username.endswith("_bot") or username.endswith("bot"):
        return True
    try:
        return await bot.is_bot_user(target_id)
    except Exception:
        return False


def _nearby_position(owner_position):
    # Coloca al esclavo a un bloque en diagonal, no encima del amo.
    return Position(
        owner_position.x + 1,
        owner_position.y,
        owner_position.z + 1,
        facing=owner_position.facing,
    )


async def _release(bot, slave_id, escaped=False):
    _state(bot)
    link = bot.slave_links.pop(slave_id, None)
    if not link:
        return False
    task = getattr(bot, "emote_tasks", {}).pop(slave_id, None)
    if task:
        task.cancel()
    slave_name = link.get("slave_username", "el esclavo")
    owner_name = link.get("owner_username", "su amo")
    try:
        await _play_once(bot, slave_id, RELEASE_EMOTE)
    except Exception as error:
        print(f"[SLAVE] No se pudo ejecutar el emote 56 al liberar: {error}")
    kind = "escape" if escaped else "release"
    await _announce(bot, "<#66FF99>" + _random_message(kind, owner_name, slave_name))
    return True


async def _monitor_slaves(bot):
    try:
        while bot.slave_links:
            for slave_id, link in list(bot.slave_links.items()):
                try:
                    owner_position = await bot.get_user_position(link["owner_id"])
                    slave_position = await bot.get_user_position(slave_id)
                    if not owner_position or not slave_position:
                        continue
                    dx = slave_position.x - owner_position.x
                    dz = slave_position.z - owner_position.z
                    dy = slave_position.y - owner_position.y
                    # Si se aleja más de unos dos bloques, vuelve a un punto cercano.
                    if dx * dx + dz * dz > 6.25 or abs(dy) > 2:
                        await bot.highrise.teleport(slave_id, _nearby_position(owner_position))
                except Exception as error:
                    print(f"[SLAVE] Error siguiendo al esclavo {slave_id}: {error}")
            await asyncio.sleep(1.0)
    except asyncio.CancelledError:
        pass
    finally:
        if getattr(bot, "slave_monitor_task", None) is asyncio.current_task():
            bot.slave_monitor_task = None


async def _start_monitor(bot):
    _state(bot)
    if bot.slave_monitor_task and not bot.slave_monitor_task.done():
        return
    bot.slave_monitor_task = asyncio.create_task(_monitor_slaves(bot))


async def _order_slave(bot, owner, slave_id, command):
    link = bot.slave_links.get(slave_id)
    if not link or link["owner_id"] != owner.id:
        await bot.highrise.send_whisper(owner.id, "🔎 No tienes un esclavo activo al que darle órdenes.")
        return
    if command == "baila":
        choices = [
            item for item in bot.emotes_list
            if not item.get("disabled")
            and ("dance" in str(item.get("command", "")).casefold()
                 or "dance" in str(item.get("emote", "")).casefold())
        ]
        if not choices:
            await bot.highrise.send_whisper(owner.id, "🎭 No encontré emotes de baile en el catálogo.")
            return
        emote = random.choice(choices)
    else:
        emote_id, emote_name = ORDER_EMOTES[command]
        emote = next(
            (item for item in bot.emotes_list if item.get("emote") == emote_id and not item.get("disabled")),
            {"emote": emote_id, "command": emote_name, "duration": 15, "auth": "public"},
        )
    try:
        await _play_once(bot, slave_id, emote)
        kind = {"sentado": "sit", "baila": "dance", "duerme": "sleep"}[command]
        await _announce(bot, "<#CC99FF>" + _random_message(kind, owner.username, link["slave_username"]))
    except Exception as error:
        print(f"[SLAVE] No se pudo ejecutar la orden {command}: {error}")
        await bot.highrise.send_whisper(owner.id, "⚠️ No pude ejecutar esa orden sobre el esclavo.")


async def handle_slave_command(bot, user, message):
    _state(bot)
    msg = message.strip()
    lower = msg.casefold()
    parts = msg.split()
    command = parts[0].casefold().lstrip("!") if parts else ""

    if command == "esclavizar":
        if not await _is_allowed(bot, user):
            await bot.highrise.send_whisper(user.id, "🔒 Solo VIP, moderadores, owner y designer pueden usar este comando.")
            return True
        if len(parts) != 2 or not parts[1].startswith("@"):
            await bot.highrise.send_whisper(user.id, "Uso: !esclavizar @usuario")
            return True
        target_name = parts[1][1:].strip()
        target_id = await bot.get_user_id(target_name)
        if not target_id:
            await bot.highrise.send_whisper(user.id, "🔎 No encontré a ese usuario en la sala.")
            return True
        if target_id == user.id:
            await bot.highrise.send_whisper(user.id, "😅 No puedes esclavizarte a ti mismo.")
            return True
        if await _is_bot_target(bot, target_id, target_name):
            await bot.highrise.send_whisper(user.id, "🤖 Los bots no pueden ser esclavizados.")
            return True
        if target_id in bot.slave_links:
            await bot.highrise.send_whisper(user.id, "⛓️ Ese usuario ya tiene un amo. ¡No se permiten dos amos!")
            return True
        if any(link["owner_id"] == user.id for link in bot.slave_links.values()):
            await bot.highrise.send_whisper(user.id, "⛓️ Ya tienes un esclavo. Libéralo antes de esclavizar a otra persona.")
            return True
        if any(link["slave_id"] == user.id for link in bot.slave_links.values()):
            await bot.highrise.send_whisper(user.id, "⛓️ No puedes esclavizar a alguien mientras tú eres esclavo. Usa !escapar primero.")
            return True
        target_position = await bot.get_user_position(target_id)
        owner_position = await bot.get_user_position(user.id)
        if not target_position or not owner_position:
            await bot.highrise.send_whisper(user.id, "📍 No pude obtener las posiciones necesarias.")
            return True
        room_users = await bot.highrise.get_room_users()
        target_user = next((u for u, _ in room_users.content if u.id == target_id), None)
        target_display = target_user.username if target_user else target_name
        bot.slave_links[target_id] = {
            "slave_id": target_id,
            "slave_username": target_display,
            "owner_id": user.id,
            "owner_username": user.username,
        }
        try:
            await bot.highrise.teleport(target_id, _nearby_position(owner_position))
        except Exception as error:
            bot.slave_links.pop(target_id, None)
            await bot.highrise.send_whisper(user.id, f"⚠️ No pude traer al usuario cerca de ti: {error}")
            return True
        await _announce(bot, "<#CC99FF>" + _random_message("enslave", user.username, target_display))
        await _start_monitor(bot)
        return True

    if command == "escapar":
        if user.id in bot.slave_links:
            await _release(bot, user.id, escaped=True)
        else:
            await bot.highrise.send_whisper(user.id, "🔎 No tienes un amo del que escapar.")
        return True

    if lower in {"!liberar esclavo", "liberar esclavo"}:
        owned = next((sid for sid, link in bot.slave_links.items() if link["owner_id"] == user.id), None)
        if owned is None:
            await bot.highrise.send_whisper(user.id, "🔎 No tienes ningún esclavo que liberar.")
        else:
            await _release(bot, owned)
        return True

    if command in {"sentado", "sientado", "baila", "duerme"}:
        slave_id = next((sid for sid, link in bot.slave_links.items() if link["owner_id"] == user.id), None)
        if slave_id is None:
            await bot.highrise.send_whisper(user.id, "🔎 Primero usa !esclavizar @usuario para tener un esclavo.")
            return True
        normalized = "sentado" if command in {"sentado", "sientado"} else command
        await _order_slave(bot, user, slave_id, normalized)
        return True

    return False
