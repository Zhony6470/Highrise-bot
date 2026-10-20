from __future__ import annotations

import asyncio
import random
from pathlib import Path

from highrise import CurrencyItem, Item, User
from services.storage import load_json, save_json

LOBBY_SECONDS = 15
TURN_SECONDS = 15
MIN_BET = 10
MAX_BET = 100
BET_STEP = 10
MIN_WITHDRAWAL = 50
BET_BARS = {1: "gold_bar_1", 5: "gold_bar_5", 10: "gold_bar_10", 50: "gold_bar_50", 100: "gold_bar_100", 500: "gold_bar_500"}


class Dados21Game:
    """Partida global de Dados 21 con cartera persistente y turnos limitados."""

    def __init__(self, bot):
        self.bot = bot
        self.data_file = str(Path(__file__).resolve().parents[1] / "data" / "dados21_wallet.json")
        self.wallet = load_json(self.data_file, {"users": {}, "pending_deposits": {}})
        self.wallet.setdefault("users", {})
        self.wallet.setdefault("pending_deposits", {})
        self.lobby: dict[str, dict] = {}
        self.active = False
        self.phase = "idle"
        self.task: asyncio.Task | None = None
        self.players: list[dict] = []
        self.turn_index = 0
        self.current: dict | None = None

    def _save(self):
        save_json(self.data_file, self.wallet)

    def _account(self, user_id: str) -> dict:
        return self.wallet["users"].setdefault(user_id, {"balance": 0, "winnings": 0, "username": ""})

    async def _whisper(self, user_id: str, message: str):
        try:
            await self.bot.highrise.send_whisper(user_id, message)
        except Exception as error:
            print(f"[DADOS21] Error enviando privado: {error}")

    async def _chat(self, message: str):
        await self.bot.highrise.chat(message)

    async def handle(self, user: User, message: str, private: bool = False) -> bool:
        parts = message.strip().split()
        if not parts:
            return False
        command = parts[0].lower()
        if command not in {"!dados21", "!tirar", "!doble", "!plantarse", "!saldo", "!salir", "!depositar", "!retirar"}:
            return False

        if command == "!dados21":
            if private:
                await self._whisper(user.id, "Usa !dados21 y las acciones en el chat de la sala.")
                return True
            if len(parts) != 2 or not parts[1].isdigit():
                await self._whisper(user.id, "Uso: !dados21 <10|20|30|...|100>")
                return True
            bet = int(parts[1])
            if bet < MIN_BET or bet > MAX_BET or bet % BET_STEP:
                await self._whisper(user.id, "La apuesta debe ser 10, 20, 30, ... o 100 G.")
                return True
            if self.phase not in {"idle", "lobby"}:
                await self._whisper(user.id, "Ya hay una partida en curso. Espera a que termine.")
                return True
            if user.id in self.lobby:
                await self._whisper(user.id, "Ya estás inscrito en esta partida.")
                return True
            account = self._account(user.id)
            if account["balance"] < bet:
                await self._whisper(user.id, f"Saldo insuficiente: {account['balance']} G. Envía oro al bot; tu saldo se actualizará automáticamente.")
                return True
            account["balance"] -= bet
            account["username"] = user.username
            self._save()
            self.lobby[user.id] = {"user": user, "bet": bet, "total": 0, "state": "waiting"}
            if self.phase == "idle":
                self.phase = "lobby"
                self.task = asyncio.create_task(self._lobby_timeout())
                await self._chat(f"🎲 Dados 21: inscripción abierta durante {LOBBY_SECONDS} segundos. Apuesta de @{user.username}: {bet} G. Usa !dados21 <10-100> para entrar.")
            else:
                await self._chat(f"🎲 @{user.username} se unió a Dados 21 con {bet} G.")
            await self._whisper(user.id, f"Inscripción confirmada por {bet} G. Espera el inicio.")
            return True

        if command == "!saldo":
            account = self._account(user.id)
            await self._whisper(user.id, f"Saldo: {account['balance']} G.")
            return True

        if command == "!depositar":
            if len(parts) != 2 or not parts[1].isdigit() or int(parts[1]) < 10 or int(parts[1]) % 10:
                await self._whisper(user.id, "Uso: !depositar <cantidad en múltiplos de 10 G, mínimo 10 G>.")
                return True
            amount = int(parts[1])
            self.wallet["pending_deposits"][user.id] = {"amount": amount, "username": user.username}
            self._save()
            await self._whisper(user.id, f"Envía exactamente {amount} G de propina a @{self.bot.bot_username} en la sala para cargar tu saldo. La solicitud queda pendiente hasta recibir esa propina.")
            return True

        if command == "!retirar":
            if len(parts) != 2 or not parts[1].isdigit():
                await self._whisper(user.id, "Uso: !retirar <cantidad>. Mínimo 50 G.")
                return True
            amount = int(parts[1])
            account = self._account(user.id)
            if amount < MIN_WITHDRAWAL:
                await self._whisper(user.id, "El retiro mínimo es de 50 G.")
                return True
            if amount > account["winnings"] or amount > account["balance"]:
                await self._whisper(user.id, "Solo puedes retirar ganancias disponibles; revisa !saldo.")
                return True
            if not await self._send_amount(user.id, amount):
                await self._whisper(user.id, "No pude completar el retiro. Tu saldo no fue descontado; inténtalo más tarde.")
                return True
            account["balance"] -= amount
            account["winnings"] -= amount
            self._save()
            await self._whisper(user.id, f"Retiro enviado: {amount} G.")
            return True

        if command == "!salir":
            if self.phase != "lobby" or user.id not in self.lobby:
                await self._whisper(user.id, "Solo puedes salir durante la inscripción, antes de que comience la partida.")
                return True
            entry = self.lobby.pop(user.id)
            account = self._account(user.id)
            account["balance"] += entry["bet"]
            self._save()
            await self._whisper(user.id, f"Saliste de la inscripción; se devolvieron {entry['bet']} G a tu saldo.")
            if not self.lobby:
                self._cancel_task(self.task)
                self.task = None
                self.phase = "idle"
                await self._chat("🎲 Inscripción cancelada: no quedan jugadores.")
            return True

        if command in {"!tirar", "!doble", "!plantarse"}:
            if private:
                await self._whisper(user.id, "Usa !tirar, !doble o !plantarse en el chat de la sala.")
                return True
            if self.phase != "playing" or not self.current or self.current["user"].id != user.id:
                await self._whisper(user.id, "No es tu turno en Dados 21.")
                return True
            if command == "!plantarse":
                await self._stand_current()
            else:
                count = 1 if command == "!tirar" else 2
                dice = [random.randint(1, 6) for _ in range(count)]
                self.current["total"] += sum(dice)
                await self._whisper(user.id, f"🎲 Dados: {', '.join(map(str, dice))}. Total: {self.current['total']}.")
                if self.current["total"] > 21:
                    await self._whisper(user.id, "💥 Te pasaste de 21. Pierdes esta ronda.")
                    await self._resolve_current(False)
                elif self.current["total"] == 21:
                    await self._whisper(user.id, "🎯 ¡Llegaste a 21!")
                    await self._stand_current()
                else:
                    self._arm_turn_timeout()
            return True

        return True

    async def handle_tip(self, sender: User, receiver: User, tip: CurrencyItem | Item) -> bool:
        """Acredita automáticamente toda propina de oro recibida por este bot."""
        if receiver.id != getattr(self.bot, "bot_id", None):
            return False
        if not isinstance(tip, CurrencyItem):
            return False

        account = self._account(sender.id)
        account["username"] = sender.username
        account["balance"] += tip.amount
        account["last_deposit"] = tip.amount
        self.wallet["pending_deposits"].pop(sender.id, None)
        self._save()
        await self._whisper(sender.id, f"Saldo: {account['balance']} G.")
        print(
            f"[DADOS21] Depósito automático: user={sender.id} "
            f"username=@{sender.username} amount={tip.amount} "
            f"balance={account['balance']}"
        )
        return True

    async def _lobby_timeout(self):
        try:
            await asyncio.sleep(LOBBY_SECONDS)
            if self.phase != "lobby" or not self.lobby:
                return
            self._cancel_task(self.task)
            self.task = None
            self.players = list(self.lobby.values())
            self.lobby.clear()
            self.phase = "playing"
            self.active = True
            await self._chat(f"🎲 Inscripción cerrada. Comienza Dados 21 con {len(self.players)} jugador(es).")
            await self._next_player()
        except asyncio.CancelledError:
            pass

    async def _next_player(self):
        if self.turn_index >= len(self.players):
            self.phase = "idle"
            self.active = False
            self.current = None
            self.players = []
            await self._chat("🎲 Dados 21 ha terminado. Ya se puede iniciar otra partida.")
            return
        self.current = self.players[self.turn_index]
        self.current["total"] = 0
        self.current["state"] = "playing"
        user = self.current["user"]
        await self._whisper(user.id, f"🎲 Es tu turno contra @{self.bot.bot_username}. Usa !tirar (un dado), !doble (dos dados) o !plantarse. Tienes {TURN_SECONDS} segundos.")
        await self._chat(f"🎲 Turno de @{user.username}.")
        self._arm_turn_timeout()

    def _arm_turn_timeout(self):
        self._cancel_task(self.task)
        self.task = asyncio.create_task(self._turn_timeout())

    async def _turn_timeout(self):
        try:
            await asyncio.sleep(TURN_SECONDS)
            if self.phase == "playing" and self.current:
                await self._whisper(self.current["user"].id, "⏱️ Se agotó el tiempo; te plantas automáticamente.")
                await self._stand_current()
        except asyncio.CancelledError:
            pass

    async def _stand_current(self):
        self._cancel_task(self.task)
        self.task = None
        if not self.current:
            return
        player = self.current
        total = player["total"]
        if total > 21:
            await self._resolve_current(False)
            return
        bot_total = 0
        bot_dice = []
        while bot_total < 17 and bot_total <= 21:
            roll = random.randint(1, 6)
            bot_dice.append(roll)
            bot_total += roll
        await self._whisper(player["user"].id, f"🤖 El bot sacó {bot_dice} (total {bot_total}). Tu total: {total}.")
        if bot_total > 21 or total > bot_total:
            await self._resolve_current(True)
        elif total == bot_total:
            await self._resolve_current(None)
        else:
            await self._resolve_current(False)

    async def _resolve_current(self, result: bool | None):
        if not self.current:
            return
        player = self.current
        user = player["user"]
        bet = player["bet"]
        account = self._account(user.id)
        if result is True:
            prize = bet * 2
            account["balance"] += prize
            account["winnings"] += bet
            text = f"🏆 @{user.username} gana {prize} G (incluye la apuesta)."
        elif result is None:
            account["balance"] += bet
            text = f"🤝 Empate con @{user.username}; se devuelve la apuesta de {bet} G al saldo."
        else:
            text = f"🤖 BotJuegos gana contra @{user.username}. Apuesta perdida: {bet} G."
        self._save()
        await self._chat(text)
        await self._whisper(user.id, f"Saldo: {account['balance']} G.")
        self.turn_index += 1
        await asyncio.sleep(1)
        await self._next_player()

    async def _send_amount(self, user_id: str, amount: int) -> bool:
        remaining = amount
        bars = []
        for value, bar in sorted(BET_BARS.items(), reverse=True):
            count, remaining = divmod(remaining, value)
            bars.extend([bar] * count)
        if remaining:
            return False
        try:
            for bar in bars:
                response = await self.bot.highrise.tip_user(user_id, bar)
                if getattr(response, "result", response) != "success":
                    return False
            return True
        except Exception as error:
            print(f"[DADOS21] Error enviando {amount} G a {user_id}: {error}")
            return False

    @staticmethod
    def _cancel_task(task: asyncio.Task | None):
        if task and not task.done() and task is not asyncio.current_task():
            task.cancel()
