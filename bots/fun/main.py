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


DATA_FILE = str(ROOT_DIR / "bots" / "fun" / "data" / "data.json")
EMOTES_FILE = str(ROOT_DIR / "common" / "emotes.json")
ROLES_FILE = str(ROOT_DIR / "roles.json")
ROOM_ID = os.environ.get("ROOM_ID", "")
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

    async def restore_position(self):
        try:
            position = self.position_manager_common.get_saved_position()
            if position:
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
        print(
            f"[FUN] Conectado. Bot ID: {self.bot_id} | "
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

        if command in targeted_commands and not await self._is_targeted_for_me(msg):
            return

        if command == "!help":
            await self.highrise.send_whisper(
                user.id,
                "\n".join([
                    "<#66CCFF>🎮 BOT DE JUEGOS",
                    f"<#FFFFFF>• !help - Ver esta ayuda",
                    "<#FFFFFF>• !set @BotJuegos - Guardar posición del bot",
                    "<#FFFFFF>• !home @BotJuegos - Volver a la posición guardada",
                    "<#FFFFFF>• !reset @BotJuegos - Reiniciar el bot",
                    "<#FFFFFF>• !dancebot @BotJuegos - Activar baile",
                    "<#FFFFFF>• !stopdance @BotJuegos - Detener baile",
                    "<#FFFFFF>• !emote @BotJuegos <emote> - Activar emote",
                    "<#FFFFFF>• !emote @BotJuegos stop - Detener emote",
                    "<#FFFFFF>• !equip @BotJuegos <prenda> - Cambiar outfit",
                    "<#FFFFFF>• !remove @BotJuegos <categoria> - Quitar prenda",
                    "<#FFFFFF>• !color @BotJuegos <categoria> <numero> - Cambiar color",
                    "<#FFFFFF>• !getoutfit @BotJuegos - Ver outfit",
                ]),
            )
            return

        if command == "!home":
            response = await handle_home(self, user, msg)
            if response:
                await self.highrise.send_whisper(user.id, response)
            return

        if command == "!reset":
            await handle_reset(self, user, msg)
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

    async def on_tip(
        self, sender: User, receiver: User, tip: CurrencyItem | Item
    ) -> None:
        try:
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
