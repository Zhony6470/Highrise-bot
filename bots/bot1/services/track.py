import os
import asyncio
import time
from random import choice

from highrise import Position, User
from services.storage import load_json, save_json

TRACK_KEY = "pista_emotes"
MAX_TRACKS = 3


def _load_tracks(bot) -> list[dict]:
    try:
        data = load_json(bot.position_manager.positions_file)
        raw = data.get(TRACK_KEY)

        # Compatibilidad con la estructura anterior, que guardaba una sola pista.
        if isinstance(raw, dict):
            return [raw]
        if isinstance(raw, list):
            return [track for track in raw if isinstance(track, dict)]
    except (AttributeError, TypeError, ValueError):
        pass
    return []


def _save_tracks(bot, tracks: list[dict]) -> None:
    data = load_json(bot.position_manager.positions_file)
    if tracks:
        data[TRACK_KEY] = tracks[:MAX_TRACKS]
    else:
        data.pop(TRACK_KEY, None)
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
                user.id, "<#FF6666>🔒 Solo el dueño o los moderadores pueden borrar las pistas."
            )
            return True

        tracks = _load_tracks(bot)
        if not tracks:
            await bot.highrise.send_whisper(
                user.id, "<#FFCC66>🔎 No hay ninguna pista de emotes creada."
            )
            return True

        _save_tracks(bot, [])
        if bot.track_monitor_task:
            bot.track_monitor_task.cancel()
            bot.track_monitor_task = None

        for user_id in list(bot.track_emote_tasks):
            task = bot.track_emote_tasks.pop(user_id)
            task.cancel()
            await bot.highrise.send_emote("", user_id)

        await bot.highrise.send_whisper(
            user.id,
            f"<#66FF99>🗑️ Se eliminaron {len(tracks)} pista(s) de emotes correctamente.",
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

    tracks = _load_tracks(bot)
    if len(tracks) >= MAX_TRACKS:
        await bot.highrise.send_whisper(
            user.id,
            f"<#FFCC66>📍 Ya existen las {MAX_TRACKS} pistas permitidas. "
            "Usa !deletepista para eliminarlas y crearlas nuevamente.",
        )
        return True

    position = await bot.get_user_position(user.id)
    if not position:
        await bot.highrise.send_whisper(
            user.id,
            "<#FF6666>📍 No pude obtener tu posición actual.",
        )
        return True

    tracks.append(
        {
            "x": position.x,
            "y": position.y,
            "z": position.z,
            "radius": radius,
        }
    )
    _save_tracks(bot, tracks)

    track_number = len(tracks)
    await bot.highrise.send_whisper(
        user.id,
        f"<#66FF99>🎶 Pista {track_number}/{MAX_TRACKS} creada: radio de {radius:g} bloques "
        f"({2 * radius + 1:g}x{2 * radius + 1:g}).\n"
        "<#66CCFF>💃 Todos los usuarios dentro harán el mismo emote aleatorio de esa pista.",
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
    Monitor independiente de hasta tres pistas.

    Cada pista tiene su propio emote actual y sus propios usuarios.
    Si dos pistas se superponen, un usuario queda asignado a la primera
    pista que lo contiene para evitar enviarle dos emotes simultáneamente.
    """
    track_states = []
    active_user_ids = set()

    try:
        while True:
            tracks = _load_tracks(bot)
            if not tracks:
                break

            while len(track_states) < len(tracks):
                track_states.append(
                    {
                        "current_emote": None,
                        "next_emote_at": 0.0,
                        "active_user_ids": set(),
                    }
                )
            if len(track_states) > len(tracks):
                track_states = track_states[: len(tracks)]

            room_users = await bot.highrise.get_room_users()
            eligible_users = []

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
                eligible_users.append((room_user, room_position))

            now = time.monotonic()
            assigned_user_ids = set()
            new_active_user_ids = set()

            for index, track in enumerate(tracks):
                state = track_states[index]
                inside_user_ids = set()

                for room_user, room_position in eligible_users:
                    if room_user.id in assigned_user_ids:
                        continue
                    if _is_inside(room_position, track):
                        inside_user_ids.add(room_user.id)
                        assigned_user_ids.add(room_user.id)

                if not state["current_emote"] or now >= state["next_emote_at"]:
                    if not bot.emotes_list:
                        await asyncio.sleep(1)
                        continue

                    selected = choice(bot.emotes_list)
                    state["current_emote"] = selected["emote"]
                    duration = float(selected.get("duration", 3))
                    state["next_emote_at"] = now + max(duration, 0.1)
                    emote_changed = True
                else:
                    emote_changed = False

                left = state["active_user_ids"] - inside_user_ids
                for user_id in left:
                    try:
                        await bot.highrise.send_emote("", user_id)
                    except Exception as error:
                        print(
                            f"No se pudo limpiar emote de pista de {user_id}: {error}"
                        )

                if emote_changed and inside_user_ids:
                    results = await asyncio.gather(
                        *(
                            bot.highrise.send_emote(
                                state["current_emote"], user_id
                            )
                            for user_id in inside_user_ids
                        ),
                        return_exceptions=True,
                    )
                    for user_id, result in zip(inside_user_ids, results):
                        if isinstance(result, Exception):
                            print(
                                f"Emote de pista no disponible para {user_id}: "
                                f"{state['current_emote']} ({result})"
                            )
                else:
                    entered = inside_user_ids - state["active_user_ids"]
                    if entered:
                        await asyncio.gather(
                            *(
                                bot.highrise.send_emote(
                                    state["current_emote"], user_id
                                )
                                for user_id in entered
                            ),
                            return_exceptions=True,
                        )

                state["active_user_ids"] = inside_user_ids
                new_active_user_ids.update(inside_user_ids)

            active_user_ids = new_active_user_ids
            await asyncio.sleep(0.5)

    except asyncio.CancelledError:
        pass
    except Exception as error:
        print(f"Error monitorizando las pistas de emotes: {error}")
    finally:
        for state in track_states:
            for user_id in state.get("active_user_ids", set()):
                try:
                    await bot.highrise.send_emote("", user_id)
                except Exception as error:
                    print(
                        f"No se pudo limpiar emote de pista de {user_id}: {error}"
                    )

        if bot.track_monitor_task is asyncio.current_task():
            bot.track_monitor_task = None


async def update_user(bot, user: User, position: Position) -> None:
    # Compatibilidad con llamadas antiguas. El monitor central controla las pistas.
    return


async def track_emote_loop(bot, user_id: str) -> None:
    # Compatibilidad con tareas antiguas. Las pistas ya no dependen de ellas.
    return
