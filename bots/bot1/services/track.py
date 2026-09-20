import os
import asyncio
import time
from random import choice

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


async def start_track_monitor(bot) -> None:
    if bot.track_monitor_task:
        bot.track_monitor_task.cancel()
    bot.track_monitor_task = asyncio.create_task(track_monitor_loop(bot))


async def track_monitor_loop(bot) -> None:
    """
    Monitor independiente de la pista.

    Todos los usuarios dentro del radio reciben exactamente el mismo emote.
    La selección de emotes es propia de la pista y no depende de Zeta.
    """
    active_user_ids = set()
    current_emote = None
    next_emote_at = 0.0

    try:
        while True:
            track = _load_track(bot)
            if track is None:
                break

            room_users = await bot.highrise.get_room_users()
            inside_user_ids = set()

            bot_names = {
                str(getattr(bot, "bot_username", "")).lower(),
                str(os.getenv("DJ_BOT_USERNAME", "Dj.Z")).lower(),
            }

            for room_user, room_position in room_users.content:
                if not isinstance(room_position, Position):
                    continue
                if room_user.id == bot.bot_id:
                    continue
                if room_user.username.lower() in bot_names:
                    continue
                if _is_inside(room_position, track):
                    inside_user_ids.add(room_user.id)

            now = time.monotonic()
            emote_changed = False

            if not current_emote or now >= next_emote_at:
                if not bot.emotes_list:
                    await asyncio.sleep(1)
                    continue

                selected = choice(bot.emotes_list)
                current_emote = selected["emote"]
                duration = float(selected.get("duration", 3))
                next_emote_at = now + max(duration, 0.1)
                emote_changed = True

                print(
                    f"[PISTA] Nuevo emote para todos: "
                    f"{current_emote} ({duration:.1f}s)"
                )

            left = active_user_ids - inside_user_ids
            for user_id in left:
                try:
                    await bot.highrise.send_emote("", user_id)
                except Exception as error:
                    print(
                        f"No se pudo limpiar emote de pista de {user_id}: "
                        f"{error}"
                    )

            # Cuando cambia el emote, TODOS los usuarios de la pista
            # reciben exactamente el mismo emote.
            if emote_changed and inside_user_ids:
                results = await asyncio.gather(
                    *(
                        bot.highrise.send_emote(current_emote, user_id)
                        for user_id in inside_user_ids
                    ),
                    return_exceptions=True,
                )
                for user_id, result in zip(inside_user_ids, results):
                    if isinstance(result, Exception):
                        print(
                            f"Emote de pista no disponible para {user_id}: "
                            f"{current_emote} ({result})"
                        )
            else:
                # Un usuario que acaba de entrar recibe el emote actual.
                entered = inside_user_ids - active_user_ids
                if entered:
                    await asyncio.gather(
                        *(
                            bot.highrise.send_emote(current_emote, user_id)
                            for user_id in entered
                        ),
                        return_exceptions=True,
                    )

            active_user_ids = inside_user_ids
            await asyncio.sleep(0.5)

    except asyncio.CancelledError:
        pass
    except Exception as error:
        print(f"Error monitorizando la pista de emotes: {error}")
    finally:
        for user_id in active_user_ids:
            try:
                await bot.highrise.send_emote("", user_id)
            except Exception as error:
                print(
                    f"No se pudo limpiar emote de pista de {user_id}: {error}"
                )

        if bot.track_monitor_task is asyncio.current_task():
            bot.track_monitor_task = None


async def update_user(bot, user: User, position: Position) -> None:
    # Compatibilidad con llamadas antiguas. El monitor central controla la pista.
    return


async def track_emote_loop(bot, user_id: str) -> None:
    # Compatibilidad con tareas antiguas. La pista ya no depende de ellas.
    return
