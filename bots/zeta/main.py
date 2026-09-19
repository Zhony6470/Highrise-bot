from highrise import BaseBot, __main__, CurrencyItem, GetMessagesRequest, Item, Position, AnchorPosition, Reaction, SessionMetadata, User
from highrise.__main__ import BotDefinition
from asyncio import run as arun
from json import load
import asyncio
import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
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
from services.track import start_track_monitor
from services.storage import load_json
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
        """Carga la configuraciÃ³n de emotes desde el archivo JSON."""
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
                "<#66CCFF>ðŸŽ­ EMOTES",
                "<#FFFFFF>â€¢ !random - Emotes aleatorios para ti",
                "<#FFFFFF>â€¢ !stop - Detener tu emote",
                "<#FFFFFF>â€¢ !help - Mostrar esta ayuda",
            ]),
            "\n".join([
                "<#66CCFF>ðŸŽ‰ DIVERSIÃ“N",
                "<#FFFFFF>â€¢ !fight @usuario - Pelear con emotes",
                "<#FFFFFF>â€¢ !kiss @usuario - Enviar un beso",
                "<#FFFFFF>â€¢ !heart @usuario - Enviar un corazÃ³n",
                "<#FFFFFF>â€¢ !love @usuario - Calcular compatibilidad",
                "<#FFFFFF>â€¢ !superpunch @usuario - Lanzar un superpunch",
            ]),
            "\n".join([
                "<#66FF99>ðŸ“ MOVIMIENTO",
                "<#FFFFFF>â€¢ !tele @usuario - Ir junto a un usuario",
                "<#FFFFFF>â€¢ !follow - Seguir al dueÃ±o",
                "<#FFFFFF>â€¢ !stopfollow - Dejar de seguir al dueÃ±o",
            ]),
            "\n".join([
                "<#FFCC66>ðŸ’° PROPINAS",
                "<#FFFFFF>â€¢ !top - Ranking de propinas",
                "<#FFFFFF>â€¢ !wallet - Ver la billetera del bot",
                "<#FFFFFF>â€¢ !get @usuario - Ver sus propinas",
            ]),
            "\n".join([
                "<#CC99FF>ðŸ‘¤ INFORMACIÃ“N",
                    "<#FFFFFF>â€¢ !userinfo - Ver tu informaciÃ³n",
                "<#FFFFFF>â€¢ !userinfo @usuario - Ver informaciÃ³n de otro usuario",
                "<#FFFFFF>â€¢ !help - Mostrar la ayuda disponible",
            ]),
        ]

        if role in ("owner", "mod"):
            sections.extend([
                "\n".join([
                    "<#FF66CC>ðŸ›¡ï¸ MODERACIÃ“N",
                    "<#FFFFFF>â€¢ !kick @usuario - Expulsar un usuario",
                    "<#FFFFFF>â€¢ !tp @usuario x y z - Teletransportar un usuario",
                    "<#FFFFFF>â€¢ !botdance - Activar baile del bot",
                    "<#FFFFFF>â€¢ !stopbotdance - Detener baile del bot",
                    "<#FFFFFF>â€¢ !randomall - Activar emotes para todos",
                ]),
                "\n".join([
                    "<#FFCC66>ðŸŽ ENVÃO DE PROPINAS",
                    "<#FFFFFF>â€¢ !tipme cantidad - Enviarte oro",
                    "<#FFFFFF>â€¢ !tip @usuario cantidad - Enviar oro",
                    "<#FFFFFF>â€¢ !tipall cantidad - Enviar a todos",
                    "<#FFFFFF>â€¢ !tip all cantidad - Alias de !tipall",
                ]),
            ])

        if role == "designer":
            sections.append(
                "\n".join([
                    "<#CC99FF>ðŸŽ¨ DISEÃ‘ADOR",
                    "<#FFFFFF>â€¢ !color categorÃ­a nÃºmero - Cambiar color",
                    "<#FFFFFF>â€¢ !equip nombre - Equipar una prenda",
                    "<#FFFFFF>â€¢ !remove categorÃ­a - Quitar una categorÃ­a",
                    "<#FFFFFF>â€¢ !getoutfit - Ver el vestuario",
                ])
            )

        if role == "owner":
            sections.extend([
                "\n".join([
                    "<#CC99FF>âš™ï¸ ADMINISTRACIÃ“N",
                    "<#FFFFFF>â€¢ !set - Guardar la posiciÃ³n del bot",
                    "<#FFFFFF>â€¢ !home - Volver a la posiciÃ³n guardada",
                    "<#FFFFFF>â€¢ !reset - Reiniciar el bot",
                    "<#FFFFFF>â€¢ !role @usuario mod|vip|designer|user - Administrar roles",
                ]),
                "\n".join([
                    "<#FFFFFF>ðŸ‘• VESTUARIO",
                    "<#FFFFFF>â€¢ !color categorÃ­a nÃºmero - Cambiar color",
                    "<#FFFFFF>â€¢ !equip nombre - Equipar una prenda",
                    "<#FFFFFF>â€¢ !remove categorÃ­a - Quitar una categorÃ­a",
                    "<#FFFFFF>â€¢ !getoutfit - Ver el vestuario",
                ]),
            ])

        return sections

    async def send_saved_roles_to_inbox(self, user: User) -> str:
        saved_roles = [
            (username, role)
            for username, role in sorted(self.role_manager.roles.items())
            if role != "user"
        ]
        if not saved_roles:
            content = "No hay usuarios con roles guardados distintos de user."
        else:
            content = "Usuarios con roles guardados:\n" + "\n".join(
                f"@{username}: {role}" for username, role in saved_roles
            )

        try:
            conversations = await self.highrise.get_conversations()
            conversation = next(
                (
                    item for item in conversations.conversations
                    if item.member_ids and user.id in item.member_ids
                ),
                None,
            )
            if conversation:
                result = await self.highrise.send_message(conversation.id, content)
                if result is None:
                    return "<#66FF99>ðŸ“¨ Te enviÃ© la lista de roles guardados por mensaje privado."
                print(f"Error enviando lista de roles: {result}")
            else:
                result = await self.highrise.send_message_bulk([user.id], content)
                if result is None:
                    return "<#66FF99>ðŸ“¨ Te enviÃ© la lista de roles guardados por mensaje privado."
                print(f"No se pudo iniciar la conversaciÃ³n privada: {result}")
        except Exception as error:
            print(f"Error enviando roles a la bandeja: {error}")

        return "<#FFCC66>ðŸ“¨ No pude enviar la lista a tu bandeja. EscrÃ­beme primero por mensaje privado y vuelve a usar !role."

    async def is_mod(self, user_id: str) -> bool:
        """Verifica si un usuario posee rol de moderador o superior."""
        if user_id == self.owner_id:
            return True
        try:
            permissions = await self.highrise.get_room_privilege(user_id)
            return bool(
                getattr(permissions, "moderator", False)
                or getattr(permissions, "designer", False)
            )
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
        """Obtiene la posiciÃ³n actual de un usuario en la sala."""
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
        """Ejecuta bailes aleatorios continuos Ãºnicamente para el bot."""
        public_emotes = [
            emote for emote in self.emotes_list
            if isinstance(emote, dict)
            and emote.get("auth") == "public"
            and isinstance(emote.get("emote"), str)
        ]
        if not public_emotes:
            print("No hay emotes pÃºblicos vÃ¡lidos para el baile automÃ¡tico.")
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
        """Bucle para hacer que el bot siga la posiciÃ³n del dueÃ±o."""
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
            print(f"Error restaurando la posiciÃ³n del bot: {error}")

    async def on_start(self, session_metadata: SessionMetadata) -> None:
        self.bot_id = session_metadata.user_id
        self.owner_id = session_metadata.room_info.owner_id
        self.bot_status = True
        print(f"Bot conectado exitosamente. Bot ID: {self.bot_id} | Owner ID: {self.owner_id}")

        await self.highrise.chat(
            "<#66FF99>ðŸ¤– Â¡Bot conectado! Escribe !help para ver los comandos."
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
                if command_name == "!userinfo":
                    await self.highrise.chat(response)
                else:
                    await self.highrise.send_whisper(user.id, response)
            return


        if msg_lower == "!reset":
            if user.id == self.owner_id or await self.is_mod(user.id):
                if not self.reset_task:
                    await self.highrise.chat(
                        "<#FF6666>ðŸ”„ El bot se reiniciarÃ¡ en un momento..."
                    )
                    self.reset_task = asyncio.create_task(self.restart_process())
            else:
                await self.highrise.send_whisper(
                    user.id, "ðŸ”’ Solo el dueÃ±o o los moderadores pueden reiniciar el bot."
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
                user.id, "<#FF6666>ðŸ›‘ Tu emote se detuvo."
            )
            return

        # ==========================================
        # 2. SEGUIR AL DUEÃ‘O (!follow / !stopfollow)
        # ==========================================
        elif msg_lower == "!follow":
            if user.id == self.owner_id or await self.is_mod(user.id):
                if not self.following:
                    self.following = True
                    self.follow_task = asyncio.create_task(self.follow_owner_loop())
                    await self.highrise.chat("<#66FF99>ðŸ§­ Â¡Ya voy contigo!")
                else:
                    await self.highrise.chat("<#FFCC66>ðŸ§­ Ya te estaba siguiendo.")
            else:
                await self.highrise.send_whisper(
                    user.id, "ðŸ”’ Solo el dueÃ±o de la sala puede usar este comando."
                )
            return

        elif msg_lower == "!stopfollow":
            if user.id == self.owner_id or await self.is_mod(user.id):
                if self.following:
                    self.following = False
                    if self.follow_task:
                        self.follow_task.cancel()
                    await self.highrise.chat("<#66CCFF>ðŸ›‘ DejÃ© de seguirte.")
                else:
                    await self.highrise.chat("<#FFCC66>ðŸ§­ No te estaba siguiendo.")
            else:
                await self.highrise.send_whisper(
                    user.id, "ðŸ”’ Solo el dueÃ±o de la sala puede usar este comando."
                )
            return

        # ==========================================
        # 3. INVOCACIÃ“N (!summon @usuario)
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
                                f"<#66CCFF>ðŸŒ€ @{target_username} ha sido invocado/a."
                            )
                        else:
                            await self.highrise.send_whisper(
                                user.id, "<#FF6666>âš ï¸ No pude obtener tu posiciÃ³n actual."
                            )
                    else:
                        await self.highrise.send_whisper(
                            user.id, "<#FFCC66>ðŸ”Ž Usuario no encontrado en la sala."
                        )
            else:
                await self.highrise.send_whisper(
                    user.id, "ðŸ”’ No tienes permisos para invocar usuarios."
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
                await self.highrise.send_whisper(user.id, "ðŸ“ Uso: !tele @usuario")
                return

            target_username = parts[1][1:]
            target_id = await self.get_user_id(target_username)
            if not target_id:
                await self.highrise.send_whisper(
                    user.id, "<#FFCC66>ðŸ”Ž Usuario no encontrado en la sala."
                )
                return

            target_position = await self.get_user_position(target_id)
            if not target_position:
                await self.highrise.send_whisper(
                    user.id, "<#FF6666>ðŸ“ No pude obtener la posiciÃ³n del usuario."
                )
                return

            await self.highrise.teleport(user.id, target_position)
            await self.highrise.send_whisper(
                user.id,
                f"<#66FF99>ðŸ“ Â¡Te has reunido con @{target_username}!"
            )
            return

        # ==========================================
        # 5. SUPERPUNCH PUBLICO (!superpunch @usuario)
        # ==========================================
        if msg_lower.startswith("!superpunch "):
            parts = msg.split()
            if len(parts) != 2 or not parts[1].startswith("@"):
                await self.highrise.send_whisper(user.id, "ðŸ¥Š Uso: !superpunch @usuario")
                return

            target_username = parts[1][1:]
            target_id = await self.get_user_id(target_username)
            if not target_id:
                await self.highrise.send_whisper(
                    user.id, "<#FFCC66>ðŸ”Ž Usuario no encontrado en la sala."
                )
                return
            if target_id == self.bot_id:
                await self.highrise.send_whisper(
                    user.id, "<#FF6666>ðŸ›¡ï¸ El bot tiene un escudo activo: no puedes golpearlo."
                )
                return

            target_position = await self.get_user_position(target_id)
            if not target_position:
                await self.highrise.send_whisper(
                    user.id, "<#FF6666>ðŸ“ No pude localizar a ese usuario."
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
                f"<#FFCC66>ðŸ¥Š @{user.username} lanzÃ³ un superpunch contra @{target_username}! ðŸ’¥"
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
                        user.id, "ðŸ”’ No tienes permiso para usar esta posiciÃ³n."
                    )
                    return
                try:
                    await self.highrise.teleport(user.id, self.position_manager.position_from_data(position_data))
                    await self.highrise.send_whisper(
                        user.id,
                        f"<#66FF99>ðŸ“ Â¡Has llegado a {position_name}!"
                    )
                except Exception as e:
                    print(f"Error al teletransportar a {position_name}: {e}")
                    await self.highrise.send_whisper(
                        user.id, "<#FF6666>âš ï¸ No se pudo realizar el teletransporte."
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
                "<#66CCFF>ðŸŽ² Emotes aleatorios activados. Escribe !stop para detenerlos.",
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
                    "<#FF6666>ðŸ”’ Este emote es exclusivo para moderadores o dueÃ±os."
                )
                return

            target_id = user.id
            if target_username:
                target_id = await self.get_user_id(target_username)
                if not target_id:
                    await self.highrise.send_whisper(
                        user.id, "<#FFCC66>ðŸ”Ž Usuario no encontrado en la sala."
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
                f"<#66FF99>âœ¨ Emote activado: {matched_emote['command']}. Escribe !stop para detenerlo.",
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
                await self.highrise.chat("<#66FF99>ðŸ’ƒ Â¡Bailes aleatorios activados! ðŸŽ¶")
            else:
                await self.highrise.send_whisper(
                    user.id, "ðŸ”’ Solo el dueÃ±o o los moderadores pueden usar este comando."
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
                await self.highrise.chat("<#66CCFF>ðŸ›‘ Los bailes del bot se detuvieron.")
            else:
                await self.highrise.send_whisper(
                    user.id, "ðŸ”’ Solo el dueÃ±o puede detener los bailes del bot."
                )
            return

        # ==========================================
        # 12. MODERACIÃ“N (KICK Y TP)
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
                            f"<#FF6666>ðŸšª @{target_username} ha sido expulsado/a de la sala."
                        )
                    else:
                        await self.highrise.send_whisper(
                            user.id, "<#FFCC66>ðŸ”Ž Usuario no encontrado en la sala."
                        )
            else:
                await self.highrise.send_whisper(
                    user.id, "ðŸ”’ No tienes permisos de moderaciÃ³n."
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
                                f"<#66CCFF>ðŸ“ @{target_username} fue teletransportado/a."
                            )
                        else:
                            await self.highrise.send_whisper(
                                user.id, "<#FFCC66>ðŸ”Ž Usuario no encontrado en la sala."
                            )
                    except ValueError:
                        await self.highrise.send_whisper(
                            user.id, "<#FFCC66>ðŸ“ Coordenadas invÃ¡lidas. Usa nÃºmeros."
                        )
            else:
                await self.highrise.send_whisper(
                    user.id, "ðŸ”’ No tienes permisos de moderaciÃ³n."
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

    async def on_user_join(
        self, user: User, position: Position | AnchorPosition
    ) -> None:
        print(f"[JOIN] {user.username} entrÃ³ a la sala.")
        role = await self.role_manager.get_user_role(self, user)
        try:
            await self.highrise.send_whisper(
                user.id,
                "\n".join([
                    f"<#66FFCC>âœ¨ Â¡Hola, {user.username}! âœ¨",
                    "<#FFFFFF>â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”",
                    f"<#FFCC66>ðŸŽ­ Tu rol en la sala: <#FFFFFF>{role}",
                    "<#66FF99>ðŸŽ‰ Â¡Bienvenido/a! Pasa, disfruta y comparte buenas vibras.",
                    "<#CC99FF>ðŸ’« Escribe <#FFFFFF>!help <#CC99FF>para descubrir mis comandos.",
                    "<#FFFFFF>â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”",
                ]),
            )
        except Exception as error:
            print(f"Error enviando la bienvenida a @{user.username}: {error}")

        try:
            await self.role_manager.apply_saved_role(self, user)
        except Exception as error:
            print(f"Error aplicando el rol guardado a @{user.username}: {error}")

        if isinstance(position, Position):
            self.user_positions[user.id] = position

    async def on_message(
        self, user_id: str, conversation_id: str, is_new_conversation: bool
    ) -> None:
        try:
            response = await self.highrise.get_messages(conversation_id)
            if not isinstance(response, GetMessagesRequest.GetMessagesResponse):
                return
            if not response.messages:
                return

            message = response.messages[-1].content.strip().lower()
            if message != "!help":
                return

            user = User(user_id, "")
            try:
                user_response = await self.webapi.get_user(user_id)
                user = User(user_id, user_response.user.username)
            except Exception as error:
                print(f"No se pudo cargar el usuario de la conversaciÃ³n: {error}")

            for section in await self.get_command_help(user):
                await self.highrise.send_message(conversation_id, section)
        except Exception as error:
            print(f"Error procesando !help en la bandeja: {error}")

if __name__ == "__main__":
    if not ROOM_ID or not API_KEY:
        raise RuntimeError("ROOM_ID y API_KEY deben estar configuradas en el entorno")
    Thread(target=start_health_server, daemon=True).start()
    definitions = [BotDefinition(Bot(), ROOM_ID, API_KEY)]
    arun(__main__.main(definitions))
