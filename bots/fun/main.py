from __future__ import annotations

import asyncio
import os
import sys
from json import load
from pathlib import Path

from highrise import BaseBot, CurrencyItem, GetMessagesRequest, Item, SessionMetadata, User, __main__
from highrise.__main__ import BotDefinition

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from commands.botdance import handle_botdance, handle_stopdance
from commands.color import handle_color
from commands.equip import handle_equip
from commands.home import handle_home
from commands.outfit import handle_get_outfit
from commands.remove import handle_remove
from commands.reset import handle_reset
from commands.set_position import handle_set_position
from common.avatar import AvatarManager
from common.bot_manager import should_handle_for_bot
from common.bot_runtime import BotRuntimeMixin
from services.message_pacing import install_message_pacing
from common.bot_state import BotStateManager
from common.dance import DanceManager
from services.emotes import EmotesManager
from services.roles import RoleManager
from bots.bot1.services.tips import TipManager
from bots.fun.games.verdad_reto import TruthOrDareGame
from bots.fun.games.rps import RpsGame
from bots.fun.games.dados21 import Dados21Game
from bots.fun.games.bomba import BombaGame


DATA_FILE = str(ROOT_DIR / "bots" / "fun" / "data" / "data.json")
EMOTES_FILE = str(ROOT_DIR / "common" / "emotes.json")
ROLES_FILE = str(ROOT_DIR / "roles.json")
ROOM_ID = os.environ.get("BOT3_ROOM_ID", "")
API_KEY = os.environ.get("BOT3_API_KEY", "")
BOT_USERNAME = os.environ.get("BOT3_USERNAME", "BotJuegos")


class Bot(BotRuntimeMixin, BaseBot):
    def __init__(self):
        super().__init__()
        self.bot_id = None
        self.owner_id = None
        self.bot_username = BOT_USERNAME
        self.state_file = DATA_FILE
        self.tip_manager = TipManager(DATA_FILE)
        self.role_manager = RoleManager(ROLES_FILE)
        self.position_manager_common = __import__(
            "common.positions", fromlist=["PositionManagerCommon"]
        ).PositionManagerCommon(self, DATA_FILE)
        self.avatar_manager = AvatarManager(self)
        self.bot_state_manager = BotStateManager(self)
        self.dance_manager = DanceManager(self)
        self.emotes_list = self.load_emotes_data()
        self.emotes_manager = EmotesManager(self.emotes_list)
        self.truth_or_dare = TruthOrDareGame(self, self.is_mod)
        self.rps = RpsGame(self)
        self.dados21 = Dados21Game(self)
        self.bomba = BombaGame(self)

    def load_emotes_data(self):
        try:
            with open(EMOTES_FILE, "r", encoding="utf-8-sig") as file:
                raw = load(file)
            result = []
            for emote in raw:
                if not isinstance(emote, dict):
                    continue
                emote_id = emote.get("emote", emote.get("id"))
                command = emote.get("command", emote.get("name"))
                if not emote_id or not command:
                    continue
                result.append({
                    "command": str(command).strip(),
                    "emote": str(emote_id).strip(),
                    "duration": max(float(emote.get("duration", 1)), 0.1),
                    "auth": emote.get("auth", "public"),
                })
            return result
        except Exception as error:
            print(f"[FUN] Error cargando emotes.json: {error}")
            return []

    async def _is_targeted_for_me(self, message: str) -> bool:
        return await should_handle_for_bot(self, message)

    async def restart_process(self):
        await asyncio.sleep(1)
        os._exit(0)

    async def _load_real_username(self):
        """Obtiene el username real del bot usando su ID de sesión."""
        try:
            room_users = await self.highrise.get_room_users()
            for room_user, _ in room_users.content:
                if room_user.id == self.bot_id:
                    self.bot_username = room_user.username
                    print(f"[FUN] Username real detectado: @{self.bot_username}")
                    return
        except Exception as error:
            print(f"[FUN] No pude obtener el username real: {error}")

        print(
            f"[FUN] Usando username configurado como respaldo: "
            f"@{self.bot_username}"
        )

    async def _game_promo_loop(self) -> None:
        """Publica invitaciones ocasionales a los juegos sin saturar el chat."""
        promos = [
            "<#CC99FF>🎭 ¿Aburrido/a? ¡Juguemos VERDAD O RETO! "
            "<#FFFFFF>Usa !vd para una ronda o !jugarvd para crear una partida grupal.",
            "<#FF4D6D>💣 ¡Cuidado, que la bomba no espera! "
            "<#FFFFFF>Escribe !bomba para iniciar y escribe jugar para entrar.",
            "<#FFCC66>🎲 ¿Te atreves a llegar a 21? "
            "<#FFFFFF>Prueba DADOS 21 con !dados21 100 y tira con !tirar.",
            "<#66CCFF>✊📄✂️ ¡Desafía a alguien a PIEDRA, PAPEL O TIJERA! "
            "<#FFFFFF>Usa !rps o !rps @usuario.",
            "<#CC99FF>💘 ¿Quién se atreve con una verdad incómoda o un reto atrevido? "
            "<#FFFFFF>Usa !verdad o !reto cuando te toque.",
            "<#FF4D6D>🔥 ¡La sala necesita un poco de emoción! "
            "<#FFFFFF>Reúne a tus amigos y empieza una partida con !jugarvd o !bomba.",
            "<#FFCC66>🏆 ¿Suerte, estrategia o valentía? "
            "<#FFFFFF>Elige tu juego: !help bomba · !help dados · !help rps · !help verdad.",
            "<#66FF99>🎮 ¡Hay juegos para todos! "
            "<#FFFFFF>Dados 21: !dados21 100 · RPS: !rps · Verdad o Reto: !vd · Bomba: !bomba.",
        ]
        # Espera inicial para no mandar la promoción inmediatamente al conectar.
        await asyncio.sleep(180)
        index = 0
        while True:
            try:
                await self.highrise.chat(promos[index % len(promos)])
                index += 1
            except asyncio.CancelledError:
                raise
            except Exception as error:
                print(f"[FUN PROMO] Error enviando invitación a juegos: {error}")
            # Un anuncio cada 8 minutos para no saturar el chat.
            await asyncio.sleep(480)

    async def restore_position(self):
        # Highrise necesita unos segundos después de on_start para que
        # el bot esté completamente presente en la sala antes del teleport.
        await asyncio.sleep(5)
        try:
            position = self.position_manager_common.get_saved_position()
            if not position:
                print("[FUN POSITION] No hay una posición guardada para restaurar.")
                return

            await self.highrise.teleport(self.bot_id, position)
            print(f"[FUN POSITION] Bot restaurado en {position}.")
        except Exception as error:
            print(f"[FUN POSITION] Error restaurando posición: {error}")

    async def restart_with_message(self):
        try:
            await self.highrise.chat(
                f"<#FFCC66>🔄 @{self.bot_username} se está reiniciando..."
            )
        except Exception:
            pass
        await self.restart_process()

    async def on_start(self, session_metadata: SessionMetadata) -> None:
        install_message_pacing(self.highrise)
        self.bot_id = session_metadata.user_id
        self.owner_id = session_metadata.room_info.owner_id

        # El username válido para los comandos se obtiene de la identidad
        # real del bot en la sala, no de BOT3_USERNAME.
        await self._load_real_username()

        print(
            f"[FUN] Conectado. Bot ID: {self.bot_id} | "
            f"Username: @{self.bot_username} | "
            f"Owner ID: {self.owner_id}"
        )

        try:
            await self.avatar_manager.restore_saved_outfit()
        except Exception as error:
            print(f"[FUN] Error restaurando outfit: {error}")

        await self.dance_manager.restore()
        asyncio.create_task(self.restore_position())
        self._game_promo_task = asyncio.create_task(self._game_promo_loop())

        await self.highrise.chat(
            f"<#66FF99>🎮 @{self.bot_username} está conectado. "
            "Escribe !help game para ver los juegos."
        )

    async def on_chat(self, user: User, message: str) -> None:
        msg = message.strip()
        if not msg:
            return

        parts = msg.split()
        command = parts[0].lower()

        # Comandos que pertenecen específicamente a este bot.
        targeted_commands = {
            "!set", "!home", "!reset",
            "!dancebot", "!botdance", "!stopdance", "!stopbotdance",
            "!color", "!equip", "!remove", "!getoutfit",
            "/equip", "/remove", "/getoutfit",
        }

        # !home y !reset sin @bot son comandos generales: cada bot que
        # esté conectado los ejecuta sobre sí mismo. Con @bot, solo responde
        # el bot mencionado.
        general_commands = {"!home", "!reset"}
        if command in targeted_commands:
            if command not in general_commands or len(parts) > 1:
                if not await self._is_targeted_for_me(msg):
                    return

        # Ayuda segmentada: cada juego tiene su propia sección.
        help_sections = {
            "bomba": [
                "<#FF4D6D>💣━━━━━━ BOMBA ━━━━━━",
                "<#FFFFFF>🚀 !bomba — Crear partida (inscripción: 20 s)",
                "<#66CCFF>👥 jugar — Unirte a la partida",
                "<#FFFFFF>🔤 Responde con una palabra válida de la categoría y letra indicadas",
                "<#FFCC66>⏱️ Tienes 30 s por ronda",
                "<#FFFFFF>🚪 salir — Abandonar la partida",
                "<#FF6666>🛑 terminar — Finalizarla (solo el creador)",
                "<#FF4D6D>💥 ¡Responde rápido y que no te explote la bomba!"
            ],
            "dados": [
                "<#FFCC66>🎲━━━━━━ DADOS 21 ━━━━━━",
                "<#FFFFFF>💰 !dados21 100 — Entrar apostando (10–100 G, múltiplos de 10)",
                "<#66CCFF>🎲 !tirar — Lanzar un dado",
                "<#FFFFFF>🎲 !doble — Lanzar dos dados",
                "<#66FF99>🛑 !plantarse — Terminar tu turno",
                "<#FFFFFF>🚪 !salir — Salir antes de comenzar",
                "<#FFCC66>💳 !saldo — Consultar tu saldo",
                "<#FFFFFF>🏆 !retirar 50 — Retirar ganancias disponibles (mín. 50 G)",
                "<#FFCC66>⏱️ ¡Acércate a 21 sin pasarte!"
            ],
            "rps": [
                "<#66CCFF>⚔️━━ PIEDRA, PAPEL O TIJERA ━━",
                "<#FFFFFF>🤖 !rps — Desafiar a BotJuegos",
                "<#66CCFF>👤 !rps @usuario — Desafiar a otro jugador",
                "<#FFFFFF>💰 !rps @usuario 10|50|100|500 — Jugar con apuesta",
                "<#FFCC66>✊ !piedra   📄 !papel   ✂️ !tijera"
            ],
            "verdad": [
                "<#CC99FF>🎭━━━━ VERDAD O RETO ━━━━",
                "<#FFFFFF>🎮 !vd — Jugar una ronda individual",
                "<#66CCFF>👥 !jugarvd — Crear partida grupal",
                "<#FFFFFF>➕ !entrarvd — Unirte a la partida",
                "<#66FF99>▶️ !iniciarvd — Comenzar (mínimo 2 jugadores)",
                "<#FFFFFF>🟢 !verdad / 🔴 !reto — Elegir",
                "<#FFCC66>✅ !listo — Terminar tu turno",
                "<#FFFFFF>🚪 !salirvd — Salir de la partida"
            ]
        }
        help_aliases = {
            "!help bomba": "bomba", "!help dados": "dados",
            "!help dados21": "dados", "!help rps": "rps",
            "!help verdad": "verdad", "!help vd": "verdad",
        }
        requested_help = msg.casefold()
        if requested_help in help_aliases:
            section = help_sections[help_aliases[requested_help]]
            await self.highrise.send_whisper(user.id, "\\n".join(section))
            return
        if requested_help == "!help game":
            for section in [
                "🎮 ¡BIENVENIDO A LA ZONA DE JUEGOS! 🔥\\n\\n💣 BOMBA: !bomba · jugar · salir",
                "🎲 DADOS 21: !dados21 100 · !tirar · !doble · !plantarse · !saldo · !retirar 50",
                "⚔️ RPS: !rps · !rps @usuario · !piedra · !papel · !tijera",
                "🎭 VERDAD O RETO: !vd · !jugarvd · !entrarvd · !iniciarvd · !verdad · !reto · !listo · !salirvd",
                "📜 !help bomba · !help dados · !help rps · !help verdad\\n👑 Creador: @Zhony6470\\n🐛 Cualquier bug, comunícate con él.",
            ]:
                await self.highrise.send_whisper(user.id, section)
            return

        if command == "!home":
            if len(parts) == 1:
                if user.id != self.owner_id and not await self.is_mod(user.id):
                    await self.highrise.send_whisper(
                        user.id,
                        "<#FF6666>🔒 Solo el dueño o los moderadores pueden usar este comando.",
                    )
                    return
                response = await self.position_manager_common.return_home()
            else:
                response = await handle_home(self, user, msg)

            if response:
                await self.highrise.send_whisper(user.id, response)
            return

        if command == "!reset":
            if len(parts) == 1:
                if user.id != self.owner_id and not await self.is_mod(user.id):
                    await self.highrise.send_whisper(
                        user.id,
                        "<#FF6666>🔒 Solo el dueño o los moderadores pueden reiniciar el bot.",
                    )
                    return
                await self.restart_with_message()
            else:
                await handle_reset(self, user, msg)
            return

        # 💣 Bomba
        if await self.bomba.handle(user, msg):
            return

        # 🎲 Dados 21
        if await self.dados21.handle(user, msg, private=False):
            return

        # ⚔️ Piedra, Papel o Tijera
        if await self.rps.handle(user, msg, private=False):
            return

        # 🎲 Verdad o Reto
        if await self.truth_or_dare.handle(user, msg):
            return

        if command == "!wallet":
            if user.id != self.owner_id and not self.role_manager.has_permission(user.id):
                await self.highrise.send_whisper(
                    user.id,
                    "<#FF6666>🔒 Necesitas el permiso avanzado para usar este comando.",
                )
                return
            response = await self.tip_manager.handle_command(self, "!wallet", user.id)
            if response:
                await self.highrise.send_whisper(user.id, response)
            return

        handlers = {
            "!set": handle_set_position,
            "!equip": handle_equip,
            "/equip": handle_equip,
            "!remove": handle_remove,
            "/remove": handle_remove,
            "!color": handle_color,
            "!getoutfit": handle_get_outfit,
            "/getoutfit": handle_get_outfit,
            "!dancebot": handle_botdance,
            "!botdance": handle_botdance,
            "!stopdance": handle_stopdance,
            "!stopbotdance": handle_stopdance,
        }

        handler = handlers.get(command)
        if handler:
            response = await handler(self, user, msg)
            if response:
                await self.highrise.send_whisper(user.id, response)
            return

        if command == "!emote":
            if len(parts) < 3 or not parts[1].startswith("@"):
                await self.highrise.send_whisper(
                    user.id,
                    f"<#FFCC66>🎭 Uso: !emote @{self.bot_username} <emote> "
                    f"o !emote @{self.bot_username} stop",
                )
                return

            target = parts[1][1:].casefold()
            if target != self.bot_username.casefold():
                return

            if user.id != self.owner_id and not await self.is_mod(user.id):
                await self.highrise.send_whisper(
                    user.id,
                    "<#FF6666>🔒 Solo el dueño o moderadores pueden controlar el emote del bot.",
                )
                return

            emote_name = " ".join(parts[2:]).strip().lower()
            if emote_name == "stop":
                response = await self.dance_manager.stop_bot_emote()
                await self.highrise.send_whisper(user.id, response)
                return

            if emote_name.isdigit():
                matched = self.emotes_manager.get_by_index(int(emote_name) - 1)
            else:
                matched = self.emotes_manager.get_by_name(emote_name)

            if not matched:
                await self.highrise.send_whisper(
                    user.id,
                    f"<#FFCC66>🎭 Emote no encontrado: {emote_name}.",
                )
                return

            response = await self.dance_manager.start_bot_emote(matched["emote"])
            await self.highrise.send_whisper(user.id, response)
            return

    async def on_message(
        self, user_id: str, conversation_id: str, is_new_conversation: bool
    ) -> None:
        """Responde !help en el buzón privado de Highrise."""
        print(f"[INBOX DEBUG] on_message recibido en bots/fun/main.py user_id={user_id} conversation_id={conversation_id} new={is_new_conversation}")
        try:
            response = await self.highrise.get_messages(conversation_id)
            if not isinstance(response, GetMessagesRequest.GetMessagesResponse):
                print(f"[INBOX DEBUG] Tipo de respuesta inesperado: {type(response).__name__}")
                return
            if not response.messages:
                print("[INBOX DEBUG] La conversación no contiene mensajes")
                return
            message = response.messages[0].content.strip().lower()
            print(f"[INBOX DEBUG] Primer mensaje de la conversación: {message!r}")
            if message != "!help":
                return
            for section in [
                "🎮 ¡BIENVENIDO A LA ZONA DE JUEGOS! 🔥\\n\\n💣 BOMBA: !bomba · jugar · salir",
                "🎲 DADOS 21: !dados21 100 · !tirar · !doble · !plantarse · !saldo · !retirar 50",
                "⚔️ RPS: !rps · !rps @usuario · !piedra · !papel · !tijera",
                "🎭 VERDAD O RETO: !vd · !jugarvd · !entrarvd · !iniciarvd · !verdad · !reto · !listo · !salirvd",
                "📜 !help bomba · !help dados · !help rps · !help verdad\\n👑 Creador: @Zhony6470\\n🐛 Cualquier bug, comunícate con él.",
            ]:
                await self.highrise.send_message(conversation_id, section)
        except Exception as error:
            print(f"[FUN INBOX HELP] Error procesando !help: {error}")

    async def on_whisper(self, user: User, message: str) -> None:
        # BotJuegos solo responde a !help game y a las ayudas específicas.
        help_command = message.strip().lower()
        if help_command == "!help game" or help_command in {
            "!help bomba", "!help dados", "!help dados21",
            "!help rps", "!help verdad", "!help vd",
        }:
            await self.on_chat(user, help_command)
            return

    async def on_user_move(self, user: User, position) -> None:
        await self.truth_or_dare.on_user_move(user, position)

    async def on_user_leave(self, user: User) -> None:
        await self.rps.on_user_leave(user.id)
        await self.truth_or_dare.on_user_leave(user.id)

    async def on_tip(
        self, sender: User, receiver: User, tip: CurrencyItem | Item
    ) -> None:
        try:
            # RPS debe procesar primero sus apuestas para que no se registren
            # también como depósitos de la cartera de Dados 21.
            if await self.rps.handle_tip(sender, receiver, tip):
                return
            if await self.dados21.handle_tip(sender, receiver, tip):
                return
            await self.tip_manager.handle_tip(
                self.highrise, self.bot_id, sender, receiver, tip
            )
        except Exception as error:
            print(f"[FUN TIP] Error procesando propina: {error}")


definitions = [BotDefinition(Bot(), ROOM_ID, API_KEY)]

if __name__ == "__main__":
    if not ROOM_ID or not API_KEY:
        raise RuntimeError("ROOM_ID y BOT3_API_KEY deben estar configuradas.")
    asyncio.run(__main__.main(definitions))            for section in [
                "🎮 ¡BIENVENIDO A LA ZONA DE JUEGOS! 🔥\\n\\n💣 BOMBA: !bomba · jugar · salir",
                "🎲 DADOS 21: !dados21 100 · !tirar · !doble · !plantarse · !saldo · !retirar 50",
                "⚔️ RPS: !rps · !rps @usuario · !piedra · !papel · !tijera",
                "🎭 VERDAD O RETO: !vd · !jugarvd · !entrarvd · !iniciarvd · !verdad · !reto · !listo · !salirvd",
                "📜 !help bomba · !help dados · !help rps · !help verdad\\n👑 Creador: @Zhony6470\\n🐛 Cualquier bug, comunícate con él.",
            ]:
                await self.highrise.send_message(conversation_id, section)
        except Exception:
            pass
        await self.restart_process()

    async def on_start(self, session_metadata: SessionMetadata) -> None:
        install_message_pacing(self.highrise)
        self.bot_id = session_metadata.user_id
        self.owner_id = session_metadata.room_info.owner_id

        # El username válido para los comandos se obtiene de la identidad
        # real del bot en la sala, no de BOT3_USERNAME.
        await self._load_real_username()

        print(
            f"[FUN] Conectado. Bot ID: {self.bot_id} | "
            f"Username: @{self.bot_username} | "
            f"Owner ID: {self.owner_id}"
        )

        try:
            await self.avatar_manager.restore_saved_outfit()
        except Exception as error:
            print(f"[FUN] Error restaurando outfit: {error}")

        await self.dance_manager.restore()
        asyncio.create_task(self.restore_position())
        self._game_promo_task = asyncio.create_task(self._game_promo_loop())

        await self.highrise.chat(
            f"<#66FF99>🎮 @{self.bot_username} está conectado. "
            "Escribe !help game para ver los juegos."
        )

    async def on_chat(self, user: User, message: str) -> None:
        msg = message.strip()
        if not msg:
            return

        parts = msg.split()
        command = parts[0].lower()

        # Comandos que pertenecen específicamente a este bot.
        targeted_commands = {
            "!set", "!home", "!reset",
            "!dancebot", "!botdance", "!stopdance", "!stopbotdance",
            "!color", "!equip", "!remove", "!getoutfit",
            "/equip", "/remove", "/getoutfit",
        }

        # !home y !reset sin @bot son comandos generales: cada bot que
        # esté conectado los ejecuta sobre sí mismo. Con @bot, solo responde
        # el bot mencionado.
        general_commands = {"!home", "!reset"}
        if command in targeted_commands:
            if command not in general_commands or len(parts) > 1:
                if not await self._is_targeted_for_me(msg):
                    return

        # Ayuda segmentada: cada juego tiene su propia sección.
        help_sections = {
            "bomba": [
                "<#FF4D6D>💣━━━━━━ BOMBA ━━━━━━",
                "<#FFFFFF>🚀 !bomba — Crear partida (inscripción: 20 s)",
                "<#66CCFF>👥 jugar — Unirte a la partida",
                "<#FFFFFF>🔤 Responde con una palabra válida de la categoría y letra indicadas",
                "<#FFCC66>⏱️ Tienes 30 s por ronda",
                "<#FFFFFF>🚪 salir — Abandonar la partida",
                "<#FF6666>🛑 terminar — Finalizarla (solo el creador)",
                "<#FF4D6D>💥 ¡Responde rápido y que no te explote la bomba!"
            ],
            "dados": [
                "<#FFCC66>🎲━━━━━━ DADOS 21 ━━━━━━",
                "<#FFFFFF>💰 !dados21 100 — Entrar apostando (10–100 G, múltiplos de 10)",
                "<#66CCFF>🎲 !tirar — Lanzar un dado",
                "<#FFFFFF>🎲 !doble — Lanzar dos dados",
                "<#66FF99>🛑 !plantarse — Terminar tu turno",
                "<#FFFFFF>🚪 !salir — Salir antes de comenzar",
                "<#FFCC66>💳 !saldo — Consultar tu saldo",
                "<#FFFFFF>🏆 !retirar 50 — Retirar ganancias disponibles (mín. 50 G)",
                "<#FFCC66>⏱️ ¡Acércate a 21 sin pasarte!"
            ],
            "rps": [
                "<#66CCFF>⚔️━━ PIEDRA, PAPEL O TIJERA ━━",
                "<#FFFFFF>🤖 !rps — Desafiar a BotJuegos",
                "<#66CCFF>👤 !rps @usuario — Desafiar a otro jugador",
                "<#FFFFFF>💰 !rps @usuario 10|50|100|500 — Jugar con apuesta",
                "<#FFCC66>✊ !piedra   📄 !papel   ✂️ !tijera"
            ],
            "verdad": [
                "<#CC99FF>🎭━━━━ VERDAD O RETO ━━━━",
                "<#FFFFFF>🎮 !vd — Jugar una ronda individual",
                "<#66CCFF>👥 !jugarvd — Crear partida grupal",
                "<#FFFFFF>➕ !entrarvd — Unirte a la partida",
                "<#66FF99>▶️ !iniciarvd — Comenzar (mínimo 2 jugadores)",
                "<#FFFFFF>🟢 !verdad / 🔴 !reto — Elegir",
                "<#FFCC66>✅ !listo — Terminar tu turno",
                "<#FFFFFF>🚪 !salirvd — Salir de la partida"
            ]
        }
        help_aliases = {
            "!help bomba": "bomba", "!help dados": "dados",
            "!help dados21": "dados", "!help rps": "rps",
            "!help verdad": "verdad", "!help vd": "verdad",
        }
        requested_help = msg.casefold()
        if requested_help in help_aliases:
            section = help_sections[help_aliases[requested_help]]
            await self.highrise.send_whisper(user.id, "\\n".join(section))
            return
        if requested_help == "!help game":
            for section in [
                "🎮 ¡BIENVENIDO A LA ZONA DE JUEGOS! 🔥\\n\\n💣 BOMBA: !bomba · jugar · salir",
                "🎲 DADOS 21: !dados21 100 · !tirar · !doble · !plantarse · !saldo · !retirar 50",
                "⚔️ RPS: !rps · !rps @usuario · !piedra · !papel · !tijera",
                "🎭 VERDAD O RETO: !vd · !jugarvd · !entrarvd · !iniciarvd · !verdad · !reto · !listo · !salirvd",
                "📜 !help bomba · !help dados · !help rps · !help verdad\\n👑 Creador: @Zhony6470\\n🐛 Cualquier bug, comunícate con él.",
            ]:
                await self.highrise.send_whisper(user.id, section)
            return

        if command == "!home":
            if len(parts) == 1:
                if user.id != self.owner_id and not await self.is_mod(user.id):
                    await self.highrise.send_whisper(
                        user.id,
                        "<#FF6666>🔒 Solo el dueño o los moderadores pueden usar este comando.",
                    )
                    return
                response = await self.position_manager_common.return_home()
            else:
                response = await handle_home(self, user, msg)

            if response:
                await self.highrise.send_whisper(user.id, response)
            return

        if command == "!reset":
            if len(parts) == 1:
                if user.id != self.owner_id and not await self.is_mod(user.id):
                    await self.highrise.send_whisper(
                        user.id,
                        "<#FF6666>🔒 Solo el dueño o los moderadores pueden reiniciar el bot.",
                    )
                    return
                await self.restart_with_message()
            else:
                await handle_reset(self, user, msg)
            return

        # 💣 Bomba
        if await self.bomba.handle(user, msg):
            return

        # 🎲 Dados 21
        if await self.dados21.handle(user, msg, private=False):
            return

        # ⚔️ Piedra, Papel o Tijera
        if await self.rps.handle(user, msg, private=False):
            return

        # 🎲 Verdad o Reto
        if await self.truth_or_dare.handle(user, msg):
            return

        if command == "!wallet":
            if user.id != self.owner_id and not self.role_manager.has_permission(user.id):
                await self.highrise.send_whisper(
                    user.id,
                    "<#FF6666>🔒 Necesitas el permiso avanzado para usar este comando.",
                )
                return
            response = await self.tip_manager.handle_command(self, "!wallet", user.id)
            if response:
                await self.highrise.send_whisper(user.id, response)
            return

        handlers = {
            "!set": handle_set_position,
            "!equip": handle_equip,
            "/equip": handle_equip,
            "!remove": handle_remove,
            "/remove": handle_remove,
            "!color": handle_color,
            "!getoutfit": handle_get_outfit,
            "/getoutfit": handle_get_outfit,
            "!dancebot": handle_botdance,
            "!botdance": handle_botdance,
            "!stopdance": handle_stopdance,
            "!stopbotdance": handle_stopdance,
        }

        handler = handlers.get(command)
        if handler:
            response = await handler(self, user, msg)
            if response:
                await self.highrise.send_whisper(user.id, response)
            return

        if command == "!emote":
            if len(parts) < 3 or not parts[1].startswith("@"):
                await self.highrise.send_whisper(
                    user.id,
                    f"<#FFCC66>🎭 Uso: !emote @{self.bot_username} <emote> "
                    f"o !emote @{self.bot_username} stop",
                )
                return

            target = parts[1][1:].casefold()
            if target != self.bot_username.casefold():
                return

            if user.id != self.owner_id and not await self.is_mod(user.id):
                await self.highrise.send_whisper(
                    user.id,
                    "<#FF6666>🔒 Solo el dueño o moderadores pueden controlar el emote del bot.",
                )
                return

            emote_name = " ".join(parts[2:]).strip().lower()
            if emote_name == "stop":
                response = await self.dance_manager.stop_bot_emote()
                await self.highrise.send_whisper(user.id, response)
                return

            if emote_name.isdigit():
                matched = self.emotes_manager.get_by_index(int(emote_name) - 1)
            else:
                matched = self.emotes_manager.get_by_name(emote_name)

            if not matched:
                await self.highrise.send_whisper(
                    user.id,
                    f"<#FFCC66>🎭 Emote no encontrado: {emote_name}.",
                )
                return

            response = await self.dance_manager.start_bot_emote(matched["emote"])
            await self.highrise.send_whisper(user.id, response)
            return

    async def on_message(
        self, user_id: str, conversation_id: str, is_new_conversation: bool
    ) -> None:
        """Responde !help en el buzón privado de Highrise."""
        print(f"[INBOX DEBUG] on_message recibido en bots/fun/main.py user_id={user_id} conversation_id={conversation_id} new={is_new_conversation}")
        try:
            response = await self.highrise.get_messages(conversation_id)
            if not isinstance(response, GetMessagesRequest.GetMessagesResponse):
                print(f"[INBOX DEBUG] Tipo de respuesta inesperado: {type(response).__name__}")
                return
            if not response.messages:
                print("[INBOX DEBUG] La conversación no contiene mensajes")
                return
            message = response.messages[0].content.strip().lower()
            print(f"[INBOX DEBUG] Primer mensaje de la conversación: {message!r}")
            if message != "!help":
                return
            await self.highrise.send_message(
                conversation_id,
                "🎮 JUEGOS DISPONIBLES\\n"
                "• !help verdad — Verdad o Reto\\n"
                "• !help rps — Piedra, Papel o Tijera\\n"
                "• !help dados — Dados 21\\n"
                "• !help bomba — Bomba"
            )
        except Exception as error:
            print(f"[FUN INBOX HELP] Error procesando !help: {error}")

    async def on_whisper(self, user: User, message: str) -> None:
        # BotJuegos solo responde a !help game y a las ayudas específicas.
        help_command = message.strip().lower()
        if help_command == "!help game" or help_command in {
            "!help bomba", "!help dados", "!help dados21",
            "!help rps", "!help verdad", "!help vd",
        }:
            await self.on_chat(user, help_command)
            return

    async def on_user_move(self, user: User, position) -> None:
        await self.truth_or_dare.on_user_move(user, position)

    async def on_user_leave(self, user: User) -> None:
        await self.rps.on_user_leave(user.id)
        await self.truth_or_dare.on_user_leave(user.id)

    async def on_tip(
        self, sender: User, receiver: User, tip: CurrencyItem | Item
    ) -> None:
        try:
            # RPS debe procesar primero sus apuestas para que no se registren
            # también como depósitos de la cartera de Dados 21.
            if await self.rps.handle_tip(sender, receiver, tip):
                return
            if await self.dados21.handle_tip(sender, receiver, tip):
                return
            await self.tip_manager.handle_tip(
                self.highrise, self.bot_id, sender, receiver, tip
            )
        except Exception as error:
            print(f"[FUN TIP] Error procesando propina: {error}")


definitions = [BotDefinition(Bot(), ROOM_ID, API_KEY)]

if __name__ == "__main__":
    if not ROOM_ID or not API_KEY:
        raise RuntimeError("ROOM_ID y BOT3_API_KEY deben estar configuradas.")
    asyncio.run(__main__.main(definitions))
