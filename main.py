from highrise import BaseBot, __main__, CurrencyItem, GetMessagesRequest, Item, Position, AnchorPosition, Reaction, SessionMetadata, User
from highrise.__main__ import BotDefinition
from asyncio import run as arun
from json import load
import asyncio
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from random import choice, randint
from threading import Thread
from config import (
    API_KEY,
    DATA_FILE,
    DEFAULT_DATA,
    EMOTES_FILE,
    POSITIONS_FILE,
    ROOM_ID,
    ROLES_FILE,
)
from commands.owner import handle_owner_command
from commands.dispatcher import CommandDispatcher
from services.positions import PositionManager
from services.roles import RoleManager, get_user_role
from services.emotes import EmotesManager
from services.track import handle_track_command, start_track_monitor
from services.storage import load_json
from services.youtube import YouTubeSearchError, search_youtube
from services.radio import RadioRequestError, request_playback
from tips import TipManager
from anuncios import announcement_loop
from diversion import handle_diversion_command


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/health":
            self.send_error(404)
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok\n")

    def log_message(self, *_):
        return


def start_health_server():
    port = int(os.environ.get("PORT", "10000"))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()


class Bot(BaseBot):
    def __init__(self):
        super().__init__()
        self.bot_id = None
        self.owner_id = None
        self.bot_status = False
        self.tip_manager = TipManager(DATA_FILE)
        self.position_manager = PositionManager(POSITIONS_FILE, DATA_FILE)
        self.role_manager = RoleManager(ROLES_FILE)
        self.command_dispatcher = CommandDispatcher()
        self.bot_position = None
        self.user_positions = {}
        self.track_monitor_task = None
        self.track_emote_tasks = {}

        # Estado de seguimiento
        self.following = False
        self.follow_task = None
        self.emote_tasks = {}
        self.botdance_task = None
        self.position_task = None
        self.reset_task = None
        self.announcement_task = None
        self.fight_tasks = set()
        self.current_bot_emote = None
        self.current_bot_emote_duration = 0
        
        # Cargar lista de emotes desde emotes.json
        self.emotes_list = self.load_emotes_data()
        self.emotes_manager = EmotesManager(self.emotes_list)

    def load_emotes_data(self):
        """Carga la configuración de emotes desde el archivo JSON."""
        try:
            with open(EMOTES_FILE, "r", encoding="utf-8") as file:
                emotes = load(file)
            normalized_emotes = []
            for emote in emotes:
                if not isinstance(emote, dict):
                    continue
                emote_id = emote.get("emote", emote.get("id"))
                command = emote.get("command", emote.get("name"))
                if not emote_id or not command:
                    continue
                normalized_emotes.append({
                    "command": str(command).strip(),
                    "emote": str(emote_id),
                    "duration": max(float(emote.get("duration", 1)), 0.1),
                    "auth": emote.get("auth", "public"),
                })
            return normalized_emotes
        except (OSError, TypeError, ValueError) as error:
            print(f"Error al cargar emotes.json: {error}")
            return []

    async def get_command_help(self, user: User) -> list[str]:
        role = await self.role_manager.get_user_role(self, user)
        sections = [
            "\n".join([
                "<#66CCFF>🎭 EMOTES",
                "<#FFFFFF>• !random - Emotes aleatorios para ti",
                "<#FFFFFF>• !stop - Detener tu emote",
                "<#FFFFFF>• !help - Mostrar esta ayuda",
            ]),
            "\n".join([
                "<#66CCFF>🎉 DIVERSIÓN",
                "<#FFFFFF>• !fight @usuario - Pelear con emotes",
                "<#FFFFFF>• !kiss @usuario - Enviar un beso",
                "<#FFFFFF>• !heart @usuario - Enviar un corazón",
                "<#FFFFFF>• !love @usuario - Calcular compatibilidad",
                "<#FFFFFF>• !superpunch @usuario - Lanzar un superpunch",
            ]),
            "\n".join([
                "<#66FF99>📍 MOVIMIENTO",
                "<#FFFFFF>• !tele @usuario - Ir junto a un usuario",
                "<#FFFFFF>• !follow - Seguir al dueño",
                "<#FFFFFF>• !stopfollow - Dejar de seguir al dueño",
            ]),
            "\n".join([
                "<#FFCC66>💰 PROPINAS",
                "<#FFFFFF>• !top - Ranking de propinas",
                "<#FFFFFF>• !wallet - Ver la billetera del bot",
                "<#FFFFFF>• !get @usuario - Ver sus propinas",
            ]),
            "\n".join([
                "<#CC99FF>👤 INFORMACIÓN",
                "<#FFFFFF>• !userinfo @usuario - Ver información",
                "<#FFFFFF>• !play canción - Añadir música a la radio",
            ]),
        ]

        if role in ("owner", "mod"):
            sections.extend([
                "\n".join([
                    "<#FF66CC>🛡️ MODERACIÓN",
                    "<#FFFFFF>• !kick @usuario - Expulsar un usuario",
                    "<#FFFFFF>• !tp @usuario x y z - Teletransportar un usuario",
                    "<#FFFFFF>• !botdance - Activar baile del bot",
                    "<#FFFFFF>• !stopbotdance - Detener baile del bot",
                    "<#FFFFFF>• !randomall - Activar emotes para todos",
                ]),
                "\n".join([
                    "<#FFCC66>🎁 ENVÍO DE PROPINAS",
                    "<#FFFFFF>• !tipme cantidad - Enviarte oro",
                    "<#FFFFFF>• !tip @usuario cantidad - Enviar oro",
                    "<#FFFFFF>• !tipall cantidad - Enviar a todos",
                    "<#FFFFFF>• !tip all cantidad - Alias de !tipall",
                ]),
            ])

        if role == "owner":
            sections.extend([
                "\n".join([
                    "<#CC99FF>⚙️ ADMINISTRACIÓN",
                    "<#FFFFFF>• !set - Guardar la posición del bot",
                    "<#FFFFFF>• !home - Volver a la posición guardada",
                    "<#FFFFFF>• !reset - Reiniciar el bot",
                    "<#FFFFFF>• !role @usuario mod|vip|user - Administrar roles",
                ]),
                "\n".join([
                    "<#FFFFFF>👕 VESTUARIO",
                    "<#FFFFFF>• !color categoría número - Cambiar color",
                    "<#FFFFFF>• !equip nombre - Equipar una prenda",
                    "<#FFFFFF>• /remove categoría - Quitar una categoría",
                    "<#FFFFFF>• /getoutfit - Ver el vestuario",
                ]),
            ])

        return sections

    async def is_mod(self, user_id: str) -> bool:
        """Verifica si un usuario posee rol de moderador o superior."""
        if user_id == self.owner_id:
            return True
        try:
            permissions = await self.highrise.get_room_privilege(user_id)
            return bool(getattr(permissions, "moderator", False))
        except Exception as error:
            print(f"Error comprobando permisos de {user_id}: {error}")
            return False

    async def get_user_id(self, username: str) -> str | None:
        """Busca el ID de un usuario por su nombre de usuario en la sala."""
        room_users = await self.highrise.get_room_users()
        for room_user, _ in room_users.content:
            if room_user.username.lower() == username.lower():
                return room_user.id
        return None

    async def get_user_position(self, user_id: str) -> Position | None:
        """Obtiene la posición actual de un usuario en la sala."""
        room_users = await self.highrise.get_room_users()
        for room_user, position in room_users.content:
            if room_user.id == user_id:
                return position
        return None

    async def emote_loop(self, user_id: str, emote_id: str, duration: float):
        """Bucle continuo para ejecutar un emote en un usuario."""
        while True:
            try:
                await self.highrise.send_emote(emote_id, user_id)
                await asyncio.sleep(duration)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error enviando emote a {user_id}: {e}")
                await asyncio.sleep(2)

    async def random_emote_loop(self, user_id: str):
        """Ejecuta un bucle de emotes aleatorios sobre un usuario."""
        while True:
            try:
                random_emote = choice(self.emotes_list)
                await self.highrise.send_emote(random_emote["emote"], user_id)
                await asyncio.sleep(random_emote.get("duration", 3))
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error enviando emote aleatorio a {user_id}: {e}")
                await asyncio.sleep(2)

    async def random_dance_loop(self):
        """Ejecuta bailes aleatorios continuos únicamente para el bot."""
        public_emotes = [
            emote for emote in self.emotes_list
            if isinstance(emote, dict)
            and emote.get("auth") == "public"
            and isinstance(emote.get("emote"), str)
        ]
        if not public_emotes:
            print("No hay emotes públicos válidos para el baile automático.")
            return

        while True:
            try:
                random_emote = choice(public_emotes)
                self.current_bot_emote = random_emote["emote"]
                self.current_bot_emote_duration = random_emote.get("duration", 3)
                await self.highrise.send_emote(self.current_bot_emote, self.bot_id)
                await asyncio.sleep(self.current_bot_emote_duration)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error en el baile del bot: {e}")
                await asyncio.sleep(2)

    async def follow_owner_loop(self):
        """Bucle para hacer que el bot siga la posición del dueño."""
        while self.following:
            try:
                owner_pos = await self.get_user_position(self.owner_id)
                if owner_pos and isinstance(owner_pos, Position):
                    bot_pos = Position(owner_pos.x + 1, owner_pos.y, owner_pos.z, owner_pos.facing)
                    await self.highrise.walk_to(bot_pos)
                await asyncio.sleep(2)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error en follow_owner_loop: {e}")
                await asyncio.sleep(2)

    async def restart_process(self):
        """Reinicia el proceso del bot de forma limpia."""
        await asyncio.sleep(1)
        os._exit(0)

    async def place_bot(self):
        await asyncio.sleep(5)
        try:
            self.bot_position = self.position_manager.get_bot_position()
            if self.bot_position != Position(0, 0, 0, "FrontRight"):
                await self.highrise.teleport(self.bot_id, self.bot_position)
                print(f"[POSITION] Bot restaurado en {self.bot_position}.")
        except Exception as error:
            print(f"Error restaurando la posición del bot: {error}")

    async def on_start(self, session_metadata: SessionMetadata) -> None:
        self.bot_id = session_metadata.user_id
        self.owner_id = session_metadata.room_info.owner_id
        self.bot_status = True
        print(f"Bot conectado exitosamente. Bot ID: {self.bot_id} | Owner ID: {self.owner_id}")

        await self.highrise.chat(
            "<#66FF99>🤖 ¡Bot conectado! Escribe !help para ver los comandos."
        )
        if self.position_task:
            self.position_task.cancel()
        self.position_task = asyncio.create_task(self.place_bot())
        if self.botdance_task:
            self.botdance_task.cancel()
        self.botdance_task = asyncio.create_task(self.random_dance_loop())
        if self.announcement_task:
            self.announcement_task.cancel()
        self.announcement_task = asyncio.create_task(announcement_loop(self))
        try:
            positions = load_json(self.position_manager.positions_file)
            if positions.get("pista_emotes"):
                await start_track_monitor(self)
        except (AttributeError, TypeError, ValueError) as error:
            print(f"No se pudo iniciar el monitor de pista: {error}")

    async def on_chat(self, user: User, message: str) -> None:
        msg = message.strip()
        msg_lower = msg.lower()

        command_name = msg.split(maxsplit=1)[0].lower() if msg else ""
        if command_name in self.command_dispatcher.handlers:
            response = await self.command_dispatcher.handle(self, user, msg)
            if isinstance(response, list):
                for section in response:
                    await self.highrise.send_whisper(user.id, section)
            elif response:
                await self.highrise.send_whisper(user.id, response)
            return

        if await handle_track_command(self, user, message):
            return

        if msg_lower.startswith(("!play", "/play")):
            query = msg[5:].strip()
            if not query:
                await self.highrise.send_whisper(
                    user.id, "<#FFCC66>🎵 Uso: !play nombre de la canción"
                )
                return
            try:
                video = await asyncio.to_thread(search_youtube, query)
                try:
                    await request_playback(
                        video["video_id"],
                        {
                            "title": video["title"],
                            "channel": video["channel"],
                            "url": video["url"],
                        },
                    )
                    playback_message = "<#66FF99>▶️ Solicitud enviada a la radio."
                except RadioRequestError as error:
                    playback_message = f"<#FFCC66>ℹ️ {error}"
                await self.highrise.chat(
                    f"<#66FF99>🎵 @{user.username} encontró: {video['title']} "
                    f"({video['channel']})\n{playback_message}"
                )
                await self.highrise.send_whisper(
                    user.id,
                    "<#66FF99>🔎 Resultado encontrado:\n"
                    f"<#FFFFFF>🎵 {video['title']}\n"
                    f"<#CC99FF>👤 {video['channel']}\n"
                    f"<#66CCFF>🔗 {video['url']}\n"
                    "<#FFCC66>ℹ️ Solicitud añadida a la cola de reproducción.",
                )
            except YouTubeSearchError as error:
                await self.highrise.send_whisper(
                    user.id, f"<#FF6666>⚠️ {error}"
                )
            return

        if msg_lower == "!reset":
            if user.id == self.owner_id or await self.is_mod(user.id):
                if not self.reset_task:
                    await self.highrise.chat(
                        "<#FF6666>🔄 El bot se reiniciará en un momento..."
                    )
                    self.reset_task = asyncio.create_task(self.restart_process())
            else:
                await self.highrise.send_whisper(
                    user.id, "🔒 Solo el dueño o los moderadores pueden reiniciar el bot."
                )
            return

        if msg_lower in ["!stop", "stop"]:
            emote_task = self.emote_tasks.pop(user.id, None)
            if emote_task:
                emote_task.cancel()
            track_task = self.track_emote_tasks.pop(user.id, None)
            if track_task:
                track_task.cancel()
            try:
                await self.highrise.send_emote("", user.id)
            except Exception as error:
                print(f"No se pudo detener el emote de {user.id}: {error}")
            await self.highrise.send_whisper(
                user.id, "<#FF6666>🛑 Tu emote se detuvo."
            )
            return

        # ==========================================
        # 2. SEGUIR AL DUEÑO (!follow / !stopfollow)
        # ==========================================
        elif msg_lower == "!follow":
            if user.id == self.owner_id or await self.is_mod(user.id):
                if not self.following:
                    self.following = True
                    self.follow_task = asyncio.create_task(self.follow_owner_loop())
                    await self.highrise.chat("<#66FF99>🧭 ¡Ya voy contigo!")
                else:
                    await self.highrise.chat("<#FFCC66>🧭 Ya te estaba siguiendo.")
            else:
                await self.highrise.send_whisper(
                    user.id, "🔒 Solo el dueño de la sala puede usar este comando."
                )
            return

        elif msg_lower == "!stopfollow":
            if user.id == self.owner_id or await self.is_mod(user.id):
                if self.following:
                    self.following = False
                    if self.follow_task:
                        self.follow_task.cancel()
                    await self.highrise.chat("<#66CCFF>🛑 Dejé de seguirte.")
                else:
                    await self.highrise.chat("<#FFCC66>🧭 No te estaba siguiendo.")
            else:
                await self.highrise.send_whisper(
                    user.id, "🔒 Solo el dueño de la sala puede usar este comando."
                )
            return

        # ==========================================
        # 3. INVOCACIÓN (!summon @usuario)
        # ==========================================
        elif msg_lower.startswith("!summon "):
            if user.id == self.owner_id or await self.is_mod(user.id):
                parts = msg.split(" ")
                if len(parts) >= 2:
                    target_username = parts[1].replace("@", "")
                    target_id = await self.get_user_id(target_username)
                    if target_id:
                        caller_pos = await self.get_user_position(user.id)
                        if caller_pos:
                            await self.highrise.teleport(target_id, caller_pos)
                            await self.highrise.send_whisper(
                                user.id,
                                f"<#66CCFF>🌀 @{target_username} ha sido invocado/a."
                            )
                        else:
                            await self.highrise.send_whisper(
                                user.id, "<#FF6666>⚠️ No pude obtener tu posición actual."
                            )
                    else:
                        await self.highrise.send_whisper(
                            user.id, "<#FFCC66>🔎 Usuario no encontrado en la sala."
                        )
            else:
                await self.highrise.send_whisper(
                    user.id, "🔒 No tienes permisos para invocar usuarios."
                )
            return

        if await handle_diversion_command(self, user, msg):
            return

        # ==========================================
        # 4. TELETRANSPORTE A USUARIO (!tele @usuario)
        # ==========================================
        if msg_lower.startswith("!tele "):
            parts = msg.split()
            if len(parts) != 2 or not parts[1].startswith("@"):
                await self.highrise.send_whisper(user.id, "📍 Uso: !tele @usuario")
                return

            target_username = parts[1][1:]
            target_id = await self.get_user_id(target_username)
            if not target_id:
                await self.highrise.send_whisper(
                    user.id, "<#FFCC66>🔎 Usuario no encontrado en la sala."
                )
                return

            target_position = await self.get_user_position(target_id)
            if not target_position:
                await self.highrise.send_whisper(
                    user.id, "<#FF6666>📍 No pude obtener la posición del usuario."
                )
                return

            await self.highrise.teleport(user.id, target_position)
            await self.highrise.send_whisper(
                user.id,
                f"<#66FF99>📍 ¡Te has reunido con @{target_username}!"
            )
            return

        # ==========================================
        # 5. SUPERPUNCH PUBLICO (!superpunch @usuario)
        # ==========================================
        if msg_lower.startswith("!superpunch "):
            parts = msg.split()
            if len(parts) != 2 or not parts[1].startswith("@"):
                await self.highrise.send_whisper(user.id, "🥊 Uso: !superpunch @usuario")
                return

            target_username = parts[1][1:]
            target_id = await self.get_user_id(target_username)
            if not target_id:
                await self.highrise.send_whisper(
                    user.id, "<#FFCC66>🔎 Usuario no encontrado en la sala."
                )
                return
            if target_id == self.bot_id:
                await self.highrise.send_whisper(
                    user.id, "<#FF6666>🛡️ El bot tiene un escudo activo: no puedes golpearlo."
                )
                return

            target_position = await self.get_user_position(target_id)
            if not target_position:
                await self.highrise.send_whisper(
                    user.id, "<#FF6666>📍 No pude localizar a ese usuario."
                )
                return

            offset_x = randint(-8, 8)
            offset_z = randint(-8, 8)
            while offset_x ** 2 + offset_z ** 2 < 16:
                offset_x = randint(-8, 8)
                offset_z = randint(-8, 8)

            nearby_position = Position(
                target_position.x + offset_x,
                target_position.y,
                target_position.z + offset_z,
                facing=target_position.facing,
            )
            await self.highrise.teleport(target_id, nearby_position)
            if self.botdance_task:
                self.botdance_task.cancel()
            self.botdance_task = asyncio.create_task(self.random_dance_loop())
            await self.highrise.send_emote("emoji-punch", user.id)
            await self.highrise.send_emote("emote-fail1", target_id)
            await self.highrise.chat(
                f"<#FFCC66>🥊 @{user.username} lanzó un superpunch contra @{target_username}! 💥"
            )
            return

        # ==========================================
        # 9. TELETRANSPORTE A POSICIONES GUARDADAS
        # ==========================================
        if len(msg.split()) == 1:
            position_name = msg_lower[1:] if msg_lower.startswith("!") else msg_lower
            position_data = self.position_manager.get_named_position_data(position_name)
            if position_data:
                if position_data.get("access") == "priv" and not await self.position_manager.can_use_private_position(self, user):
                    await self.highrise.send_whisper(
                        user.id, "🔒 No tienes permiso para usar esta posición."
                    )
                    return
                try:
                    await self.highrise.teleport(user.id, self.position_manager.position_from_data(position_data))
                    await self.highrise.send_whisper(
                        user.id,
                        f"<#66FF99>📍 ¡Has llegado a {position_name}!"
                    )
                except Exception as e:
                    print(f"Error al teletransportar a {position_name}: {e}")
                    await self.highrise.send_whisper(
                        user.id, "<#FF6666>⚠️ No se pudo realizar el teletransporte."
                    )
                return

        # ==========================================
        # 10. COMANDOS DE EMOTES (Cargados desde emotes.json)
        # ==========================================
        emote_text = msg_lower[1:].strip() if msg_lower.startswith("!") else msg_lower
        if emote_text.startswith("/emote "):
            emote_text = emote_text[7:].strip()
        emote_parts = emote_text.split()
        target_username = None
        if len(emote_parts) > 1 and emote_parts[-1].startswith("@"):
            target_username = emote_parts.pop()[1:]
            emote_text = " ".join(emote_parts)

        if emote_text == "random":
            target_id = user.id
            if target_username:
                target_id = await self.get_user_id(target_username)
                if not target_id:
                    await self.highrise.chat("Usuario no encontrado en la sala.")
                    return

            previous_task = self.emote_tasks.pop(target_id, None)
            if previous_task:
                previous_task.cancel()
            self.emote_tasks[target_id] = asyncio.create_task(
                self.random_emote_loop(target_id)
            )
            await self.highrise.send_whisper(
                user.id,
                "<#66CCFF>🎲 Emotes aleatorios activados. Escribe !stop para detenerlos.",
            )
            return

        matched_emote = None
        if emote_text.isdigit():
            emote_index = int(emote_text) - 1
            matched_emote = self.emotes_manager.get_by_index(emote_index)
        else:
            matched_emote = self.emotes_manager.get_by_name(emote_text)

        if matched_emote:
            if matched_emote.get("auth") == "vip" and not await self.is_mod(user.id) and user.id != self.owner_id:
                await self.highrise.send_whisper(
                    user.id,
                    "<#FF6666>🔒 Este emote es exclusivo para moderadores o dueños."
                )
                return

            target_id = user.id
            if target_username:
                target_id = await self.get_user_id(target_username)
                if not target_id:
                    await self.highrise.send_whisper(
                        user.id, "<#FFCC66>🔎 Usuario no encontrado en la sala."
                    )
                    return

            previous_task = self.emote_tasks.pop(target_id, None)
            if previous_task:
                previous_task.cancel()
            self.emote_tasks[target_id] = asyncio.create_task(
                self.emote_loop(
                    target_id,
                    matched_emote["emote"],
                    matched_emote.get("duration", 1),
                )
            )
            await self.highrise.send_whisper(
                user.id,
                f"<#66FF99>✨ Emote activado: {matched_emote['command']}. Escribe !stop para detenerlo.",
            )
            return

        # ==========================================
        # 11. COMANDO PROPIO DEL BOT (!botdance / !stopbotdance)
        # ==========================================
        if msg_lower == "!botdance":
            if user.id == self.owner_id or await self.is_mod(user.id):
                if self.botdance_task:
                    self.botdance_task.cancel()
                self.botdance_task = asyncio.create_task(self.random_dance_loop())
                await self.highrise.chat("<#66FF99>💃 ¡Bailes aleatorios activados! 🎶")
            else:
                await self.highrise.send_whisper(
                    user.id, "🔒 Solo el dueño o los moderadores pueden usar este comando."
                )
            return

        if msg_lower == "!stopbotdance":
            if user.id == self.owner_id or await self.is_mod(user.id):
                if self.botdance_task:
                    self.botdance_task.cancel()
                    self.botdance_task = None
                self.current_bot_emote = None
                self.current_bot_emote_duration = 0
                await self.highrise.send_emote("", self.bot_id)
                await self.highrise.chat("<#66CCFF>🛑 Los bailes del bot se detuvieron.")
            else:
                await self.highrise.send_whisper(
                    user.id, "🔒 Solo el dueño puede detener los bailes del bot."
                )
            return

        # ==========================================
        # 12. MODERACIÓN (KICK Y TP)
        # ==========================================
        elif msg_lower.startswith("!kick "):
            if await self.is_mod(user.id):
                parts = msg.split(" ")
                if len(parts) >= 2:
                    target_username = parts[1].replace("@", "")
                    target_id = await self.get_user_id(target_username)
                    if target_id:
                        await self.highrise.moderate_room(target_id, "kick")
                        await self.highrise.chat(
                            f"<#FF6666>🚪 @{target_username} ha sido expulsado/a de la sala."
                        )
                    else:
                        await self.highrise.send_whisper(
                            user.id, "<#FFCC66>🔎 Usuario no encontrado en la sala."
                        )
            else:
                await self.highrise.send_whisper(
                    user.id, "🔒 No tienes permisos de moderación."
                )
            return

        elif msg_lower.startswith("!tp "):
            if await self.is_mod(user.id):
                parts = msg.split(" ")
                if len(parts) == 5:
                    target_username = parts[1].replace("@", "")
                    try:
                        x, y, z = float(parts[2]), float(parts[3]), float(parts[4])
                        target_id = await self.get_user_id(target_username)
                        if target_id:
                            await self.highrise.teleport(target_id, Position(x, y, z))
                            await self.highrise.send_whisper(
                                user.id,
                                f"<#66CCFF>📍 @{target_username} fue teletransportado/a."
                            )
                        else:
                            await self.highrise.send_whisper(
                                user.id, "<#FFCC66>🔎 Usuario no encontrado en la sala."
                            )
                    except ValueError:
                        await self.highrise.send_whisper(
                            user.id, "<#FFCC66>📐 Coordenadas inválidas. Usa números."
                        )
            else:
                await self.highrise.send_whisper(
                    user.id, "🔒 No tienes permisos de moderación."
                )
            return

        response = await self.command_handler(user.id, message)
        if response:
            await self.highrise.send_whisper(user.id, response)
        return

    async def command_handler(self, user_id: str, message: str) -> str | None:
        command = message.lower().strip()
        if not command or (user_id != self.owner_id and not await self.is_mod(user_id)):
            return None
        if command.startswith("!tip all "):
            command = "!tipall " + command[len("!tip all "):]

        owner_response = await handle_owner_command(self, command, user_id)
        if owner_response:
            return owner_response
        return await self.tip_manager.handle_command(self, command, user_id)

if __name__ == "__main__":
    if not ROOM_ID or not API_KEY:
        raise RuntimeError("ROOM_ID y API_KEY deben estar configuradas en el entorno")
    Thread(target=start_health_server, daemon=True).start()
    definitions = [BotDefinition(Bot(), ROOM_ID, API_KEY)]
    arun(__main__.main(definitions))