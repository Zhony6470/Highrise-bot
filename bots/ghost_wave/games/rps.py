import asyncio

CHOICES = {"piedra", "papel", "tijera"}
WINS = {("piedra", "tijera"), ("papel", "piedra"), ("tijera", "papel")}

class RPSGame:
    """Piedra, papel o tijera por buzón, solo entre los dos participantes."""
    def __init__(self, bot):
        self.bot = bot
        self.matches = {}
        self.user_match = {}
        self.counter = 0
        self.timeout_tasks = {}

    async def handle(self, user_id, message):
        text = message.strip()
        parts = text.split()
        if not parts:
            return None
        cmd = parts[0].casefold()
        if cmd == "!rps":
            if len(parts) != 2 or not parts[1].startswith("@"):
                return "🎮 Uso: !rps @usuario. El reto y las jugadas se gestionan por privado con Ghost Wave."
            if user_id in self.user_match:
                return "⚠️ Ya tienes una partida activa."
            found = await self.bot.find_user(parts[1])
            if not found:
                return "🔎 No encuentro a ese usuario. Pídele que escriba primero 'hola' a Ghost Wave."
            target_id, target_name = found
            if target_id == user_id:
                return "😅 No puedes retarte a ti mismo."
            if not self.bot.store.d["conversations"].get(target_id):
                return "📩 Ese jugador debe escribir primero 'hola' a Ghost Wave para habilitar su conversación privada."
            if target_id in self.user_match:
                return "⚠️ Ese jugador ya tiene una partida activa."
            username = self.bot.store.d["names"].get(user_id, "Jugador")
            self.counter += 1
            match_id = f"rps-{self.counter}"
            self.matches[match_id] = {"p1": user_id, "p2": target_id, "names": {user_id: username, target_id: target_name}, "state": "pending", "choices": {}, "wins": {user_id: 0, target_id: 0}, "round": 1}
            self.user_match[user_id] = match_id
            self.user_match[target_id] = match_id
            await self.bot.inbox(target_id, f"⚔️ @{username} te reta a Piedra, Papel o Tijera en Ghost Wave. Para jugar, responde exactamente: aceptar. Para rechazar: rechazar.")
            return f"✅ Reto enviado a @{target_name}. Solo ustedes dos recibirán mensajes de esta partida."

        match_id = self.user_match.get(user_id)
        if not match_id:
            return None
        # No interceptar los comandos normales de Ghost Wave mientras hay una partida.
        if cmd.startswith("!") and cmd not in ("!aceptar", "!rechazar", "!cancelar", "!piedra", "!papel", "!tijera"):
            return None
        match = self.matches.get(match_id)
        if not match:
            self.user_match.pop(user_id, None)
            return None
        if match["state"] == "pending" and user_id == match["p2"] and cmd in ("aceptar", "!aceptar"):
            match["state"] = "playing"
            instructions = "🎮 RPS iniciado. Responde solo a Ghost Wave con: piedra, papel o tijera. Tienen 40 segundos por ronda. Gana quien consiga 2 rondas."
            await self.bot.inbox(match["p1"], instructions)
            self._start_timeout(match_id)
            return instructions
        if match["state"] == "pending" and user_id == match["p2"] and cmd in ("rechazar", "!rechazar"):
            await self.bot.inbox(match["p1"], f"🙅 @{match['names'][user_id]} rechazó tu reto de RPS.")
            self._cleanup(match_id)
            return "Has rechazado el reto."
        if cmd in ("rechazar", "!rechazar", "cancelar", "!cancelar"):
            other = match["p2"] if user_id == match["p1"] else match["p1"]
            await self.bot.inbox(other, "⚠️ La partida de RPS fue cancelada por el otro jugador.")
            self._cleanup(match_id)
            return "Partida cancelada."
        if match["state"] != "playing" or cmd not in CHOICES:
            if match["state"] == "pending":
                return "⏳ Tu reto aún está pendiente. El rival debe responder 'aceptar' o 'rechazar'."
            return "🎮 Para jugar RPS, responde: piedra, papel o tijera. Puedes escribir cancelar para salir."
        if user_id in match["choices"]:
            return "🔒 Ya registré tu jugada de esta ronda; espera al rival."
        match["choices"][user_id] = cmd
        other = match["p2"] if user_id == match["p1"] else match["p1"]
        await self.bot.inbox(other, "🎮 Tu rival ya eligió. Envía piedra, papel o tijera.")
        if len(match["choices"]) < 2:
            return "🔐 Jugada guardada en privado. Esperando al rival."
        self._cancel_timeout(match_id)
        p1, p2 = match["p1"], match["p2"]
        a, b = match["choices"][p1], match["choices"][p2]
        if a != b:
            winner = p1 if (a, b) in WINS else p2
            match["wins"][winner] += 1
        result = "🤝 Empate en esta ronda." if a == b else f"🏆 @{match['names'][winner]} gana la ronda."
        score = f"📊 Marcador: @{match['names'][p1]} {match['wins'][p1]} - {match['wins'][p2]} @{match['names'][p2]}"
        details = f"⚔️ Ronda {match['round']}\n@{match['names'][p1]}: {a}\n@{match['names'][p2]}: {b}\n{result}\n{score}"
        await self.bot.inbox(p1, details)
        await self.bot.inbox(p2, details)
        if max(match["wins"].values()) >= 2:
            winner_id = p1 if match["wins"][p1] > match["wins"][p2] else p2
            final = f"🏆 ¡Partida terminada! Ganó @{match['names'][winner_id]}."
            await self.bot.inbox(p1, final)
            await self.bot.inbox(p2, final)
            self._cleanup(match_id)
        else:
            match["round"] += 1
            match["choices"] = {}
            await self.bot.inbox(p1, "🎮 Nueva ronda: responde piedra, papel o tijera. Tienes 40 segundos.")
            await self.bot.inbox(p2, "🎮 Nueva ronda: responde piedra, papel o tijera. Tienes 40 segundos.")
            self._start_timeout(match_id)
        return "✅ Tu jugada fue procesada. Revisa tu conversación privada con Ghost Wave para ver el resultado."

    def _start_timeout(self, match_id):
        self._cancel_timeout(match_id)
        self.timeout_tasks[match_id] = asyncio.create_task(self._timeout(match_id))

    def _cancel_timeout(self, match_id):
        task = self.timeout_tasks.pop(match_id, None)
        if task and not task.done():
            task.cancel()

    async def _timeout(self, match_id):
        try:
            await asyncio.sleep(40)
            match = self.matches.get(match_id)
            if not match or match["state"] != "playing":
                return
            p1, p2 = match["p1"], match["p2"]
            choices = match["choices"]
            if not choices:
                note = "⏳ RPS cancelado: ninguno eligió en 40 segundos."
                await self.bot.inbox(p1, note)
                await self.bot.inbox(p2, note)
                self._cleanup(match_id)
                return
            if len(choices) == 1:
                winner = next(iter(choices))
                match["wins"][winner] += 1
                winner_name = match["names"][winner]
                p1_name = match["names"][p1]
                p2_name = match["names"][p2]
                note = f"⏳ Se acabó el tiempo. @{winner_name} gana la ronda porque el rival no eligió."
                score = f"📊 Marcador: @{p1_name} {match['wins'][p1]} - {match['wins'][p2]} @{p2_name}"
                for uid in (p1, p2):
                    await self.bot.inbox(uid, note + "\n" + score)
                if match["wins"][winner] >= 2:
                    final = f"🏆 ¡Partida terminada! Ganó @{winner_name}."
                    await self.bot.inbox(p1, final)
                    await self.bot.inbox(p2, final)
                    self._cleanup(match_id)
                    return
                match["round"] += 1
                match["choices"] = {}
                await self.bot.inbox(p1, "🎮 Nueva ronda: responde piedra, papel o tijera. Tienes 40 segundos.")
                await self.bot.inbox(p2, "🎮 Nueva ronda: responde piedra, papel o tijera. Tienes 40 segundos.")
                self._start_timeout(match_id)
        except asyncio.CancelledError:
            return
        except Exception as error:
            print(f"[GHOST RPS] timeout: {error}")
        finally:
            if self.timeout_tasks.get(match_id) is asyncio.current_task():
                self.timeout_tasks.pop(match_id, None)

    def _cleanup(self, match_id):
        self._cancel_timeout(match_id)
        match = self.matches.pop(match_id, None)
        if match:
            self.user_match.pop(match["p1"], None)
            self.user_match.pop(match["p2"], None)
