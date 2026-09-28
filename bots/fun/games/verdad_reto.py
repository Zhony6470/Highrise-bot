from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from typing import Awaitable, Callable

from highrise import User


TRUTH_QUESTIONS = [
    "¿Cuál ha sido la situación más vergonzosa que has vivido?",
    "¿Cuál es el secreto más gracioso que puedes contar?",
    "¿Qué cosa te da vergüenza admitir que te gusta?",
    "¿Cuál ha sido tu peor primera impresión de alguien?",
    "¿Alguna vez has mentido para evitar salir de casa?",
    "¿Qué es lo primero que notas cuando conoces a alguien?",
    "¿Cuál ha sido la excusa más rara que has usado?",
    "¿Qué hábito extraño tienes?",
    "¿Cuál es la cosa más impulsiva que has hecho?",
    "¿Alguna vez has enviado un mensaje a la persona equivocada?",
    "¿Qué canción te sabes completa aunque te dé pena admitirlo?",
    "¿Cuál ha sido tu momento más incómodo en una sala?",
    "¿Qué personaje de Highrise te representa más y por qué?",
    "¿Qué cosa cambiarías de tu personalidad?",
    "¿Cuál ha sido tu mayor metida de pata?",
]

CHALLENGES = [
    "Haz un baile durante 30 segundos.",
    "Haz un emote que elijas durante 20 segundos.",
    "Ve hasta otra zona de la sala y regresa.",
    "Quédate junto a otro jugador durante 20 segundos.",
    "Escribe una frase usando solamente emojis.",
    "Saluda de una forma completamente exagerada a la sala.",
    "Haz una pose y mantenla durante 20 segundos.",
    "Camina alrededor de la sala durante 30 segundos.",
    "Di en el chat tres cosas positivas sobre la sala.",
    "Haz tu mejor presentación como si fueras una celebridad.",
    "Elige a alguien y dile algo amable.",
    "Durante 20 segundos, responde solo con emojis.",
    "Haz una entrada dramática al centro de la sala.",
    "Inventa un apodo divertido para ti mismo.",
    "Escribe una frase sin usar la letra A.",
]


@dataclass
class GroupPlayer:
    user_id: str
    username: str


class TruthOrDareGame:
    CHOICE_SECONDS = 20
    ACTION_SECONDS = 60

    def __init__(
        self,
        bot,
        is_mod: Callable[[str], Awaitable[bool]],
    ):
        self.bot = bot
        self.is_mod = is_mod
        self.creator_id: str | None = None
        self.players: list[GroupPlayer] = []
        self.turn_index = 0
        self.state = "idle"
        self.current_choice_user_id: str | None = None
        self.current_choice_task: asyncio.Task | None = None
        self.current_action_task: asyncio.Task | None = None
        self.current_mode: str | None = None
        self.individual_choices: dict[str, asyncio.Task] = {}
        self.individual_actions: dict[str, asyncio.Task] = {}

    @property
    def active(self) -> bool:
        return self.state in {"waiting", "playing"}

    def _player_index(self, user_id: str) -> int:
        for index, player in enumerate(self.players):
            if player.user_id == user_id:
                return index
        return -1

    def _current_player(self) -> GroupPlayer | None:
        if not self.players or self.state != "playing":
            return None
        if self.turn_index >= len(self.players):
            self.turn_index = 0
        return self.players[self.turn_index]

    async def _chat(self, message: str) -> None:
        try:
            await self.bot.highrise.chat(message)
        except Exception as error:
            print(f"[FUN GAME] Error enviando mensaje: {error}")

    def _cancel_task(self, task: asyncio.Task | None) -> None:
        if task and not task.done():
            task.cancel()

    def _clear_current_turn(self) -> None:
        self._cancel_task(self.current_choice_task)
        self._cancel_task(self.current_action_task)
        self.current_choice_task = None
        self.current_action_task = None
        self.current_choice_user_id = None
        self.current_mode = None

    async def start_individual(self, user: User) -> None:
        if user.id in self.individual_choices:
            await self._chat(
                f"<#FFCC66>🎲 @{user.username}, ya tienes una elección pendiente. "
                "Escribe !verdad o !reto."
            )
            return

        await self._chat(
            f"<#66CCFF>🎲 @{user.username}, elige: <#66FF99>!verdad "
            f"<#FFFFFF>o <#FF6666>!reto. <#FFCC66>⏱️ Tienes "
            f"{self.CHOICE_SECONDS} segundos."
        )

        task = asyncio.create_task(self._individual_choice_timeout(user.id, user.username))
        self.individual_choices[user.id] = task

    async def _individual_choice_timeout(self, user_id: str, username: str) -> None:
        try:
            await asyncio.sleep(self.CHOICE_SECONDS)
            if user_id in self.individual_choices:
                self.individual_choices.pop(user_id, None)
                await self._chat(
                    f"<#FFCC66>⏰ @{username}, se agotó el tiempo para elegir. "
                    "Puedes volver a usar !vd."
                )
        except asyncio.CancelledError:
            return

    async def individual_choice(self, user: User, mode: str) -> bool:
        task = self.individual_choices.pop(user.id, None)
        if task is None:
            return False

        self._cancel_task(task)
        await self._send_prompt(user.username, mode, individual=True)
        self._cancel_task(self.individual_actions.pop(user.id, None))
        self.individual_actions[user.id] = asyncio.create_task(
            self._individual_action_timeout(user.id, user.username)
        )
        return True

    async def individual_direct(self, user: User, mode: str) -> None:
        if user.id in self.individual_choices:
            await self.individual_choice(user, mode)
            return
        await self._send_prompt(user.username, mode, individual=True)

    async def _individual_action_timeout(self, user_id: str, username: str) -> None:
        try:
            await asyncio.sleep(self.ACTION_SECONDS)
            task = self.individual_actions.pop(user_id, None)
            if task is not None:
                await self._chat(
                    f"<#FFCC66>⏰ @{username}, se agotó el tiempo. Puedes volver a jugar con !vd."
                )
        except asyncio.CancelledError:
            return

    async def _send_prompt(self, username: str, mode: str, individual: bool = False) -> None:
        if mode == "truth":
            prompt = random.choice(TRUTH_QUESTIONS)
            await self._chat(
                f"<#66FF99>🟢 VERDAD para @{username}: "
                f"<#FFFFFF>{prompt}"
            )
        else:
            prompt = random.choice(CHALLENGES)
            await self._chat(
                f"<#FF6666>🔴 RETO para @{username}: "
                f"<#FFFFFF>{prompt}"
            )

        if individual:
            await self._chat(
                f"<#FFCC66>Cuando termines, @{username}, escribe !listo."
            )

    async def start_group(self, user: User) -> None:
        if self.active:
            await self._chat(
                "<#FFCC66>🎲 Ya hay una partida de Verdad o Reto activa."
            )
            return

        self.creator_id = user.id
        self.players = [GroupPlayer(user.id, user.username)]
        self.turn_index = 0
        self.state = "waiting"

        await self._chat(
            f"<#66CCFF>🎲 ¡VERDAD O RETO GRUPAL INICIADO POR @{user.username}!\n"
            "<#FFFFFF>👥 Escribe !entrarvd para participar.\n"
            "<#FFCC66>▶️ Cuando estén listos, el creador usa !iniciarvd."
        )

    async def join_group(self, user: User) -> None:
        if self.state != "waiting":
            await self._chat(
                "<#FFCC66>⚠️ La partida ya comenzó o no existe."
            )
            return

        if self._player_index(user.id) >= 0:
            await self._chat(f"<#FFCC66>👥 @{user.username}, ya estás en la partida.")
            return

        self.players.append(GroupPlayer(user.id, user.username))
        await self._chat(
            f"<#66FF99>✅ @{user.username} se unió a la partida. "
            f"<#FFFFFF>👥 Jugadores: {len(self.players)}"
        )

    async def leave_group(self, user: User) -> None:
        index = self._player_index(user.id)
        if index < 0:
            await self._chat(f"<#FFCC66>⚠️ @{user.username}, no estás en la partida.")
            return

        was_current = self.state == "playing" and index == self.turn_index
        self.players.pop(index)

        if not self.players:
            await self._finish("🏁 La partida terminó porque no quedan jugadores.")
            return

        if index < self.turn_index:
            self.turn_index -= 1
        elif was_current and self.turn_index >= len(self.players):
            self.turn_index = 0

        if self.creator_id == user.id:
            self.creator_id = self.players[0].user_id
            await self._chat(
                f"<#FFCC66>👑 @{user.username} salió. "
                f"<#FFFFFF>El control pasa a @{self.players[0].username}."
            )
        else:
            await self._chat(f"<#FFCC66>🚪 @{user.username} salió de la partida.")

        if was_current:
            self._clear_current_turn()
            await self._start_current_turn()

    async def start_group_game(self, user: User) -> None:
        if self.state != "waiting":
            await self._chat("<#FFCC66>⚠️ No hay una partida esperando para comenzar.")
            return
        if user.id != self.creator_id and not await self.is_mod(user.id):
            await self._chat("<#FF6666>🔒 Solo el creador o un moderador puede iniciar la partida.")
            return
        if len(self.players) < 2:
            await self._chat("<#FFCC66>👥 Necesitas al menos 2 jugadores para comenzar.")
            return

        self.state = "playing"
        self.turn_index = 0
        await self._start_current_turn()

    async def _start_current_turn(self) -> None:
        if self.state != "playing" or not self.players:
            return

        player = self._current_player()
        if not player:
            await self._finish("🏁 La partida terminó porque no quedan jugadores.")
            return

        self._clear_current_turn()
        self.current_choice_user_id = player.user_id

        await self._chat(
            f"<#66CCFF>🎯 Turno de @{player.username}\n"
            f"<#66FF99>🟢 !verdad  <#FFFFFF>o "
            f"<#FF6666>🔴 !reto\n"
            f"<#FFCC66>⏱️ Tienes {self.CHOICE_SECONDS} segundos para elegir."
        )

        self.current_choice_task = asyncio.create_task(
            self._group_choice_timeout(player.user_id, player.username)
        )

    async def _group_choice_timeout(self, user_id: str, username: str) -> None:
        try:
            await asyncio.sleep(self.CHOICE_SECONDS)
            if (
                self.state == "playing"
                and self.current_choice_user_id == user_id
            ):
                await self._chat(
                    f"<#FFCC66>⏰ @{username} no eligió a tiempo. "
                    "Pierde el turno."
                )
                await self._advance_turn()
        except asyncio.CancelledError:
            return

    async def choose_group(self, user: User, mode: str) -> bool:
        if self.state != "playing":
            return False

        player = self._current_player()
        if not player or player.user_id != user.id:
            await self._chat(
                f"<#FFCC66>⚠️ @{user.username}, no es tu turno."
            )
            return True

        if self.current_choice_user_id != user.id:
            return True

        self._cancel_task(self.current_choice_task)
        self.current_choice_task = None
        self.current_choice_user_id = None
        self.current_mode = mode

        await self._send_prompt(user.username, mode)
        await self._chat(
            f"<#FFCC66>⏱️ @{user.username}, tienes "
            f"{self.ACTION_SECONDS} segundos. Escribe !listo al terminar."
        )

        self.current_action_task = asyncio.create_task(
            self._group_action_timeout(user.id, user.username)
        )
        return True

    async def _group_action_timeout(self, user_id: str, username: str) -> None:
        try:
            await asyncio.sleep(self.ACTION_SECONDS)
            if self.state == "playing" and self.current_choice_user_id is None:
                current = self._current_player()
                if current and current.user_id == user_id:
                    await self._chat(
                        f"<#FFCC66>⏰ @{username}, se agotó el tiempo. "
                        "Pierdes el turno."
                    )
                    await self._advance_turn()
        except asyncio.CancelledError:
            return

    async def ready(self, user: User) -> bool:
        individual_task = self.individual_actions.pop(user.id, None)
        if individual_task is not None:
            self._cancel_task(individual_task)
            await self._chat(f"<#66FF99>✅ @{user.username} completó su ronda individual.")
            return True

        if self.state == "playing":
            player = self._current_player()
            if not player or player.user_id != user.id:
                await self._chat(f"<#FFCC66>⚠️ @{user.username}, no es tu turno.")
                return True

            self._cancel_task(self.current_action_task)
            self.current_action_task = None
            await self._chat(
                f"<#66FF99>✅ @{user.username} completó su turno."
            )
            await self._advance_turn()
            return True

        return False

    async def _advance_turn(self) -> None:
        self._clear_current_turn()

        if not self.players:
            await self._finish("🏁 La partida terminó porque no quedan jugadores.")
            return

        self.turn_index = (self.turn_index + 1) % len(self.players)
        await self._start_current_turn()

    async def end_group(self, user: User, cancelled: bool = False) -> None:
        if not self.active:
            await self._chat("<#FFCC66>⚠️ No hay una partida grupal activa.")
            return

        if user.id != self.creator_id and not await self.is_mod(user.id):
            await self._chat(
                "<#FF6666>🔒 Solo el creador o un moderador puede "
                "finalizar la partida."
            )
            return

        if cancelled:
            await self._finish("🛑 La partida de Verdad o Reto fue cancelada.")
        else:
            await self._finish(
                f"<#66FF99>🏁 ¡PARTIDA TERMINADA!\n"
                f"<#FFFFFF>👥 Participantes: {len(self.players)}\n"
                "<#FFCC66>🎲 ¡Gracias por jugar!"
            )

    async def _finish(self, message: str) -> None:
        self._clear_current_turn()
        for task in list(self.individual_choices.values()):
            self._cancel_task(task)
        for task in list(self.individual_actions.values()):
            self._cancel_task(task)
        self.individual_choices.clear()
        self.individual_actions.clear()
        self.creator_id = None
        self.players.clear()
        self.turn_index = 0
        self.state = "idle"
        await self._chat(message)

    async def on_user_leave(self, user_id: str) -> None:
        # Se usa directamente el ID para procesar la salida de la sala.
        index = self._player_index(user_id)
        if index < 0:
            return

        username = self.players[index].username
        was_current = self.state == "playing" and index == self.turn_index
        self.players.pop(index)

        if not self.players:
            await self._finish("🏁 La partida terminó porque no quedan jugadores.")
            return

        if index < self.turn_index:
            self.turn_index -= 1
        elif was_current and self.turn_index >= len(self.players):
            self.turn_index = 0

        if self.creator_id == user_id:
            self.creator_id = self.players[0].user_id
            await self._chat(
                f"<#FFCC66>🚪 @{username} salió. <#FFFFFF>El control pasa a @{self.players[0].username}."
            )
        else:
            await self._chat(f"<#FFCC66>🚪 @{username} salió de la partida.")

        if was_current:
            self._clear_current_turn()
            await self._start_current_turn()

    async def handle(self, user: User, command: str) -> bool:
        if command == "!vd":
            if self.active:
                await self._chat(
                    "<#FFCC66>⚠️ Hay una partida grupal activa. "
                    "Espera a tu turno."
                )
            else:
                await self.start_individual(user)
            return True

        if command == "!verdad":
            if self.state == "playing":
                return await self.choose_group(user, "truth")
            if user.id in self.individual_choices:
                return await self.individual_choice(user, "truth")
            if not self.active:
                await self.individual_direct(user, "truth")
                return True
            return True

        if command == "!reto":
            if self.state == "playing":
                return await self.choose_group(user, "dare")
            if user.id in self.individual_choices:
                return await self.individual_choice(user, "dare")
            if not self.active:
                await self.individual_direct(user, "dare")
                return True
            return True

        if command == "!jugarvd":
            await self.start_group(user)
            return True
        if command == "!entrarvd":
            await self.join_group(user)
            return True
        if command == "!salirvd":
            await self.leave_group(user)
            return True
        if command == "!iniciarvd":
            await self.start_group_game(user)
            return True
        if command == "!listo":
            handled = await self.ready(user)
            if not handled and self.active:
                await self._chat(f"<#FFCC66>⚠️ @{user.username}, no es tu turno.")
            return True
        if command == "!terminarvd":
            await self.end_group(user)
            return True
        if command == "!cancelarvd":
            await self.end_group(user, cancelled=True)
            return True

        return False
