from __future__ import annotations

import asyncio
import os
import sys
from json import load
from pathlib import Path

from highrise import BaseBot, CurrencyItem, Item, SessionMetadata, User, __main__
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
from common.bot_state import BotStateManager
from common.dance import DanceManager
from services.emotes import EmotesManager
from services.roles import RoleManager
from bots.bot1.services.tips import TipManager
from bots.fun.games.verdad_reto import TruthOrDareGame
from bots.fun.games.rps import RpsGame


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

        await self.highrise.chat(
            f"<#66FF99>🎮 @{self.bot_username} está conectado. "
            "Escribe !help para ver los comandos."
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

        if msg.lower() == "!help game":
            await self.highrise.send_whisper(
                user.id,
                "\\n".join([
                    "<#66CCFF>🎮 JUEGOS",
                    "<#FFFFFF>🎭 VERDAD O RETO",
                    "<#FFFFFF>• !jugarvd - Crear partida",
                    "<#FFFFFF>• !entrarvd - Unirse",
                    "<#FFFFFF>• !iniciarvd - Iniciar partida",
                    "<#FFFFFF>• !rps - RPS contra BotJuegos",
                    "<#FFFFFF>• !rps @usuario - RPS contra jugador",
                    "<#FFFFFF>• !rps @usuario 10|50|100|500 - RPS con apuesta",
                ]),
            )
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

    async def on_whisper(self, user: User, message: str) -> None:
        if await self.rps.handle(user, message.strip(), private=True):
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
            if await self.rps.handle_tip(sender, receiver, tip):
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
