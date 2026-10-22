import asyncio
import os
import random
from highrise import Position

ALLOWED_ROLES = {"vip", "mod", "owner", "designer"}
ORDER_EMOTES = {
    "!sentado": ("idle-loop-sitfloor", "Sit"),
    "!duerme": ("idle-floorsleeping", "Cozy Nap"),
}


def _state(bot):
    if not hasattr(bot, "slave_links"):
        bot.slave_links = {}
    if not hasattr(bot, "slave_monitor_task"):
        bot.slave_monitor_task = None


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
        "zeta_bot", "dj.z", "ghost_wave", "ghost wave", "fun_bot", "games_bot",
    }
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
    if escaped:
        await _announce(
            bot,
            f"<#FFCC66>🏃💨 ¡@{slave_name} se ha escapado de @{owner_name}! "
            "¡La libertad triunfa! 🎉",
        )
    else:
        await _announce(
            bot,
            f"<#66FF99>🔓 @{slave_name} ha sido liberado/a por @{owner_name}. "
            "¡Se acabó el servicio! 😄",
        )
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
    if command == "!baila":
        choices = [
            item for item in bot.emotes_list
            if "dance" in str(item.get("command", "")).casefold()
            or "dance" in str(item.get("emote", "")).casefold()
        ]
        if not choices:
            await bot.highrise.send_whisper(owner.id, "🎭 No encontré emotes de baile en el catálogo.")
            return
        emote = random.choice(choices)
    else:
        emote_id, emote_name = ORDER_EMOTES[command]
        emote = next(
            (item for item in bot.emotes_list if item.get("emote") == emote_id),
            {"emote": emote_id, "command": emote_name, "duration": 15, "auth": "public"},
        )
    success = await bot._activate_emote(owner.id, slave_id, emote)
    if success:
        labels = {"!sentado": "🪑 ¡A sentarse!", "!baila": "💃 ¡A bailar!", "!duerme": "😴 ¡A dormir!"}
        await _announce(bot, f"<#CC99FF>{labels[command]} @{link['slave_username']} obedece la orden de @{owner.username}.")


async def handle_slave_command(bot, user, message):
    _state(bot)
    msg = message.strip()
    lower = msg.casefold()
    parts = msg.split()
    command = parts[0].casefold() if parts else ""

    if command == "!esclavizar":
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
        await _announce(bot, f"<#CC99FF>⛓️ @{user.username} ha esclavizado a @{target_display}. ¡Que empiece la aventura! 😈")
        await _start_monitor(bot)
        return True

    if lower == "!escapar":
        if user.id in bot.slave_links:
            await _release(bot, user.id, escaped=True)
        else:
            await bot.highrise.send_whisper(user.id, "🔎 No tienes un amo del que escapar.")
        return True

    if lower == "!liberar esclavo":
        owned = next((sid for sid, link in bot.slave_links.items() if link["owner_id"] == user.id), None)
        if owned is None:
            await bot.highrise.send_whisper(user.id, "🔎 No tienes ningún esclavo que liberar.")
        else:
            await _release(bot, owned)
        return True

    if command in {"!sentado", "!baila", "!duerme"}:
        slave_id = next((sid for sid, link in bot.slave_links.items() if link["owner_id"] == user.id), None)
        if slave_id is None:
            return False
        await _order_slave(bot, user, slave_id, command)
        return True

    return False
