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
from services.track import handle_track_command, start_track_monitor
from services.storage import load_json
from services.youtube import YouTubeSearchError, search_video
from services.radio import RadioRequestError, request_playback
from tips import TipManager
from anuncios import announcement_loop
from diversion import handle_diversion_command


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

    async def on_chat(self, user: User, message: str) -> None:
        msg = message.strip()
        msg_lower = msg.lower()

        if msg_lower == "!help":
            response = await self.command_dispatcher.handle(self, user, msg)
            if response:
                for section in response:
                    await self.highrise.send_whisper(user.id, section)
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
                video = await search_video(query)
                try:
                    await request_playback(video["video_id"])
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
                    "<#FFCC66>ℹ️ Solo se reproducen contenidos propios, "
                    "libres de derechos o autorizados.",
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

        # ==========================================
        if await handle_diversion_command(self, user, msg):
            return

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
            if 0 <= emote_index < len(self.emotes_list):
                matched_emote = self.emotes_list[emote_index]
        else:
            matched_emote = next(
                (emote for emote in self.emotes_list
                 if emote["command"].lower() == emote_text),
                None,
            )

        if matched_emote:
            # Verificar permisos si el emote requiere auth especial
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
                target_username = msg.split(" ")[1].replace("@", "")
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
                    user.id, "🔒 No tienes permisos para teletransportar."
                )
            return

        # ==========================================
        # 13. COMANDOS DE DUEÑO / PROPINAS Y WALLET
        # ==========================================
        response = await self.command_dispatcher.handle(self, user, msg)
        if response:
            await self.highrise.send_whisper(user.id, response)
            return

        response = await self.command_handler(user.id, message)
        if response:
            try:
                await self.highrise.send_whisper(user.id, response)
            except Exception as e:
                print(f"Chat Error: {e}")

    async def follow_owner_loop(self):
        """Bucle para hacer que el bot siga la posición del dueño continuamente."""
        try:
            while self.following:
                owner_pos = await self.get_user_position(self.owner_id)
                if owner_pos:
                    await self.highrise.walk_to(owner_pos)
                await asyncio.sleep(1.5)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"Error en bucle de seguimiento: {e}")

    async def emote_loop(self, user_id: str, emote_id: str, duration: float):
        try:
            while True:
                await self.highrise.send_emote(emote_id, user_id)
                await asyncio.sleep(max(float(duration), 0.1))
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.emote_tasks.pop(user_id, None)
            print(f"Error en bucle de emote: {e}")

    async def random_emote_loop(self, user_id: str):
        public_emotes = [
            emote for emote in self.emotes_list
            if emote.get("auth") == "public"
        ]
        if not public_emotes:
            print("No hay emotes públicos disponibles en emotes.json.")
            self.emote_tasks.pop(user_id, None)
            return

        try:
            while True:
                emote = choice(public_emotes)
                try:
                    await self.highrise.send_emote(emote["emote"], user_id)
                except Exception as error:
                    public_emotes.remove(emote)
                    print(
                        f"Emote no disponible para {user_id}: "
                        f"{emote['emote']} ({error})"
                    )
                    if not public_emotes:
                        break
                    continue
                await asyncio.sleep(max(float(emote.get("duration", 1)), 0.1))
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.emote_tasks.pop(user_id, None)
            print(f"Error en el bucle de emotes aleatorios: {e}")
        finally:
            self.emote_tasks.pop(user_id, None)

    async def random_dance_loop(self):
        dances = [
            emote for emote in self.emotes_list
            if emote.get("emote", "").startswith(("dance-", "idle-dance-"))
            and emote.get("auth") == "public"
        ]
        if not dances:
            print("No hay bailes públicos disponibles en emotes.json.")
            return

        try:
            while True:
                dance = choice(dances)
                dance_duration = max(
                    float(dance.get("duration", 1)), 0.1
                )
                try:
                    await self.highrise.send_emote(dance["emote"], self.bot_id)
                except Exception as error:
                    dances.remove(dance)
                    print(
                        f"Baile no disponible para el bot: "
                        f"{dance['emote']} ({error})"
                    )
                    if not dances:
                        break
                    continue
                self.current_bot_emote = dance["emote"]
                self.current_bot_emote_duration = dance_duration
                await asyncio.sleep(self.current_bot_emote_duration)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"Error en el bucle de bailes: {e}")
        finally:
            self.current_bot_emote = None
            self.current_bot_emote_duration = 0
            self.botdance_task = None

    async def get_user_position(self, user_id: str) -> Position | None:
        """Obtiene las coordenadas actuales de un usuario."""
        room_users = await self.highrise.get_room_users()
        for room_user, pos in room_users.content:
            if room_user.id == user_id and isinstance(pos, Position):
                return pos
        return None

    async def update_user(self, user: User, position: Position | AnchorPosition) -> None:
        """Guarda la última posición conocida del usuario para controlar su movimiento."""
        if not isinstance(position, Position):
            return
        self.user_positions[user.id] = position

    async def on_whisper(self, user: User, message: str) -> None:
        print(f"[WHISPER] {user.username}: {message}")
        response = await self.command_dispatcher.handle(self, user, message)
        if response:
            if message.strip().lower() == "!help":
                for section in response:
                    await self.highrise.send_whisper(user.id, section)
            else:
                await self.highrise.send_whisper(user.id, response)
            return

        response = await self.command_handler(user.id, message)
        if response:
            try:
                await self.highrise.send_whisper(user.id, response)
            except Exception as e:
                print(f"Whisper Error: {e}")

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
            if is_new_conversation or message == "!help":
                for section in await self.get_command_help(user_id):
                    await self.highrise.send_message(conversation_id, section)
        except Exception as error:
            print(f"Error procesando mensaje privado: {error}")

    async def get_command_help(self, user_id: str) -> list[str]:
        sections = [
            "\n".join([
                "<#FF6666>✨ COMANDOS DISPONIBLES ✨",
                "<#66CCFF>🎭 EMOTES",
                "<#FFFFFF>• !stop / stop - Detener tu emote",
                "<#FFFFFF>• !random - Emotes aleatorios",
            ]),
            "\n".join([
                "<#66FF99>📍 MOVIMIENTO",
                "<#FFFFFF>• !tele @usuario - Ir junto a un usuario",
            ]),
            "\n".join([
                "<#FFCC66>🥊 DIVERSIÓN",
                "<#FFFFFF>• !fight @usuario - Pelear con emotes",
                "<#FFFFFF>• !kiss @usuario - Enviar un beso secreto",
                "<#FFFFFF>• !heart @usuario - Enviar un corazón secreto",
                "<#FFFFFF>• !love @usuario - Calcular el amor contigo",
                "<#FFFFFF>• !love @usuario1 @usuario2 - Calcular el amor entre dos usuarios",
                "<#FFFFFF>• !superpunch @usuario - Lanzar un superpunch",
            ]),
            "\n".join([
                "<#CC99FF>👤 INFORMACIÓN",
                "<#FFFFFF>• !userinfo @usuario - Ver información de un usuario",
                "<#FFFFFF>• !help - Mostrar esta lista",
            ]),
        ]

        if user_id == self.owner_id or await self.is_mod(user_id):
            sections.extend([
                "\n".join([
                    "<#FF66CC>🛡️ ADMINISTRACIÓN Y VESTUARIO",
                    "<#FFFFFF>• !color categoria numero - Cambiar el color de una prenda",
                    "<#FFFFFF>• !equip nombre [numero] - Equipar una prenda",
                    "<#FFFFFF>• /remove categoria - Quitar una categoría del vestuario",
                    "<#FFFFFF>• /getoutfit - Ver el vestuario del bot",
                    "<#FFFFFF>• !role @usuario mod|vip|user - Administrar roles",
                    "<#FFFFFF>• !reset - Reiniciar el bot",
                    "<#FFFFFF>• !home - Llevar el bot a su posición guardada",
                    "<#FFFFFF>• !set - Guardar la posición actual del bot",
                    "<#FFFFFF>• !randomall - Activar emotes para todos",
                ]),
                "\n".join([
                    "<#66FF99>📍 POSICIONES Y PROPINAS",
                    "<#FFFFFF>• !top - Ver el ranking de propinas",
                    "<#FFFFFF>• !get @usuario - Ver las propinas de un usuario",
                    "<#FFFFFF>• !wallet - Ver el oro de la billetera",
                    "<#FFFFFF>• !tipme cantidad - Enviarte oro",
                    "<#FFFFFF>• !tip @usuario cantidad - Enviar oro a un usuario",
                    "<#FFFFFF>• !tipall cantidad - Enviar oro a todos",
                    "<#FFFFFF>• !ubi nombre priv|publi - Guardar una posición",
                    "<#FFFFFF>• !ubi delete nombre - Eliminar una posición",
                ]),
                "\n".join([
                    "<#FF6666>⚔️ MODERACIÓN",
                    "<#FFFFFF>• !kick @usuario - Expulsar un usuario",
                    "<#FFFFFF>• !tp @usuario x y z - Teletransportar un usuario",
                ]),
            ])

        return sections

    async def on_reaction(self, user: User, reaction: Reaction, receiver: User) -> None:
        print(f"[REACTION] {user.username} -> {reaction} -> {receiver.username}")
        if receiver.id == self.bot_id:
            try:
                await self.highrise.react(reaction, user.id)
            except Exception as e:
                print(f"Error al reaccionar: {e}")

    async def on_emote(self, user: User, emote_id: str, receiver: User | None) -> None:
        if receiver and receiver.id == self.bot_id:
            await self.highrise.send_emote("", self.bot_id)
            await self.highrise.send_whisper(
                user.id, "🛡️ No se pueden enviar emotes al bot."
            )

    async def on_tip(
        self, sender: User, receiver: User, tip: CurrencyItem | Item
    ) -> None:
        await self.tip_manager.handle_tip(self.highrise, self.bot_id, sender, receiver, tip)

    async def on_user_join(self, user: User, position: Position | AnchorPosition) -> None:
        print(f"[JOIN   ] {user.username} entró a la sala.")
        try:
            await self.role_manager.apply_saved_role(self, user)
        except Exception as error:
            print(f"Error aplicando el rol guardado de @{user.username}: {error}")
        role = await get_user_role(self, user)
        print(f"[ROLE   ] {user.username}: {role}")
        await self.highrise.send_whisper(
            user.id,
            f"<#FF66CC>🌟 ¡Bienvenido/a a la sala, @{user.username}!\n"
            f"<#66CCFF>🎭 Tu rol es: {role}. ¡Disfruta tu estancia! ✨"
        )
        if isinstance(position, Position):
            await self.update_user(user, position)

    async def on_user_leave(self, user: User) -> None:
        print(f"[LEAVE  ] {user.username} salió de la sala.")
        emote_task = self.emote_tasks.pop(user.id, None)
        if emote_task:
            emote_task.cancel()

    async def on_user_move(
        self, user: User, destination: Position | AnchorPosition
    ) -> None:
        if isinstance(destination, Position):
            await self.update_user(user, destination)

    async def on_start(self, session_metadata: SessionMetadata) -> None:
        print("[START  ] Bot conectado correctamente.")
        self.bot_id = session_metadata.user_id
        self.owner_id = session_metadata.room_info.owner_id
        self.bot_status = True
        if load_json(self.position_manager.positions_file).get("pista_emotes"):
            await start_track_monitor(self)
        if self.position_task:
            self.position_task.cancel()
        self.position_task = asyncio.create_task(self.place_bot())
        if self.botdance_task:
            self.botdance_task.cancel()
        self.botdance_task = asyncio.create_task(self.random_dance_loop())
        if self.announcement_task:
            self.announcement_task.cancel()
        self.announcement_task = asyncio.create_task(announcement_loop(self))
        await self.highrise.chat(
            "<#66FF99>✅ ¡El bot se ha conectado correctamente a la sala!"
        )

    async def restart_process(self) -> None:
        await asyncio.sleep(1)
        os._exit(0)

    # Comandos de administración y comandos exclusivos del dueño
    async def command_handler(self, user_id, message: str):
        command = message.lower().strip()

        command_name = command.split(maxsplit=1)[0] if command else ""
        if command_name == "!ubi":
            parts = command.split()
            if user_id != self.owner_id and not await self.is_mod(user_id):
                return "Solo el dueño o los moderadores pueden administrar ubicaciones."
            if len(parts) == 3 and parts[1] in ("eliminar", "borrar", "delete"):
                return self.position_manager.delete_named_position(parts[2])
            if len(parts) != 3 or parts[2] not in ("priv", "publi"):
                return "Usa: !ubi <nombre> <priv|publi> o !ubi delete <nombre>"
            return await self.position_manager.save_named_position(self, user_id, parts[1], parts[2])

        if user_id != self.owner_id and not await self.is_mod(user_id):
            return

        owner_response = await handle_owner_command(self, command, user_id)
        if owner_response:
            return owner_response
        return await self.tip_manager.handle_command(self, command, user_id)

    async def place_bot(self):
        await asyncio.sleep(5)
        for attempt in range(5):
            try:
                self.bot_position = self.position_manager.get_bot_position()
                if self.bot_position != Position(0, 0, 0, 'FrontRight'):
                    await self.highrise.teleport(self.bot_id, self.bot_position)
                    print(f"[POSITION] Bot restaurado en {self.bot_position}.")
                return
            except Exception as e:
                print(f"Error restaurando la posición (intento {attempt + 1}/5): {e}")
                if attempt < 4:
                    await asyncio.sleep(2)

    def load_emotes_data(self) -> list:
        """Carga la lista de emotes desde emotes.json."""
        if os.path.exists(EMOTES_FILE):
            try:
                with open(EMOTES_FILE, "r", encoding="utf-8") as file:
                    emotes = load(file)
                normalized_emotes = []
                for emote in emotes:
                    emote_id = emote.get("emote", emote.get("id"))
                    command = emote.get("command", emote.get("name"))
                    if not emote_id or not command:
                        continue
                    normalized_emotes.append(
                        {
                            "command": str(command).strip(),
                            "emote": emote_id,
                            "duration": max(float(emote.get("duration", 1)), 0.1),
                            "auth": emote.get("auth", "public"),
                        }
                    )
                return normalized_emotes
            except Exception as e:
                print(f"Error al cargar emotes.json: {e}")
        return []

    async def run_bot(self, room_id, api_key) -> None:
        self.start_health_server()
        definitions = [BotDefinition(self, room_id, api_key)]
        await __main__.main(definitions)

    def start_health_server(self) -> None:
        port = int(os.environ.get("PORT", "10000"))

        class HealthHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"OK")

            def do_HEAD(self):
                self.send_response(200)
                self.end_headers()

            def log_message(self, format, *args):
                return

        server = HTTPServer(("0.0.0.0", port), HealthHandler)
        Thread(target=server.serve_forever, daemon=True).start()

    async def is_mod(self, user_id: str) -> bool:
        """Verifica si un usuario es moderador o diseñador de la sala."""
        try:
            permissions = await self.highrise.get_room_privilege(user_id)
            return permissions.moderator
        except Exception as e:
            print(f"Error comprobando permisos: {e}")
            return False

    async def get_user_id(self, username: str) -> str | None:
        room_users = await self.highrise.get_room_users()
        for room_user, _ in room_users.content:
            if room_user.username.lower() == username.lower():
                return room_user.id
        return None

def data_file(filename: str, default_data: str = "{}") -> None:
    if not os.path.exists(filename):
        with open(filename, 'w') as file:
            file.write(default_data)

data_file(DATA_FILE, DEFAULT_DATA)
data_file(ROLES_FILE, '{"vip_users": []}')

if __name__ == "__main__":
    if not ROOM_ID or not API_KEY:
        raise RuntimeError("ROOM_ID y API_KEY deben estar configuradas en el entorno")
    arun(Bot().run_bot(ROOM_ID, API_KEY))