from highrise import BaseBot, __main__, CurrencyItem, GetMessagesRequest, Item, Position, AnchorPosition, SessionMetadata, User
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
    EMOTES_FILE,
    POSITIONS_FILE,
    ROOM_ID,
    ROLES_FILE,
)
from commands.owner import handle_owner_command
from commands.dispatcher import CommandDispatcher
from services.positions import PositionManager
from services.roles import RoleManager
from services.emotes import EmotesManager
from bots.bot1.services.track import handle_track_command, start_track_monitor
from services.storage import load_json
from bots.bot1.services.tips import TipManager
from bots.bot1.services.anuncios import announcement_loop
from bots.bot1.services.diversion import handle_diversion_command
from common.bot_manager import should_handle_for_bot
from common.avatar import AvatarManager
from common.positions import PositionManagerCommon
from common.dance import DanceManager
from common.bot_state import BotStateManager


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
        self.following_user_id = None
        self.follow_task = None
        self.emote_tasks = {}
        self.position_task = None
        self.reset_task = None
        self.announcement_task = None
        self.fight_tasks = set()
        self.current_bot_emote = None
        self.bot_username = os.getenv("BOT1_USERNAME", "Zeta_Bot")
        self.avatar_manager = AvatarManager(self)
        self.position_manager_common = PositionManagerCommon(self, DATA_FILE)
        self.dance_manager = DanceManager(self)
        self.bot_state_manager = BotStateManager(self)
        self.state_file = DATA_FILE
        
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

    async def _is_targeted_for_me(self, message: str) -> bool:
        return await should_handle_for_bot(self, message)

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
            "\n".join([                "<#CC99FF>👤 INFORMACIÓN",
                    "<#FFFFFF>• !userinfo - Ver tu información",
                "<#FFFFFF>• !userinfo @usuario - Ver información de otro usuario",
                "<#FFFFFF>• !help - Mostrar la ayuda disponible",
            ]),
        ]

        if role in ("owner", "mod"):
            sections.extend([
                "\n".join([
                    "<#FF66CC>🛡️ MODERACIÓN",
                    "<#FFFFFF>• !kick @usuario - Expulsar un usuario",
                    "<#FFFFFF>• !tp @usuario x y z - Teletransportar un usuario",
                    "<#FFFFFF>• !dancebot @Zeta_Bot - Activar baile aleatorio",
                    "<#FFFFFF>• !stopdance @Zeta_Bot - Detener baile aleatorio",
                    "<#FFFFFF>• !emote @Zeta_Bot rest - Emote persistente del bot",
                    "<#FFFFFF>• !emote @Zeta_Bot stop - Detener emote del bot",
                    "<#FFFFFF>• rest @usuario - Emote para un usuario",
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

        if role == "designer":
            sections.append(
                "\n".join([
                    "<#CC99FF>🎨 DISEÑADOR",
                    "<#FFFFFF>• !color categoría número - Cambiar color",
                    "<#FFFFFF>• !equip nombre - Equipar una prenda",
                    "<#FFFFFF>• !remove categoría - Quitar una categoría",
                    "<#FFFFFF>• !getoutfit - Ver el vestuario",
                ])
            )

        if role == "owner":
            sections.extend([
                "\n".join([
                    "<#CC99FF>⚙️ ADMINISTRACIÓN",
                    "<#FFFFFF>• !set @Zeta_Bot - Guardar la posición del bot",
                    "<#FFFFFF>• !home @Zeta_Bot - Volver a la posición guardada",
                    "<#FFFFFF>• !reset @Zeta_Bot - Reiniciar el bot",
                    "<#FFFFFF>• !role @usuario mod|vip|designer|user - Administrar roles",
                ]),
                "\n".join([
                    "<#FFFFFF>👕 VESTUARIO",
                    "<#FFFFFF>• !color categoría número - Cambiar color",
                    "<#FFFFFF>• !equip nombre - Equipar una prenda",
                    "<#FFFFFF>• !remove categoría - Quitar una categoría",
                    "<#FFFFFF>• !getoutfit - Ver el vestuario",
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
                    return "<#66FF99>📨 Te envié la lista de roles guardados por mensaje privado."
                print(f"Error enviando lista de roles: {result}")
            else:
                result = await self.highrise.send_message_bulk([user.id], content)
                if result is None:
                    return "<#66FF99>📨 Te envié la lista de roles guardados por mensaje privado."
                print(f"No se pudo iniciar la conversación privada: {result}")
        except Exception as error:
            print(f"Error enviando roles a la bandeja: {error}")

        return "<#FFCC66>📨 No pude enviar la lista a tu bandeja. Escríbeme primero por mensaje privado y vuelve a usar !role."

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

    async def is_bot_user(self, user_id: str) -> bool:
        if user_id == self.bot_id:
            return True
        bot_usernames = {
            self.bot_username.lower(),
            os.getenv("DJ_BOT_USERNAME", "Dj.Z").lower(),
        }
        try:
            room_users = await self.highrise.get_room_users()
            return any(
                room_user.id == user_id and room_user.username.lower() in bot_usernames
                for room_user, _ in room_users.content
            )
        except Exception:
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

    async def follow_user_loop(self):
        """Bucle para seguir al usuario que activó !follow."""
        while self.following:
            try:
                target_id = self.following_user_id
                if not target_id:
                    break
                target_pos = await self.get_user_position(target_id)
                if target_pos and isinstance(target_pos, Position):
                    bot_pos = Position(
                        target_pos.x + 1,
                        target_pos.y,
                        target_pos.z,
                        target_pos.facing,
                    )
                    await self.highrise.walk_to(bot_pos)
                await asyncio.sleep(2)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error en follow_user_loop: {e}")
                await asyncio.sleep(2)

    async def restart_process(self):
        """Reinicia el proceso del bot de forma limpia."""
        await asyncio.sleep(1)
        os._exit(0)

    async def place_bot(self):
        await asyncio.sleep(5)
        try:
            self.bot_position = self.position_manager_common.get_saved_position()
            if self.bot_position:
                await self.highrise.teleport(self.bot_id, self.bot_position)
                print(f"[POSITION] Bot restaurado en {self.bot_position}.")
        except Exception as error:
            print(f"Error restaurando la posición del bot: {error}")

    async def on_tip(
        self, sender: User, receiver: User, tip: CurrencyItem | Item
    ) -> None:
        try:
            await self.tip_manager.handle_tip(self.highrise, self.bot_id, sender, receiver, tip)
        except Exception as error:
            print(f"[TIP ERROR] Error procesando propina de @{sender.username}: {error}")

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
        try:
            await self.avatar_manager.restore_saved_outfit()
        except Exception as error:
            print(f"Error restaurando el vestuario del bot: {error}")
        await self.dance_manager.restore()
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
        protected_commands = {"!set", "!home", "!color", "!equip", "!remove", "!getoutfit", "/equip", "/remove", "/getoutfit"}
        if command_name in protected_commands and not await self._is_targeted_for_me(msg):
            return

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


        if msg_lower.startswith("!reset"):
            if not await self._is_targeted_for_me(msg):
                return
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

        if msg_lower.startswith("!set @") or msg_lower.startswith("!home @"):
            if await self._is_targeted_for_me(msg):
                if msg_lower.startswith("!set @"):
                    result = await self.position_manager_common.set_current_position(user.id)
                    if "No pude obtener" in result:
                        await self.highrise.send_whisper(user.id, result)
                        return
                    position = await self.get_user_position(user.id)
                    if position:
                        await self.highrise.teleport(self.bot_id, position)
                    await self.highrise.send_whisper(user.id, result)
                    return
                if msg_lower.startswith("!home @"):
                    response = await self.position_manager_common.return_home()
                    await self.highrise.send_whisper(user.id, response)
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
        # 2. SEGUIR AL USUARIO QUE ACTIVA EL COMANDO
        # ==========================================
        elif msg_lower.startswith("!follow"):
            parts = msg.split()
            if len(parts) == 2 and parts[1].startswith("@"):
                target_bot = parts[1][1:].lower()
                if target_bot != self.bot_username.lower():
                    return
            elif len(parts) != 1:
                await self.highrise.send_whisper(
                    user.id, "📍 Uso: !follow @Zeta_Bot"
                )
                return

            if self.following:
                if self.following_user_id == user.id:
                    await self.highrise.send_whisper(
                        user.id, "<#FFCC66>🧭 Ya te estaba siguiendo."
                    )
                else:
                    await self.highrise.send_whisper(
                        user.id, "<#FFCC66>🧭 El bot ya está siguiendo a otro usuario."
                    )
                return

            self.following = True
            self.following_user_id = user.id
            self.follow_task = asyncio.create_task(self.follow_user_loop())
            await self.highrise.chat(f"<#66FF99>🧭 ¡Ya voy contigo, @{user.username}!")
            return

        elif msg_lower.startswith("!stopfollow"):
            parts = msg.split()
            if len(parts) == 2 and parts[1].startswith("@"):
                target_bot = parts[1][1:].lower()
                if target_bot != self.bot_username.lower():
                    return
            elif len(parts) != 1:
                await self.highrise.send_whisper(
                    user.id, "📍 Uso: !stopfollow @Zeta_Bot"
                )
                return

            if not self.following:
                await self.highrise.send_whisper(
                    user.id, "<#FFCC66>🧭 El bot no está siguiendo a nadie."
                )
                return

            if self.following_user_id != user.id and user.id != self.owner_id and not await self.is_mod(user.id):
                await self.highrise.send_whisper(
                    user.id, "<#FF6666>🔒 Solo quien activó el seguimiento, el dueño o un moderador puede detenerlo."
                )
                return

            self.following = False
            self.following_user_id = None
            if self.follow_task:
                self.follow_task.cancel()
                self.follow_task = None
            await self.highrise.chat("<#66CCFF>🛑 Dejé de seguir.")
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
                                user.id, "<#FF6666>âš ï¸ No pude obtener tu posición actual."
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

        if await handle_track_command(self, user, msg):
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
            if await self.is_bot_user(target_id):
                await self.highrise.send_whisper(
                    user.id, "<#FF6666>🛡️ Los bots no pueden ser objetivos de este comando."
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
                        user.id, "<#FF6666>âš ï¸ No se pudo realizar el teletransporte."
                    )
                return

        # ==========================================
        # 10. COMANDOS DE EMOTES (Cargados desde emotes.json)        # ==========================================
        # ==========================================
        # 10. BAILE ALEATORIO DIRIGIDO AL BOT
        # ==========================================
        if msg_lower.startswith(("!dancebot", "!botdance")):
            if not await self._is_targeted_for_me(msg):
                return
            if user.id == self.owner_id or await self.is_mod(user.id):
                await self.highrise.send_whisper(
                    user.id, await self.dance_manager.start_random_dance()
                )
            else:
                await self.highrise.send_whisper(
                    user.id, "🔒 Solo el dueño o los moderadores pueden usar este comando."
                )
            return

        if msg_lower.startswith(("!stopdance", "!stopbotdance")):
            if not await self._is_targeted_for_me(msg):
                return
            if user.id == self.owner_id or await self.is_mod(user.id):
                await self.highrise.send_whisper(
                    user.id, await self.dance_manager.stop_dance()
                )
            else:
                await self.highrise.send_whisper(
                    user.id, "🔒 Solo el dueño o los moderadores pueden detener el baile del bot."
                )
            return

        if msg_lower.startswith("!emote "):
            emote_parts = msg.split()
            if len(emote_parts) < 3 or not emote_parts[1].startswith("@"):
                await self.highrise.send_whisper(user.id, "<#FFCC66>🎭 Uso: !emote @Bot <emote> o !emote @Bot stop")
                return
            target_username = emote_parts[1][1:]
            emote_name = " ".join(emote_parts[2:]).lower()

            if target_username.lower() == self.bot_username.lower():
                if user.id != self.owner_id and not await self.is_mod(user.id):
                    await self.highrise.send_whisper(user.id, "<#FF6666>🔒 Solo el dueño o moderadores pueden controlar el emote del bot.")
                    return
                if emote_name == "stop":
                    response = await self.dance_manager.stop_bot_emote()
                else:
                    if emote_name.isdigit():
                        matched_emote = self.emotes_manager.get_by_index(int(emote_name) - 1)
                    else:
                        matched_emote = self.emotes_manager.get_by_name(emote_name)
                    if not matched_emote:
                        await self.highrise.send_whisper(user.id, f"<#FFCC66>🎭 Emote no encontrado: {emote_name}.")
                        return
                    response = await self.dance_manager.start_bot_emote(matched_emote["emote"])
                await self.highrise.send_whisper(user.id, response)
                return
            if target_username.lower() == os.getenv("DJ_BOT_USERNAME", "Dj.Z").lower():
                return
            await self.highrise.send_whisper(user.id, "<#FFCC66>🎭 Los usuarios usan: rest @usuario")
            return

        emote_text = msg_lower[1:].strip() if msg_lower.startswith("!") else msg_lower
        if emote_text.startswith("/emote "):
            emote_text = emote_text[7:].strip()
        emote_parts = emote_text.split()
        target_username = None
        if len(emote_parts) > 1 and emote_parts[-1].startswith("@"):
            target_username = emote_parts.pop()[1:]
            emote_text = " ".join(emote_parts)

        bot_names = {
            self.bot_username.lower(),
            os.getenv("DJ_BOT_USERNAME", "Dj.Z").lower(),
        }
        if target_username and target_username.lower() in bot_names:
            await self.highrise.send_whisper(
                user.id, "<#FF6666>🛡️ No se pueden poner emotes directamente a los bots."
            )
            return

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

        protected_commands = {"!set", "!home", "!color", "!equip", "!remove", "!getoutfit", "/equip", "/remove", "/getoutfit"}
        if command.split()[0].lower() in protected_commands and not await self._is_targeted_for_me(message):
            return None

        if command.startswith("!tip all "):
            command = "!tipall " + command[len("!tip all "):]

        owner_response = await handle_owner_command(self, command, user_id)
        if owner_response:
            return owner_response
        return await self.tip_manager.handle_command(self, command, user_id)

    async def on_user_join(async def on_user_join(
        self, user: User, position: Position | AnchorPosition
    ) -> None:
        print(f"[JOIN] {user.username} entró a la sala.")
        try:
            role = await self.role_manager.get_user_role(self, user)
            if role and role != "user":
                await self.highrise.send_whisper(
                    user.id,
                    f"👋 ¡Bienvenido/a, @{user.username}! Tu rol actual es: {role}."
                )
        except Exception as error:
            print(f"[JOIN ERROR] Error procesando entrada de @{user.username}: {error}")

    async def on_user_leave(self, user: User) -> None:
        print(f"[LEAVE] {user.username} salió de la sala.")
        task = self.emote_tasks.pop(user.id, None)
        if task:
            task.cancel()
        self.user_positions.pop(user.id, None)

    async def on_tip(self, sender: User, receiver: User, tip: CurrencyItem | Item) -> None:
        try:
            await self.tip_manager.handle_tip(self.highrise, self.bot_id, sender, receiver, tip)
        except Exception as error:
            print(f"[TIP ERROR] Error procesando propina de @{sender.username}: {error}")


if __name__ == "__main__":
    if not ROOM_ID or not API_KEY:
        raise RuntimeError("ROOM_ID y API_KEY deben estar configuradas en el entorno")
    Thread(target=start_health_server, daemon=True).start()
    definitions = [BotDefinition(Bot(), ROOM_ID, API_KEY)]
    arun(__main__.main(definitions))
