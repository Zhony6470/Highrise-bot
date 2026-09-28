from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field

from highrise import CurrencyItem, Item, User


CHOICE_SECONDS = 15
BET_SECONDS = 60
ALLOWED_BETS = {10, 50, 100, 500}

CHOICES = {
    "!piedra": "rock",
    "!papel": "paper",
    "!tijera": "scissors",
}

DISPLAY = {
    "rock": "✊ Piedra",
    "paper": "📄 Papel",
    "scissors": "✂️ Tijera",
}

WINS = {
    ("rock", "scissors"),
    ("paper", "rock"),
    ("scissors", "paper"),
}

BET_BARS = {
    10: "gold_bar_10",
    50: "gold_bar_50",
    100: "gold_bar_100",
    500: "gold_bar_500",
}


@dataclass
class RpsMatch:
    match_id: str
    player_one: User
    player_two: User | None
    bet: int = 0
    choices: dict[str, str] = field(default_factory=dict)
    paid: dict[str, int] = field(default_factory=dict)
    bot_choice: str | None = None
    task: asyncio.Task | None = None
    state: str = "playing"


class RpsGame:
    def __init__(self, bot):
        self.bot = bot
        self.matches: dict[str, RpsMatch] = {}
        self.user_matches: dict[str, str] = {}
        self.counter = 0

    async def _chat(self, message: str) -> None:
        await self.bot.highrise.chat(message)

    async def _whisper(self, user_id: str, message: str) -> None:
        try:
            await self.bot.highrise.send_whisper(user_id, message)
        except Exception as error:
            print(f"[RPS] Error enviando privado: {error}")

    def _new_id(self) -> str:
        self.counter += 1
        return f"rps-{self.counter}"

    def _busy(self, user_id: str) -> bool:
        return user_id in self.user_matches

    async def handle(self, user: User, message: str, private: bool = False) -> bool:
        parts = message.strip().split()
        if not parts:
            return False

        command = parts[0].lower()

        if command == "!rps":
            await self.start_command(user, parts)
            return True

        if command in CHOICES:
            return await self.receive_choice(user, command, private)

        return False

    async def start_command(self, user: User, parts: list[str]) -> None:
        if len(parts) > 3:
            await self._whisper(user.id, "<#FFCC66>🎮 Uso: !rps, !rps @usuario o !rps @usuario <10|50|100|500>")
            return

        if len(parts) == 1:
            if self._busy(user.id):
                await self._whisper(user.id, "<#FFCC66>⚠️ Ya tienes una partida de RPS activa.")
                return

                match = RpsMatch(
                match_id=self._new_id(),
                player_one=user,
                player_two=None,
                bot_choice=random.choice(list(DISPLAY)),
            )
            self.matches[match.match_id] = match
            self.user_matches[user.id] = match.match_id

            await self._chat(
                f"<#66CCFF>⚔️ RPS: @{user.username} vs 🤖 @{self.bot.bot_username}. "
                "La elección de @"
                f"{user.username} será privada."
            )
            await self._send_choice_prompt(user)
            match.task = asyncio.create_task(self._choice_timeout(match.match_id))
            return

        target_text = parts[1]
        if not target_text.startswith("@") or not target_text[1:].strip():
            await self._whisper(user.id, "<#FFCC66>🎮 Uso: !rps @usuario [10|50|100|500]")
            return

        target_username = target_text[1:].strip()
        target_id = await self.bot.get_user_id(target_username)
        if not target_id:
            try:
                response = await self.bot.webapi.get_users(username=target_username)
                matched = next(
                    (
                        item for item in response.users
                        if item.username.casefold() == target_username.casefold()
                    ),
                    None,
                )
                if matched:
                    target_id = matched.id
                    target_username = matched.username
            except Exception as error:
                print(f"[RPS] Error buscando @{target_username}: {error}")

        if not target_id:
            await self._whisper(user.id, "<#FFCC66>🔎 No encontré a ese usuario.")
            return
        if target_id == user.id:
            await self._whisper(user.id, "<#FFCC66>⚠️ No puedes desafiarte a ti mismo.")
            return
        if target_id == getattr(self.bot, "bot_id", None):
            await self._whisper(user.id, "<#FFCC66>🤖 Para jugar contra mí usa simplemente !rps.")
            return
        if self._busy(user.id):
            await self._whisper(user.id, "<#FFCC66>⚠️ Ya tienes una partida de RPS activa.")
            return
        if self._busy(target_id):
            await self._whisper(user.id, "<#FFCC66>⚠️ Ese jugador ya está en otra partida de RPS.")
            return

        target_user = await self._get_room_user(target_id, target_username)
        if target_user is None:
            await self._whisper(
                user.id,
                "<#FFCC66>⚠️ Ese jugador debe estar en la sala para jugar RPS.",
            )
            return

        bet = 0
        if len(parts) == 3:
            try:
                bet = int(parts[2])
            except ValueError:
                await self._whisper(user.id, "<#FFCC66>💰 Apuesta válida: 10, 50, 100 o 500G.")
                return
            if bet not in ALLOWED_BETS:
                await self._whisper(user.id, "<#FFCC66>💰 Apuesta válida: 10, 50, 100 o 500G.")
                return

        match = RpsMatch(
            match_id=self._new_id(),
            player_one=user,
            player_two=target_user,
            bet=bet,
            state="waiting_bets" if bet else "playing",
        )
        self.matches[match.match_id] = match
        self.user_matches[user.id] = match.match_id
        self.user_matches[target_id] = match.match_id

        if bet:
            await self._chat(
                f"<#66CCFF>⚔️ RPS: @{user.username} desafió a @{target_user.username}. "
                f"💰 Apuesta: {bet}G por jugador."
            )
            await self._whisper(
                user.id,
                f"<#FFCC66>💰 Para confirmar la partida, envía exactamente {bet}G de propina a @{self.bot.bot_username}.",
            )
            await self._whisper(
                target_id,
                f"<#66CCFF>⚔️ @{user.username} te desafió a RPS por {bet}G. "
                f"Para aceptar, envía exactamente {bet}G de propina a @{self.bot.bot_username}.",
            )
            match.task = asyncio.create_task(self._bet_timeout(match.match_id))
        else:
            await self._chat(
                f"<#66CCFF>⚔️ RPS: @{user.username} 🆚 @{target_user.username}. "
                "Las elecciones serán privadas."
            )
            await self._send_choice_prompt(user)
            await self._send_choice_prompt(target_user)
            match.task = asyncio.create_task(self._choice_timeout(match.match_id))

    async def _get_room_user(self, user_id: str, username: str) -> User | None:
        try:
            response = await self.bot.highrise.get_room_users()
            for room_user, _ in response.content:
                if room_user.id == user_id:
                    return room_user
        except Exception as error:
            print(f"[RPS] Error obteniendo usuario de sala: {error}")
        return None

    async def _send_choice_prompt(self, user: User) -> None:
        await self._whisper(
            user.id,
            "<#66CCFF>🎮 RPS — elige por privado:\n"
            "✊ !piedra\n"
            "📄 !papel\n"
            "✂️ !tijera\n"
            f"⏳ Tienes {CHOICE_SECONDS} segundos.",
        )

    async def receive_choice(self, user: User, command: str, private: bool) -> bool:
        match_id = self.user_matches.get(user.id)
        if not match_id:
            return False

        match = self.matches.get(match_id)
        if not match or match.state != "playing":
            if private:
                await self._whisper(user.id, "<#FFCC66>⚠️ No tienes una elección pendiente.")
            return True

        if not private:
            await self._whisper(
                user.id,
                "<#FFCC66>🔐 Tu elección debe enviarse por privado a BotJuegos.",
            )
            return True

        if user.id in match.choices:
            await self._whisper(user.id, "<#FFCC66>⚠️ Ya registré tu elección.")
            return True

        match.choices[user.id] = CHOICES[command]
        await self._whisper(user.id, "<#66FF99>🔒 Elección recibida. Esperando al rival...")

        if match.player_two is None:
            await self._finish_match(match)
        elif len(match.choices) == 2:
            await self._finish_match(match)

        return True

    async def handle_tip(self, sender: User, receiver: User, tip: CurrencyItem | Item) -> bool:
        if receiver.id != getattr(self.bot, "bot_id", None):
            return False
        if not isinstance(tip, CurrencyItem):
            return False

        match_id = self.user_matches.get(sender.id)
        if not match_id:
            return False

        match = self.matches.get(match_id)
        if not match or match.state != "waiting_bets":
            return False

        if sender.id not in {match.player_one.id, match.player_two.id if match.player_two else ""}:
            return False

        if sender.id in match.paid:
            await self._refund(sender.id, tip.amount)
            await self._whisper(
                sender.id,
                f"<#FFCC66>⚠️ Ya habías confirmado tu apuesta. Te devolví los {tip.amount}G adicionales.",
            )
            return True

        if tip.amount != match.bet:
            await self._whisper(
                sender.id,
                f"<#FF6666>💰 La apuesta es exactamente {match.bet}G. "
                f"Recibí {tip.amount}G; intentaré devolverte el monto.",
            )
            await self._refund(sender.id, tip.amount)
            return True

        match.paid[sender.id] = tip.amount
        await self._whisper(
            sender.id,
            f"<#66FF99>💰 Apuesta recibida: {tip.amount}G. "
            "Esperando al otro jugador.",
        )

        if match.player_two and len(match.paid) == 2:
            match.state = "playing"
            self._cancel_task(match.task)
            await self._chat(
                f"<#66CCFF>💰 Apuesta confirmada: {match.bet * 2}G en el pozo. "
                "¡Comienza el RPS!"
            )
            await self._send_choice_prompt(match.player_one)
            await self._send_choice_prompt(match.player_two)
            match.task = asyncio.create_task(self._choice_timeout(match.match_id))

        return True

    async def _finish_match(self, match: RpsMatch) -> None:
        if match.match_id not in self.matches:
            return

        self._cancel_task(match.task)

        if match.player_two is None:
            player_choice = match.choices.get(match.player_one.id)
            if not player_choice:
                await self._cleanup(match)
                return

            bot_choice = match.bot_choice or random.choice(list(DISPLAY))
            result = self._result(player_choice, bot_choice)
            if result == "draw":
                text = "🤝 ¡Empate!"
            elif result == "win":
                text = f"🏆 ¡@{match.player_one.username} gana!"
            else:
                text = "🤖 ¡BotJuegos gana!"

            await self._chat(
                "<#66CCFF>⚔️ RESULTADO RPS\n"
                f"@{match.player_one.username} → {DISPLAY[player_choice]}\n"
                f"🤖 @{self.bot.bot_username} → {DISPLAY[bot_choice]}\n"
                f"<#FFFFFF>{text}"
            )
            await self._cleanup(match)
            return

        p1 = match.player_one
        p2 = match.player_two
        p1_choice = match.choices.get(p1.id)
        p2_choice = match.choices.get(p2.id)

        if not p1_choice and not p2_choice:
            await self._refund_all(match)
            await self._chat("<#FFCC66>🤝 Ninguno eligió a tiempo. La partida fue cancelada y las apuestas devueltas.")
            await self._cleanup(match)
            return

        if not p1_choice or not p2_choice:
            winner = p2 if p1_choice is None else p1
            loser = p1 if winner.id == p2.id else p2
            await self._resolve_winner(match, winner, loser, reason="no eligió a tiempo")
            return

        result = self._result(p1_choice, p2_choice)
        if result == "draw":
            await self._refund_all(match)
            await self._chat(
                f"<#66CCFF>🤝 EMPATE\n"
                f"@{p1.username} → {DISPLAY[p1_choice]}\n"
                f"@{p2.username} → {DISPLAY[p2_choice]}\n"
                f"<#66FF99>💰 Las apuestas fueron devueltas."
            )
            await self._cleanup(match)
            return

        winner = p1 if result == "win" else p2
        loser = p2 if result == "win" else p1
        await self._resolve_winner(match, winner, loser)

    async def _resolve_winner(
        self,
        match: RpsMatch,
        winner: User,
        loser: User,
        reason: str = "",
    ) -> None:
        if match.bet:
            prize = match.bet * 2
            paid = await self._pay(winner.id, prize)
            if not paid:
                await self._chat(
                    "<#FF6666>💸 No pude entregar el premio automáticamente. "
                    "La partida queda marcada para revisión."
                )
                await self._cleanup(match)
                return

        suffix = f" ({reason})" if reason else ""
        p1_choice = match.choices.get(match.player_one.id, "—")
        p2_choice = match.choices.get(match.player_two.id, "—") if match.player_two else "—"
        message = (
            "<#66CCFF>⚔️ RESULTADO RPS\n"
            f"@{match.player_one.username} → {DISPLAY.get(p1_choice, '❔ Sin elección')}\n"
            f"@{match.player_two.username if match.player_two else '—'} → {DISPLAY.get(p2_choice, '❔ Sin elección')}\n"
            f"<#66FF99>🏆 ¡@{winner.username} gana{suffix}!"
        )
        if match.bet:
            message += f"\n💰 Premio: {match.bet * 2}G"
        await self._chat(message)
        await self._cleanup(match)

    async def _pay(self, user_id: str, amount: int) -> bool:
        if amount not in {20, 100, 200, 1000}:
            return False
        base = amount // 2
        bar = BET_BARS[base]
        try:
            first = await self.bot.highrise.tip_user(user_id, bar)
            first_value = getattr(first, "result", first)
            second = await self.bot.highrise.tip_user(user_id, bar)
            second_value = getattr(second, "result", second)
            return first_value == "success" and second_value == "success"
        except Exception as error:
            print(f"[RPS] Error pagando {amount}G a {user_id}: {error}")
            return False

    async def _refund(self, user_id: str, amount: int) -> bool:
        if amount <= 0:
            return False

        bars = []
        remaining = amount
        for value, bar in sorted(BET_BARS.items(), reverse=True):
            count, remaining = divmod(remaining, value)
            bars.extend([bar] * count)

        if remaining:
            return False

        try:
            for bar in bars:
                result = await self.bot.highrise.tip_user(user_id, bar)
                if getattr(result, "result", result) != "success":
                    return False
            return True
        except Exception as error:
            print(f"[RPS] Error devolviendo {amount}G a {user_id}: {error}")
            return False

    async def _refund_all(self, match: RpsMatch) -> None:
        for user_id, amount in list(match.paid.items()):
            await self._refund(user_id, amount)

    async def _bet_timeout(self, match_id: str) -> None:
        try:
            await asyncio.sleep(BET_SECONDS)
            match = self.matches.get(match_id)
            if not match or match.state != "waiting_bets":
                return

            await self._refund_all(match)
            await self._chat(
                "<#FFCC66>⏳ RPS cancelado: no se recibieron las dos apuestas a tiempo. "
                "Las apuestas recibidas fueron devueltas."
            )
            await self._cleanup(match)
        except asyncio.CancelledError:
            pass

    async def _choice_timeout(self, match_id: str) -> None:
        try:
            await asyncio.sleep(CHOICE_SECONDS)
            match = self.matches.get(match_id)
            if match and match.state == "playing":
                await self._finish_match(match)
        except asyncio.CancelledError:
            pass

    async def on_user_leave(self, user_id: str) -> None:
        match_id = self.user_matches.get(user_id)
        if not match_id:
            return

        match = self.matches.get(match_id)
        if not match:
            self.user_matches.pop(user_id, None)
            return

        if match.state == "waiting_bets":
            await self._refund_all(match)
            await self._chat("<#FFCC66>⚠️ Un jugador salió. La partida de RPS fue cancelada y las apuestas devueltas.")
            await self._cleanup(match)
            return

        if match.player_two is None:
            await self._cleanup(match)
            return

        other = match.player_two if user_id == match.player_one.id else match.player_one
        if user_id in match.choices:
            await self._resolve_winner(match, other, match.player_one if other.id == match.player_two.id else match.player_two, reason="el rival salió de la sala")
        else:
            await self._resolve_winner(match, other, match.player_one if other.id == match.player_two.id else match.player_two, reason="el rival salió de la sala")

    async def _cleanup(self, match: RpsMatch) -> None:
        self._cancel_task(match.task)
        self.matches.pop(match.match_id, None)
        self.user_matches.pop(match.player_one.id, None)
        if match.player_two:
            self.user_matches.pop(match.player_two.id, None)

    @staticmethod
    def _cancel_task(task: asyncio.Task | None) -> None:
        if task and not task.done():
            task.cancel()

    @staticmethod
    def _result(first: str, second: str) -> str:
        if first == second:
            return "draw"
        return "win" if (first, second) in WINS else "lose"
