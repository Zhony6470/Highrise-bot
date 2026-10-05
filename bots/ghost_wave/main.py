import asyncio, json, os, re
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from zoneinfo import ZoneInfo

from highrise import BaseBot, SessionMetadata
from highrise.__main__ import BotDefinition, main as highrise_main

DATA = Path(os.getenv("GHOST_WAVE_DATA_FILE", "/app/bots/ghost_wave/data/ghost_wave.json"))
DEFAULT_INTERVAL = int(os.getenv("GHOST_WAVE_DEFAULT_INTERVAL", "75"))
TZNAME = os.getenv("GHOST_WAVE_TIMEZONE", "UTC")


class Store:
    def __init__(self):
        self.d = {
            "enabled": False,
            "rooms": {},
            "admins": [],
            "subs": [],
            "conversations": {},
            "names": {},
        }
        try:
            if DATA.exists():
                self.d.update(json.loads(DATA.read_text(encoding="utf8")))
        except Exception as e:
            print("[GHOST] load:", e)
        for key, value in {
            "rooms": {}, "admins": [], "subs": [], "conversations": {}, "names": {}
        }.items():
            self.d.setdefault(key, value)

        # Compatibilidad con una configuración antigua de una sola sala.
        if "room" in self.d and self.d.get("room") and self.d["room"] in self.d["rooms"]:
            room = self.d["rooms"][self.d["room"]]
            room.setdefault("next", self.d.get("next"))
            room.setdefault("last", self.d.get("last"))
            room.setdefault("interval", self.d.get("interval", DEFAULT_INTERVAL))
            room.setdefault("waiting", self.d.get("waiting", False))
            room.setdefault("alerted", self.d.get("alerted", False))
            room.setdefault("enabled", self.d.get("enabled", False))

    def save(self):
        DATA.parent.mkdir(parents=True, exist_ok=True)
        tmp = DATA.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.d, ensure_ascii=False, indent=2), encoding="utf8")
        tmp.replace(DATA)


class Bot(BaseBot):
    def __init__(self):
        super().__init__()
        self.owner_id = None
        self.bot_id = None
        self.store = Store()
        self.task = None

    @property
    def tz(self):
        try:
            return ZoneInfo(str(self.store.d.get("timezone") or TZNAME))
        except Exception:
            return ZoneInfo("UTC")

    def now(self):
        return datetime.now(self.tz)

    def parse_clock(self, value):
        """Acepta una hora sencilla H:MM/HH:MM sin AM ni PM."""
        match = re.fullmatch(r"(1[0-2]|0?[1-9]):([0-5]\d)", value.strip())
        if not match:
            return None
        hour, minute = int(match.group(1)), int(match.group(2))
        return hour, minute

    def actual_clock(self, value, room_name=None):
        parsed = self.parse_clock(value)
        if not parsed:
            return None
        hour, minute = parsed

        predicted = None
        if room_name and room_name in self.store.d["rooms"]:
            predicted = self.iso(self.store.d["rooms"][room_name].get("next"))
        base = predicted or self.now()

        # Sin AM/PM, elegimos la ocurrencia más cercana a la hora prevista.
        candidates = [
            base.replace(hour=hour % 12, minute=minute, second=0, microsecond=0),
            base.replace(hour=(hour % 12) + 12, minute=minute, second=0, microsecond=0),
        ]
        if predicted:
            candidates += [candidate - timedelta(days=1) for candidate in candidates]
            candidates += [candidate + timedelta(days=1) for candidate in candidates[:2]]
            return min(candidates, key=lambda candidate: abs((candidate - predicted).total_seconds()))
        now = self.now()
        past_candidates = [candidate for candidate in candidates if candidate <= now]
        return max(past_candidates, default=max(candidates, key=lambda candidate: abs((candidate - now).total_seconds())))

    def last_wave_clock(self, value):
        """Interpreta una hora sencilla como la última activación real."""
        parsed = self.parse_clock(value)
        if not parsed:
            return None
        hour, minute = parsed
        now = self.now()
        candidates = [
            now.replace(hour=hour % 12, minute=minute, second=0, microsecond=0),
            now.replace(hour=(hour % 12) + 12, minute=minute, second=0, microsecond=0),
        ]
        # La última oleada debe ser una ocurrencia pasada; elige la más reciente.
        past_candidates = [candidate for candidate in candidates if candidate <= now]
        if not past_candidates:
            past_candidates = [candidate - timedelta(days=1) for candidate in candidates]
        return max(past_candidates)

    def iso(self, value):
        try:
            return datetime.fromisoformat(value) if value else None
        except Exception:
            return None

    def fmt(self, value):
        return value.astimezone(self.tz).strftime("%d/%m %I:%M") if value else "--:--"

    def owner(self, user_id):
        return user_id == self.owner_id

    def admin(self, user_id):
        return self.owner(user_id) or user_id in self.store.d["admins"]

    async def inbox(self, user_id, message):
        conversation_id = self.store.d["conversations"].get(user_id)
        try:
            if conversation_id:
                result = await self.highrise.send_message(conversation_id, message)
                if result is None:
                    return True
        except Exception as e:
            print("[GHOST] inbox:", e)
        try:
            result = await self.highrise.send_message_bulk([user_id], message)
            return result is None
        except Exception as e:
            print("[GHOST] bulk:", e)
            return False

    async def broadcast(self, user_ids, message):
        for user_id in list(dict.fromkeys(user_ids)):
            await self.inbox(user_id, message)
            await asyncio.sleep(0.15)

    async def find_user(self, username):
        username = username.lstrip("@").strip()
        normalized = username.casefold()

        # Primero consulta los usuarios que ya han escrito al bot.
        # Esto evita depender exclusivamente del filtro público de WebAPI.
        for user_id, known_name in self.store.d["names"].items():
            if str(known_name).lstrip("@").casefold() == normalized:
                return user_id, known_name

        try:
            response = await self.webapi.get_users(username=username)
            user = next(
                (u for u in response.users
                 if (u.username or "").lstrip("@").casefold() == normalized),
                None,
            )
            if user:
                return user.user_id, user.username or username
        except Exception as e:
            print("[GHOST] find:", e)
        return None

    def extract_room_id(self, link):
        query = parse_qs(urlparse(link).query)
        if query.get("id"):
            return query["id"][0]
        match = re.search(r"(?:room[=/]|id=)([A-Za-z0-9_-]{10,})", link)
        return match.group(1) if match else None

    def room_names(self):
        return list(self.store.d["rooms"].keys())

    def room_list(self):
        rooms = self.store.d["rooms"]
        if not rooms:
            return "🏠 No hay salas configuradas."

        lines = ["🏠 SALAS Y HORARIOS"]
        for name, room in rooms.items():
            next_wave = self.iso(room.get("next"))
            interval = int(room.get("interval", DEFAULT_INTERVAL))
            if room.get("enabled") and next_wave:
                alert = next_wave - timedelta(minutes=5)
                state = "🟢 ACTIVA"
                schedule = f"⏰ Próxima: {self.fmt(next_wave)} | 🔔 Aviso: {self.fmt(alert)}"
            elif room.get("waiting"):
                state = "🟡 ESPERANDO HORA REAL"
                schedule = f"⏰ Prevista: {self.fmt(next_wave)}"
            else:
                state = "⏸️ DETENIDA"
                schedule = "⏰ Sin horario"
            lines.append(
                f"\n{'⭐ ' if name == self.store.d.get('active_room') else '• '}{name} — {state}"
            )
            lines.append(f"   ⏱️ Cada {interval} min | {schedule}")
            lines.append(f"   🔗 {room.get('link', '')}")
        return "\n".join(lines)

    def permissions_text(self):
        names = self.store.d["names"]
        admins = self.store.d["admins"]
        subs = self.store.d["subs"]
        lines = [
            "🔐 PERMISOS GHOST WAVE",
            f"👑 Propietario: @{names.get(self.owner_id, self.owner_id)}",
            "",
            "🛠️ Administradores:",
        ]
        lines += [f"• @{names.get(uid, uid)}" for uid in admins] or ["• Ninguno"]
        lines += ["", "📨 Personas que reciben anuncios:"]
        lines += [f"• @{names.get(uid, uid)}" for uid in subs] or ["• Ninguno"]
        lines += [
            "",
            "ℹ️ Administrador = puede configurar.",
            "ℹ️ Suscrito = recibe anuncios e invitaciones.",
        ]
        return "\n".join(lines)

    def status(self):
        enabled = [n for n, r in self.store.d["rooms"].items() if r.get("enabled")]
        waiting = [n for n, r in self.store.d["rooms"].items() if r.get("waiting")]
        return (
            "👻 GHOST WAVE\n"
            f"🟢 Salas activas: {len(enabled)}\n"
            f"🟡 Esperando confirmación: {len(waiting)}\n"
            f"🏠 Salas configuradas: {len(self.store.d['rooms'])}\n"
            f"📨 Suscritos: {len(self.store.d['subs'])}\n"
            f"🔐 Administradores: {len(self.store.d['admins'])}\n\n"
            + self.room_list()
        )

    def help(self):
        return (
            "👻 GHOST WAVE — AYUDA\n\n"
            "📊 !ghost estado\n"
            "🏠 !ghost salas\n"
            "▶️ !ghost iniciar <sala> HH:MM [min] (última oleada)\n"
            "🕐 !ghost hora <sala> HH:MM\n"
            "⏸️ !ghost parar <sala>\n"
            "▶️ !ghost reanudar\n"
            "⏱️ !ghost intervalo <sala> 75\n"
            "➕ !ghost sala agregar <nombre> <link>\n"
            "✏️ !ghost sala editar <nombre> <link>\n"
            "🗑️ !ghost sala borrar <nombre>\n"
            "⭐ !ghost sala principal <nombre>\n"
            "📨 !ghost usuarios\n"
            "🔐 !ghost permisos\n"
            "🔑 !ghost admin @usuario\n"
            "🔓 !ghost radmin @usuario\n"
            "📩 !ghost suscribir @usuario\n"
            "🔕 !ghost quitar-suscripcion @usuario"
        )

    async def command(self, user_id, message):
        if not message.lower().startswith("!ghost"):
            # Si hay exactamente una sala esperando confirmación, se puede
            # responder solamente con HH:MM. Con varias, se exige indicar sala.
            waiting = [
                name for name, room in self.store.d["rooms"].items()
                if room.get("waiting")
            ]
            if self.admin(user_id) and len(waiting) == 1:
                actual = self.actual_clock(message, waiting[0])
                if actual:
                    return await self.register_actual(waiting[0], actual, user_id)
            return None

        parts = message.split()
        args = parts[1:]
        command = args[0].lower() if args else "ayuda"

        if command in ("ayuda", "help"):
            return self.help()
        if command == "estado":
            if not self.admin(user_id):
                return "🔒 Sin permiso."
            return self.status()
        if command == "salas":
            return self.room_list()
        if command == "permisos":
            if not self.admin(user_id):
                return "🔒 Sin permiso."
            return self.permissions_text()
        if command == "usuarios":
            if not self.admin(user_id):
                return "🔒 Sin permiso."
            return self.permissions_text()

        if command == "iniciar":
            if not self.admin(user_id):
                return "🔒 Sin permiso."
            if len(args) < 3:
                return "Uso: !ghost iniciar <sala> HH:MM [min]"
            name = args[1]
            time_text = args[2]
            interval_index = 3
            if len(args) > 3 and args[3].upper() in ("AM", "PM"):
                time_text += " " + args[3]
                interval_index = 4
            room = self.store.d["rooms"].get(name)
            if not room:
                return "🔎 Sala no encontrada."
            last_wave = self.last_wave_clock(time_text)
            if not last_wave:
                return "🕐 Hora inválida. Usa formato de 12 horas, por ejemplo 10:20."
            interval = int(args[interval_index]) if len(args) > interval_index and args[interval_index].isdigit() else int(room.get("interval", DEFAULT_INTERVAL))
            if interval <= 0:
                return "⏱️ Intervalo inválido."

            next_wave = last_wave + timedelta(minutes=interval)
            now = self.now()
            # Si el cálculo quedó en el pasado, avanzar por intervalos hasta
            # encontrar la próxima oleada que todavía no haya vencido.
            while next_wave <= now:
                next_wave += timedelta(minutes=interval)

            room.update(
                enabled=True, interval=interval, next=next_wave.isoformat(),
                last=last_wave.isoformat(), waiting=False, alerted=False
            )
            self.store.save()
            return (
                f"🟢 {name} iniciada.\n"
                f"🕐 Última oleada: {last_wave:%d/%m %I:%M}\n"
                f"⏰ Próxima estimada: {next_wave:%I:%M}\n"
                f"🔔 Aviso: {(next_wave - timedelta(minutes=5)):%I:%M}\n"
                f"⏱️ Intervalo: {interval} minutos."
            )

        if command in ("parar", "detener", "pausar"):
            if not self.admin(user_id):
                return "🔒 Sin permiso."
            if len(args) != 2:
                return "Uso: !ghost parar <sala>"
            room = self.store.d["rooms"].get(args[1])
            if not room:
                return "🔎 Sala no encontrada."
            room.update(enabled=False, waiting=False, alerted=False)
            self.store.save()
            return f"⏸️ Anuncios detenidos para {args[1]}."

        if command in ("reanudar", "activar"):
            if not self.admin(user_id):
                return "🔒 Sin permiso."
            for room in self.store.d["rooms"].values():
                room.update(enabled=False, waiting=False, alerted=False, next=None)
            self.store.save()
            return "▶️ Sistema listo. Debes configurar nuevamente cada sala con !ghost iniciar."

        if command == "hora":
            if not self.admin(user_id):
                return "🔒 Sin permiso."
            if len(args) not in (3, 4):
                return "Uso: !ghost hora <sala> HH:MM"
            name, time_text = args[1], args[2]
            if len(args) == 4 and args[3].upper() in ("AM", "PM"):
                time_text += " " + args[3]
            if name not in self.store.d["rooms"]:
                return "🔎 Sala no encontrada."
            room = self.store.d["rooms"][name]
            if not room.get("waiting"):
                return (
                    f"ℹ️ {name} ya no está esperando confirmación. "
                    "La hora de esta oleada ya fue registrada."
                )
            actual = self.actual_clock(time_text, name)
            if not actual:
                return "🕐 Hora inválida."
            return await self.register_actual(name, actual, user_id)

        if command == "intervalo":
            if not self.admin(user_id):
                return "🔒 Sin permiso."
            if len(args) != 3 or not args[2].isdigit() or int(args[2]) <= 0:
                return "Uso: !ghost intervalo <sala> 75"
            room = self.store.d["rooms"].get(args[1])
            if not room:
                return "🔎 Sala no encontrada."
            room["interval"] = int(args[2])
            self.store.save()
            return f"⏱️ {args[1]} ahora usa {args[2]} minutos."

        if command in ("admin", "radmin", "suscribir", "quitar-suscripcion"):
            if not self.owner(user_id):
                return "🔒 Solo el propietario puede administrar accesos."
            if len(args) != 2:
                return "Uso: !ghost admin|radmin|suscribir|quitar-suscripcion @usuario"
            found = await self.find_user(args[1])
            if not found:
                return "🔎 Usuario no encontrado."
            target_id, username = found
            self.store.d["names"][target_id] = username

            if command == "admin":
                self.store.d["admins"] = sorted(set(self.store.d["admins"] + [target_id]))
                reply = f"🔐 @{username} puede configurar el bot."
            elif command == "radmin":
                self.store.d["admins"] = [x for x in self.store.d["admins"] if x != target_id]
                reply = f"🔓 @{username} ya no puede configurar el bot."
            elif command == "suscribir":
                self.store.d["subs"] = sorted(set(self.store.d["subs"] + [target_id]))
                reply = f"📨 @{username} recibirá los anuncios por buzón."
            else:
                self.store.d["subs"] = [x for x in self.store.d["subs"] if x != target_id]
                reply = f"🔕 @{username} ya no recibirá anuncios."

            self.store.save()
            return reply

        if command == "sala":
            if not self.admin(user_id):
                return "🔒 Sin permiso."
            if len(args) < 2:
                return self.room_list()

            action = args[1].lower()

            if action in ("agregar", "editar") and len(args) >= 4:
                name, link = args[2], args[3]
                room_id = self.extract_room_id(link)
                if not room_id:
                    return "🔗 Link de sala inválido."
                old = self.store.d["rooms"].get(name, {})
                self.store.d["rooms"][name] = {
                    **old,
                    "name": name,
                    "link": link,
                    "room_id": room_id,
                    "enabled": old.get("enabled", False),
                    "interval": int(old.get("interval", DEFAULT_INTERVAL)),
                    "next": old.get("next"),
                    "last": old.get("last"),
                    "waiting": old.get("waiting", False),
                    "alerted": old.get("alerted", False),
                }
                self.store.save()
                return f"🏠 Sala '{name}' guardada/actualizada."

            if action in ("borrar", "eliminar") and len(args) == 3:
                name = args[2]
                room = self.store.d["rooms"].get(name)
                if not room:
                    return "🔎 Sala no encontrada."
                if room.get("enabled") or room.get("waiting"):
                    return (
                        "⚠️ Esa sala tiene un horario activo o esperando confirmación. "
                        "Primero usa !ghost parar " + name
                    )
                del self.store.d["rooms"][name]
                self.store.save()
                return f"🗑️ Sala '{name}' eliminada."

            if action == "principal" and len(args) == 3:
                name = args[2]
                if name not in self.store.d["rooms"]:
                    return "🔎 Sala no encontrada."
                self.store.d["active_room"] = name
                self.store.save()
                return f"⭐ Sala principal: {name}"

            return "🏠 Uso: agregar, editar, borrar o principal."

        return "❓ Usa !ghost ayuda."

    async def register_actual(self, room_name, actual, confirmer_id):
        room = self.store.d["rooms"][room_name]
        if not room.get("waiting"):
            confirmed_by = room.get("confirmed_by")
            confirmed_at = self.iso(room.get("last"))
            name = self.store.d["names"].get(confirmed_by, confirmed_by or "otro administrador")
            when = confirmed_at.strftime("%I:%M") if confirmed_at else "--:--"
            return (
                f"ℹ️ {room_name} ya fue confirmada por @{name} a las {when}.\n"
                "La primera confirmación es la que se utiliza para calcular la próxima oleada."
            )

        interval = int(room.get("interval", DEFAULT_INTERVAL))
        next_wave = actual + timedelta(minutes=interval)
        confirmer_name = self.store.d["names"].get(confirmer_id, confirmer_id)
        room.update(
            last=actual.isoformat(),
            next=next_wave.isoformat(),
            enabled=True,
            waiting=False,
            alerted=False,
            confirmed_by=confirmer_id,
        )
        self.store.d["names"].setdefault(confirmer_id, confirmer_name)
        self.store.save()

        admins = list(dict.fromkeys([self.owner_id] + self.store.d["admins"]))
        others = [uid for uid in admins if uid != confirmer_id]
        if others:
            await self.broadcast(
                others,
                f"👻 Oleada confirmada\n"
                f"🏠 Sala: {room_name}\n"
                f"👤 @{confirmer_name} ya configuró la hora de activación: {actual:%I:%M}.\n"
                f"🔮 Próxima oleada: {next_wave:%I:%M}\n"
                f"🔔 Aviso: {(next_wave - timedelta(minutes=5)):%I:%M}\n"
                "ℹ️ No es necesario volver a configurar esta oleada."
            )

        return (
            f"✅ {room_name}: activación real {actual:%I:%M}.\n"
            f"👻 Próxima: {next_wave:%I:%M}\n"
            f"🔔 Aviso: {(next_wave - timedelta(minutes=5)):%I:%M}\n"
            f"⏱️ Intervalo: {interval} minutos."
        )

    async def send_invite(self, user_id, room):
        conversation_id = self.store.d["conversations"].get(user_id)
        room_id = room.get("room_id")
        if not conversation_id or not room_id:
            return
        try:
            result = await self.highrise.send_message(
                conversation_id,
                f"👻 Invitación: {room['name']}",
                "invite",
                room_id,
            )
            if result is not None:
                print("[GHOST] invite rejected:", result)
        except Exception as e:
            print("[GHOST] invite:", e)

    async def scheduler(self):
        while True:
            try:
                now = self.now()
                for name, room in list(self.store.d["rooms"].items()):
                    if not room.get("enabled") or room.get("waiting"):
                        continue

                    next_wave = self.iso(room.get("next"))
                    if not next_wave:
                        continue

                    alert_at = next_wave - timedelta(minutes=5)

                    if not room.get("alerted") and now >= alert_at:
                        recipients = self.store.d["subs"] + [self.owner_id]
                        message = (
                            "👻 OLEADA EN 5 MINUTOS\n"
                            f"🏠 Sala: {name}\n"
                            f"⏰ Hora prevista: {next_wave:%I:%M}\n"
                            f"🔗 {room.get('link', '')}\n\n"
                            "¡Prepárate para entrar!"
                        )
                        await self.broadcast(recipients, message)
                        for user_id in list(dict.fromkeys(recipients)):
                            await self.send_invite(user_id, room)
                            await asyncio.sleep(0.15)

                        room["alerted"] = True
                        self.store.save()

                    if now >= next_wave and not room.get("waiting"):
                        admins = [self.owner_id] + self.store.d["admins"]
                        await self.broadcast(
                            admins,
                            "👻 ¡CONFIRMA LA OLEADA!\n"
                            f"🏠 Sala: {name}\n"
                            f"⏰ Estaba prevista para {next_wave:%I:%M}.\n\n"
                            f"Responde: !ghost hora {name} HH:MM\n"
                            "Si solo hay una sala esperando, también puedes responder HH:MM."
                        )
                        room["waiting"] = True
                        self.store.save()

                await asyncio.sleep(2)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print("[GHOST] scheduler:", e)
                await asyncio.sleep(5)

    async def on_start(self, session_metadata: SessionMetadata):
        self.bot_id = session_metadata.user_id
        self.owner_id = session_metadata.room_info.owner_id
        self.store.d["names"].setdefault(self.owner_id, "Propietario")
        if self.owner_id not in self.store.d["subs"]:
            self.store.d["subs"].append(self.owner_id)
        self.store.save()
        self.task = asyncio.create_task(self.scheduler())
        print(
            f"[GHOST] conectado bot={self.bot_id} "
            f"owner={self.owner_id} tz={self.tz.key}"
        )

    async def on_message(self, user_id, conversation_id, is_new_conversation):
        try:
            self.store.d["conversations"][user_id] = conversation_id

            # Guardar el username real de cualquiera que escriba al bot,
            # para poder asignarle permisos aunque la búsqueda WebAPI falle.
            try:
                profile = await self.webapi.get_user(user_id)
                username = getattr(profile.user, "username", None)
                if username:
                    self.store.d["names"][user_id] = username
            except Exception as e:
                print("[GHOST] profile lookup:", e)

            self.store.save()

            conversation = await self.highrise.get_messages(conversation_id)
            if not conversation.messages:
                return

            response = await self.command(user_id, conversation.messages[0].content.strip())
            if response:
                await self.highrise.send_message(conversation_id, response)
        except Exception as e:
            print("[GHOST] message:", e)

    async def on_chat(self, user, message):
        return


async def main():
    room_id = os.getenv("GHOST_WAVE_ROOM_ID", "").strip()
    api_key = os.getenv("GHOST_WAVE_API_KEY", "").strip()
    if not room_id or not api_key:
        raise RuntimeError("Faltan GHOST_WAVE_ROOM_ID/GHOST_WAVE_API_KEY")
    await highrise_main([BotDefinition(Bot(), room_id, api_key)])


if __name__ == "__main__":
    asyncio.run(main())
