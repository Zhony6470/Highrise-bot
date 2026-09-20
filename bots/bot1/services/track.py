import os
import asyncio

from highrise import Position, User
from services.storage import load_json, save_json

TRACK_KEY = "pista_emotes"


def _load_track(bot) -> dict | None:
    try:
        data = load_json(bot.position_manager.positions_file)
        return data.get(TRACK_KEY)
    except (AttributeError, TypeError, ValueError):
        return None


def _save_track(bot, track: dict | None) -> None:
    data = load_json(bot.position_manager.positions_file)
    if track is None:
        data.pop(TRACK_KEY, None)
    else:
        data[TRACK_KEY] = track
    save_json(bot.position_manager.positions_file, data)


def _is_inside(position: Position, track: dict) -> bool:
    radius = float(track.get("radius", track.get("side", 0)))
    return (
        abs(position.x - track["x"]) <= radius
        and abs(position.z - track["z"]) <= radius
        and abs(position.y - track["y"]) <= 1.5
    )


async def handle_track_command(bot, user: User, message: str) -> bool:
    command = message.lower().strip()
    if command == "!deletepista":
        if not await _can_manage(bot, user):
            await bot.highrise.send_whisper(
                user.id, "<#FF6666>🔒 Solo el dueño o los moderadores pueden borrar la pista."
            )
            return True
        if _load_track(bot) is None:
            await bot.highrise.send_whisper(
                user.id, "<#FFCC66>🔎 No hay ninguna pista de emotes creada."
            )
            return True
        _save_track(bot, None)
        if bot.track_monitor_task:
            bot.track_monitor_task.cancel()
            bot.track_monitor_task = None
        for user_id in list(bot.track_emote_tasks):
            task = bot.track_emote_tasks.pop(user_id)
            task.cancel()
            await bot.highrise.send_emote("", user_id)
        await bot.highrise.send_whisper(
            user.id, "<#66FF99>🗑️ La pista de emotes fue eliminada correctamente."
        )
        return True

    if not command.startswith("!pista"):
        return False
    if not await _can_manage(bot, user):
        await bot.highrise.send_whisper(
            user.id, "<#FF6666>🔒 Solo el dueño o los moderadores pueden crear una pista."
        )
        return True

    parts = message.split()
    if len(parts) != 3 or parts[1].lower() != "rad":
        await bot.highrise.send_whisper(
            user.id, "<#FFCC66>📍 Uso: !pista rad <radio>"
        )
        return True
    try:
        radius = float(parts[2])
    except ValueError:
        await bot.highrise.send_whisper(
            user.id, "<#FFCC66>🔢 El radio debe ser un número positivo."
        )
        return True
    if radius <= 0:
        await bot.highrise.send_whisper(
            user.id, "<#FFCC66>🔢 El radio debe ser mayor que 0."
        )
        return True

    position = await bot.get_user_position(user.id)
    if not position:
        await bot.highrise.send_whisper(
            user.id, "<#FF6666>📍 No pude obtener tu posición actual."
        )
        return True

    _save_track(
        bot,
        {
            "x": position.x,
            "y": position.y,
            "z": position.z,
            "radius": radius,
        },
    )
    await bot.highrise.send_whisper(
        user.id,
        f"<#66FF99>🎶 Pista creada: radio de {radius:g} bloques "
        f"({2 * radius + 1:g}x{2 * radius + 1:g}).\n"
        "<#66CCFF>💃 Los usuarios dentro copiarán el emote actual del bot.",
    )
    await start_track_monitor(bot)
    return True


async def _can_manage(bot, user: User) -> bool:
    return user.id == bot.owner_id or await bot.is_mod(user.id)


async def update_user(bot, user: User, position: Position) -> None:
    track = _load_track(bot)
    if not track or user.id == bot.bot_id:
        return
    bot_names = {
        str(getattr(bot, "bot_username", "")).lower(),
        str(os.getenv("DJ_BOT_USERNAME", "Dj.Z")).lower(),
    }
    if user.username.lower() in bot_names:
        return

    inside = _is_inside(position, track)
    task = bot.track_emote_tasks.get(user.id)
    if inside and task is None:
        bot.track_emote_tasks[user.id] = asyncio.create_task(
            track_emote_loop(bot, user.id)
        )
    elif not inside and task is not None:
        task.cancel()
        bot.track_emote_tasks.pop(user.id, None)
        await bot.highrise.send_emote("", user.id)


async def start_track_monitor(bot) -> None:
    if bot.track_monitor_task:
        bot.track_monitor_task.cancel()
    bot.track_monitor_task = asyncio.create_task(track_monitor_loop(bot))


async def track_monitor_loop(bot) -> None:
    try:
        while _load_track(bot) is not None:
            room_users = await bot.highrise.get_room_users()
            active_user_ids = set()
            for room_user, room_position in room_users.content:
                if isinstance(room_position, Position) and room_user.id != bot.bot_id:
                    active_user_ids.add(room_user.id)
                    await update_user(bot, room_user, room_position)

            for user_id in set(bot.track_emote_tasks) - active_user_ids:
                task = bot.track_emote_tasks.pop(user_id)
                task.cancel()
                await bot.highrise.send_emote("", user_id)
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass
    except Exception as error:
        print(f"Error monitorizando la pista de emotes: {error}")
    finally:
        if bot.track_monitor_task is asyncio.current_task():
            bot.track_monitor_task = None


async def track_emote_loop(bot, user_id: str) -> None:
    last_emote = None
    try:
        while True:
            track = _load_track(bot)
            position = bot.user_positions.get(user_id)
            if position is None:
                position = await bot.get_user_position(user_id)
            if not track or not position or not _is_inside(position, track):
                break
            emote_id = bot.current_bot_emote
            if emote_id and emote_id != last_emote:
                last_emote = emote_id
                try:
                    await bot.highrise.send_emote(emote_id, user_id)
                except Exception as error:
                    print(
                        f"Emote de pista no disponible para {user_id}: "
                        f"{emote_id} ({error})"
                    )
            await asyncio.sleep(0.05)
    except asyncio.CancelledError:
        pass
    except Exception as error:
        print(f"Error en la pista de emotes: {error}")
    finally:
        bot.track_emote_tasks.pop(user_id, None)
        try:
            await bot.highrise.send_emote("", user_id)
        except Exception as error:
            print(f"No se pudo limpiar el emote de pista de {user_id}: {error}")
