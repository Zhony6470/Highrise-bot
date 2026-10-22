from __future__ import annotations

import asyncio
import json
import random
import re
import unicodedata
from pathlib import Path

from highrise import Position, User
from bots.fun.games.chat_queue import send_game_chat

LOBBY_SECONDS = 20
ROUND_SECONDS = 20
DICTIONARY_FILE = Path(__file__).resolve().parents[1] / "data" / "bomba_dictionary.json"
CATEGORIES = (
    "Animales",
    "Frutas y verduras",
    "Países y ciudades",
    "Comidas y bebidas",
    "Cosas",
    "Nombres propios",
    "Colores",
)
# La ubicación se elige entre posiciones reales ocupadas en la sala, para evitar
# coordenadas arbitrarias que puedan dejar al usuario bajo el mapa o fuera del área.
FALLBACK_EMOTES = ("emote-superpunch", "emote-kicking", "emoji-crying", "emote-dance-tiktok")


def normalize(text: str) -> str:
    value = unicodedata.normalize("NFD", text.casefold().strip())
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    value = re.sub(r"[^a-z0-9ñü\s'-]", "", value)
    return re.sub(r"\s+", " ", value).strip()


class BombaGame:
    """Juego de bomba por sala: todos siguen participando aunque fallen una ronda."""

    def __init__(self, bot):
        self.bot = bot
        self.dictionary = self._load_dictionary()
        self.phase = "idle"
        self.creator_id: str | None = None
        self.creator_name = ""
        self.players: dict[str, User] = {}
        self.round_number = 0
        self.letter = ""
        self.category = ""
        self.round_words: set[str] = set()
        self.answers: dict[str, str] = {}
        self.round_players: dict[str, User] = {}
        self.task: asyncio.Task | None = None
        self.lock = asyncio.Lock()
        self.game_id = 0

    def _load_dictionary(self) -> dict[str, set[str]]:
        try:
            raw = json.loads(DICTIONARY_FILE.read_text(encoding="utf-8"))
            result = {}
            for category in CATEGORIES:
                result[category] = {
                    normalize(word) for word in raw.get(category, [])
                    if isinstance(word, str) and normalize(word)
                }
            return result
        except Exception as error:
            print(f"[BOMBA] No se pudo cargar el diccionario: {error}")
            return {category: set() for category in CATEGORIES}

    async def _chat(self, message: str):
        try:
            await send_game_chat(self.bot.highrise, message)
        except Exception as error:
            print(f"[BOMBA] Error enviando mensaje: {error}")

    async def _whisper(self, user_id: str, message: str):
        try:
            await self.bot.highrise.send_whisper(user_id, message)
        except Exception as error:
            print(f"[BOMBA] Error enviando privado: {error}")

    async def handle(self, user: User, message: str) -> bool:
        msg = message.strip()
        command = msg.casefold()
        if command == "!bomba":
            await self.start(user)
            return True
        if command == "jugar":
            await self.join(user)
            return True
        if command == "salir":
            if user.id in self.players:
                await self.leave(user)
                return True
            return self.phase != "idle"
        if command == "terminar":
            if self.phase != "idle" and user.id == self.creator_id:
                await self.stop(f"🛑 @{user.username} terminó la partida de Bomba.")
                return True
            return self.phase != "idle" and user.id in self.players
        if msg.startswith("!"):
            return False
        if self.phase == "round" and user.id in self.players:
            await self.submit_answer(user, msg)
            return True
        return False

    async def start(self, user: User):
        async with self.lock:
            if self.phase != "idle":
                await self._whisper(user.id, "Ya hay una partida de Bomba en esta sala. Escribe jugar para entrar.")
                return
            if not any(self.dictionary.get(category) for category in CATEGORIES):
                await self._whisper(user.id, "No pude iniciar Bomba porque el diccionario local no se cargó.")
                return
            self.game_id += 1
            game_id = self.game_id
            self.creator_id = user.id
            self.creator_name = user.username
            self.players = {user.id: user}
            self.phase = "lobby"
            self.round_number = 0
            self.task = asyncio.create_task(self._run(game_id))
        await self._chat(
            f"💣 ¡@{user.username} inició BOMBA! Inscripción abierta durante {LOBBY_SECONDS} segundos. "
            "Escribe jugar para participar. Para salir: salir. Solo el creador puede cancelar con terminar."
        )

    async def join(self, user: User):
        if self.phase == "idle":
            await self._whisper(user.id, "No hay una partida de Bomba abierta. Escribe !bomba para crear una.")
            return
        if user.id in self.players:
            await self._whisper(user.id, "Ya estás participando en Bomba.")
            return
        self.players[user.id] = user
        if self.phase == "lobby":
            await self._chat(f"💣 @{user.username} se unió a Bomba.")
        else:
            await self._chat(f"💣 @{user.username} entrará a partir de la próxima ronda.")
            self.answers.pop(user.id, None)

    async def leave(self, user: User):
        self.players.pop(user.id, None)
        self.answers.pop(user.id, None)
        await self._chat(f"🚪 @{user.username} salió de la partida de Bomba.")
        if not self.players and self.phase != "idle":
            await self.stop("💣 La partida de Bomba terminó porque no quedan participantes.")

    async def submit_answer(self, user: User, message: str):
        word = normalize(message)
        if user.id not in self.round_players:
            await self._whisper(user.id, "Ya estás inscrito, pero comienzas a responder desde la próxima ronda.")
            return
        if not word or user.id in self.answers:
            return
        if not word.startswith(normalize(self.letter)[:1]):
            await self._whisper(user.id, f"La palabra debe comenzar con la letra {self.letter}.")
            return
        if word not in self.dictionary.get(self.category, set()):
            await self._whisper(user.id, f"'{message}' no aparece en el diccionario de la categoría {self.category}.")
            return
        if word in self.round_words:
            await self._whisper(user.id, "Esa palabra ya fue utilizada en esta ronda. Prueba con otra.")
            return
        self.answers[user.id] = word
        self.round_words.add(word)
        await self._chat(f"✅ @{user.username} respondió a tiempo.")

    def _choose_prompt(self):
        options = []
        for category in CATEGORIES:
            by_letter: dict[str, list[str]] = {}
            for word in self.dictionary.get(category, set()):
                first = normalize(word)[:1]
                if first and first.isalpha():
                    by_letter.setdefault(first, []).append(word)
            for letter, candidates in by_letter.items():
                if candidates:
                    options.append((category, letter.upper()))
        if not options:
            return None
        return random.choice(options)

    async def _run(self, game_id: int):
        try:
            await asyncio.sleep(LOBBY_SECONDS)
            if game_id != self.game_id or self.phase != "lobby":
                return
            if not self.players:
                await self.stop("💣 La partida terminó: no hubo participantes.")
                return
            self.phase = "round"
            await self._chat(f"🚨 ¡Se cerró la inscripción! Participantes: {len(self.players)}. ¡Comienza Bomba!")
            while game_id == self.game_id and self.phase != "idle":
                prompt = self._choose_prompt()
                if not prompt:
                    await self.stop("💣 La partida terminó porque no hay palabras disponibles en el diccionario.")
                    return
                self.category, self.letter = prompt
                self.round_number += 1
                self.round_words = set()
                self.answers = {}
                self.round_players = dict(self.players)
                await self._chat(
                    f"💣 RONDA {self.round_number} | Categoría: {self.category} | "
                    f"Letra: {self.letter}. Tienen {ROUND_SECONDS} segundos para responder."
                )
                await asyncio.sleep(ROUND_SECONDS)
                if game_id != self.game_id or self.phase == "idle":
                    return
                failed = [player for player_id, player in list(self.round_players.items()) if player_id in self.players and player_id not in self.answers]
                if failed:
                    names = ", ".join(f"@{player.username}" for player in failed)
                    await self._chat(f"💥 ¡BOOM! No respondieron correctamente a tiempo: {names}. Siguen en el juego.")
                    await self._punish_players(failed)
                else:
                    await self._chat("🎉 ¡Todos respondieron a tiempo! La bomba pasa a la siguiente ronda.")
                await asyncio.sleep(2)
        except asyncio.CancelledError:
            pass
        except Exception as error:
            print(f"[BOMBA] Error en la partida: {error}")
            await self.stop("💣 La partida se detuvo por un error interno.")
        finally:
            if game_id == self.game_id and self.phase != "idle":
                self.phase = "idle"
                self.creator_id = None
                self.creator_name = ""
                self.players.clear()
                self.answers.clear()
                self.round_words.clear()
                self.task = None

    async def _punish_players(self, players: list[User]):
        try:
            room_users = await self.bot.highrise.get_room_users()
            positions = [
                position for room_user, position in room_users.content
                if room_user.id != self.bot.bot_id and position is not None
            ]
        except Exception as error:
            print(f"[BOMBA] No pude leer posiciones de la sala: {error}")
            positions = []
        emote_ids = [
            str(item.get("emote", "")).strip()
            for item in getattr(self.bot, "emotes_list", [])
            if item.get("emote")
        ]
        # Preferimos emotes cuyo nombre/ID sugiera explosión; si no existen, usamos uno conocido.
        bomb_emotes = [
            str(item.get("emote", "")).strip()
            for item in getattr(self.bot, "emotes_list", [])
            if item.get("emote") and any(token in (
                str(item.get("command", "")) + " " + str(item.get("emote", ""))
            ).casefold() for token in ("bomb", "explos", "boom"))
        ]
        explosion_emote = random.choice(bomb_emotes) if bomb_emotes else "emote-superpunch"
        try:
            await self.bot.highrise.send_emote(explosion_emote, self.bot.bot_id)
        except Exception as error:
            print(f"[BOMBA] No pude ejecutar el emote de explosión del bot: {error}")
        for player in players:
            if player.id not in self.players:
                continue
            if positions:
                try:
                    await self.bot.highrise.teleport(player.id, random.choice(positions))
                except Exception as error:
                    print(f"[BOMBA] No pude teletransportar a @{player.username}: {error}")
            if emote_ids:
                try:
                    await self.bot.highrise.send_emote(random.choice(emote_ids), player.id)
                except Exception as error:
                    print(f"[BOMBA] No pude ejecutar emote posterior sobre @{player.username}: {error}")
            await asyncio.sleep(0.35)

    async def stop(self, message: str):
        task = self.task
        self.game_id += 1
        self.phase = "idle"
        self.creator_id = None
        self.creator_name = ""
        self.players.clear()
        self.answers.clear()
        self.round_words.clear()
        self.round_players.clear()
        self.task = None
        if task and task is not asyncio.current_task():
            task.cancel()
        await self._chat(message)
