from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from typing import Awaitable, Callable

from highrise import Position, User


TRUTH_CATEGORIES = {
    "crush": [
        "¿Te gusta alguien de esta partida?",
        "¿Quién te parece más bonito/a de la partida?",
        "¿A quién de aquí besarías si tuvieras que elegir?",
        "¿Con quién tendrías una cita de esta sala?",
        "¿Quién te pone más nervioso/a cuando aparece?",
        "¿Has sentido atracción por alguien de esta sala?",
        "¿Quién te parece más coqueto/a?",
        "¿Quién tiene la mirada más atractiva?",
        "¿Quién crees que podría conquistarte fácilmente?",
        "¿Quién es tu crush secreto de esta sala?",
        "¿A quién le aceptarías una cita inmediatamente?",
        "¿Quién te parece más difícil de conquistar?",
        "¿Quién crees que está interesado/a en ti?",
        "¿Con quién pasarías una noche hablando sin aburrirte?",
        "¿Qué persona de esta partida elegirías para una cita romántica?",
        "¿Quién tiene la personalidad que más te atrae?",
        "¿A quién le darías una oportunidad si te invitara a salir?",
        "¿Quién de aquí podría hacerte cambiar de opinión sobre el amor?",
        "¿Qué usuario de esta partida te genera más curiosidad?",
        "¿Alguna vez has coqueteado con alguien de esta sala?",
        "¿Has tenido un crush que nadie de aquí conoce?",
        "¿Qué persona de esta partida te parece más interesante?",
        "¿Quién podría hacerte perder la vergüenza?",
        "¿Quién tiene más posibilidades de recibir un 'me gustas' tuyo?",
        "¿Si tuvieras que elegir pareja para una cita ahora, a quién escogerías?",
        "¿A quién de aquí le darías una oportunidad aunque no conocieras su nombre?",
        "¿Quién de esta sala te parece más irresistible?",
        "¿Quién podría convencerte de darle una segunda oportunidad?",
        "¿A quién de aquí le confiarías tu secreto más vergonzoso?",
        "¿Quién te parece más probable que tenga un crush contigo?",
        "¿Quién sería tu elección si tuvieras que compartir una cita esta noche?",
        "¿A quién de aquí te gustaría conocer mejor fuera del juego?",
        "¿Quién de la partida te parece más encantador/a?"
    ],
    "tension": [
        "¿A quién de la partida le darías un beso si no pudieras negarte?",
        "¿Quién te parece más atractivo/a cuando se pone serio/a?",
        "¿Con quién tendrías una cita a solas?",
        "¿A quién de aquí le mandarías un mensaje a medianoche?",
        "¿Quién podría hacerte ponerte celoso/a?",
        "¿Quién te parece más peligroso/a para tu corazón?",
        "¿A quién de aquí le aceptarías una invitación para salir?",
        "¿Quién te parece que tiene más química contigo?",
        "¿A quién mirarías primero si entrara a la sala ahora?",
        "¿Quién te haría dudar antes de decir que no?",
        "¿Quién de aquí te parece más difícil de ignorar?",
        "¿A quién le confesarías algo si supieras que no te juzgará?",
        "¿Quién podría hacerte cambiar de opinión sobre una relación?",
        "¿Con quién te atreverías a tener una cita improvisada?",
        "¿Quién te parece más probable que te robe un beso?",
    ],
    "personal": [
        "¿Cuál es tu mayor debilidad cuando alguien te gusta?",
        "¿Qué es lo primero que buscas en alguien que te atrae?",
        "¿Has mentido alguna vez para llamar la atención de alguien?",
        "¿Alguna vez te has puesto celoso/a por alguien que ni siquiera era tu pareja?",
        "¿Cuál ha sido tu peor primera impresión de alguien que luego te gustó?",
        "¿Has fingido que no te gustaba alguien cuando en realidad sí?",
        "¿Qué detalle pequeño puede hacer que alguien te guste mucho?",
        "¿Qué tipo de personalidad te atrae más?",
        "¿Has enviado alguna vez un mensaje coqueto y luego te arrepentiste?",
        "¿Has tenido un crush que nunca te atreviste a confesar?",
        "¿Qué es lo más atrevido que has hecho para llamar la atención de alguien?",
        "¿Alguna vez has sentido química con alguien inesperado?",
        "¿Qué te hace perder la vergüenza cuando alguien te gusta?",
        "¿Prefieres que te conquisten o conquistar?",
        "¿Qué gesto romántico te derrite más?",
    ],
    "confesiones": [
        "¿Cuál es el secreto más gracioso que puedes contar?",
        "¿Qué cosa te da vergüenza admitir que te gusta?",
        "¿Cuál es la mentira más pequeña que has dicho para impresionar a alguien?",
        "¿Alguna vez has revisado el perfil de alguien muchas veces porque te gustaba?",
        "¿Has borrado un mensaje porque te dio vergüenza enviarlo?",
        "¿Alguna vez has fingido estar ocupado/a para hacerte desear?",
        "¿Has tenido dos personas que te gustaban al mismo tiempo?",
        "¿Alguna vez has sentido celos y no lo has admitido?",
        "¿Has dado alguna indirecta que nadie entendió?",
        "¿Alguna vez has esperado que alguien te escribiera y fingiste que no te importaba?",
        "¿Has confundido amabilidad con coqueteo?",
        "¿Alguna vez has dado like a algo antiguo por accidente mientras mirabas el perfil de alguien?",
        "¿Has cambiado tu forma de vestir para llamar la atención de alguien?",
        "¿Alguna vez has practicado mentalmente qué decirle a alguien que te gusta?",
        "¿Has tenido un flechazo por alguien que casi nadie esperaba?",
    ],
    "divertidas": [
        "¿Cuál ha sido la situación más vergonzosa que has vivido?",
        "¿Cuál ha sido tu mayor metida de pata?",
        "¿Cuál ha sido la excusa más rara que has usado?",
        "¿Qué hábito extraño tienes?",
        "¿Cuál es la cosa más impulsiva que has hecho?",
        "¿Alguna vez has enviado un mensaje a la persona equivocada?",
        "¿Qué canción te sabes completa aunque te dé pena admitirlo?",
        "¿Cuál ha sido tu momento más incómodo en una sala?",
        "¿Qué cosa cambiarías de tu personalidad?",
        "¿Qué es lo más raro que has hecho por aburrimiento?",
        "¿Cuál es tu talento más inútil?",
        "¿Qué apodo absurdo te pondrías si nadie pudiera cambiarlo?",
        "¿Cuál es la cosa más infantil que todavía disfrutas?",
        "¿Qué moda jamás usarías aunque todos tus amigos la usaran?",
        "¿Cuál es tu peor excusa para no contestar un mensaje?",
        "¿Qué personaje de Highrise te representa más y por qué?",
    ],
    "atrevidas": [
        "¿Te atreverías a confesarle tu crush a alguien de esta partida?",
        "¿A quién elegirías para una cita de película?",
        "¿Quién de aquí crees que coquetea mejor?",
        "¿A quién de la partida le confiarías una cita secreta?",
        "¿Con quién aceptarías una cita sin preguntar a dónde van?",
        "¿Quién de aquí te haría romper tus propias reglas?",
        "¿A quién escogerías para una cita de tres horas sin usar el teléfono?",
        "¿Quién te parece más probable que te haga sonrojar?",
        "¿A quién de aquí le darías una oportunidad aunque normalmente no sea tu tipo?",
        "¿Quién podría convencerte de hacer algo que normalmente no harías?",
        "¿A quién invitarías a una cita si solo pudieras elegir a una persona?",
        "¿Qué persona de la partida te parece más peligrosa para enamorarte?",
        "¿A quién le dirías 'tenemos algo pendiente' si tuvieras que elegir?",
        "¿Quién de aquí te genera más tensión cuando está cerca?",
        "¿A quién elegirías para protagonizar una historia romántica contigo?",
    ],
}

DARE_CATEGORIES = {
    "romanticos": [
        "Besa virtualmente a {target}.",
        "Abraza virtualmente a {target}.",
        "Dile 'te amo' a {target} mirándolo/a de frente.",
        "Dile a {target}: 'Me gustas más de lo que debería'.",
        "Dile a {target}: 'Eres mi crush por los próximos 60 segundos'.",
        "Dile a {target}: 'Hoy te ves demasiado bien'.",
        "Dile a {target}: 'Creo que tenemos química'.",
        "Dile a {target}: 'Me debes una cita'.",
        "Hazle una declaración de amor exageradamente dramática a {target}.",
        "Dile a {target} tres cosas que te gustan de esa persona.",
        "Dedícale a {target} una frase romántica improvisada.",
        "Dile a {target}: 'No apartes la mirada' y mantén la mirada durante 10 segundos.",
        "Pregúntale a {target}: '¿Cuándo tenemos nuestra cita?'",
        "Dile a {target}: 'No sé si me gustas o me estás empezando a gustar'.",
        "Dile a {target}: 'Si esto fuera una cita, ya estarías en problemas'.",
        "Dile a {target} algo bonito que normalmente no te atreverías a decir.",
        "Haz una mini declaración de amor de 15 segundos para {target}.",
        "Dile a {target}: 'Hoy tienes permiso para hacerme sonrojar'.",
        "Dile a {target}: 'Eres fe@, pero de alguna manera me caes demasiado bien'.",
        "Dile a {target}: 'Eres oficialmente mi enemigo favorito'.",
        "Dile a {target}: 'No sé qué tienes, pero llamas demasiado mi atención'.",
        "Dile a {target}: 'Si me sigues mirando así, voy a pensar que te gusto'.",
        "Dile a {target}: 'Te odio... porque haces que este juego sea demasiado interesante'.",
        "Dile a {target}: 'Acepto una cita contigo, pero tú eliges el lugar'.",
    ],
    "tension": [
        "Elige a {target} y dile: 'Tenemos química, admítelo'.",
        "Acércate a {target} y dile algo coqueto.",
        "Ponte frente a {target} durante 20 segundos sin moverte.",
        "Dile a {target}: 'Creo que eres mi problema favorito'.",
        "Dile a {target}: 'Si me invitas a salir, probablemente diga que sí'.",
        "Hazle a {target} una pregunta coqueta que normalmente no harías.",
        "Dile a {target}: 'No sé si confiar en ti o enamorarme'.",
        "Mira a {target} durante 15 segundos y después dile algo bonito.",
        "Dile a {target}: 'Te elegiría para una cita ahora mismo'.",
        "Dile a {target}: 'Me estás poniendo nervioso/a' y mantén la posición durante 10 segundos.",
        "Haz una presentación de {target} como si fuera tu cita ideal.",
        "Dile a {target}: 'No me mires así que me lo voy a creer'.",
        "Invita públicamente a {target} a una cita ficticia.",
        "Dile a {target} una frase que podría hacer que alguien se ponga celoso.",
        "Elige a {target} y dile: 'Hoy eres oficialmente mi crush del juego'.",
    ],
    "confesiones": [
        "Dile a {target} algo que nunca le hayas dicho.",
        "Dile a {target} cuál fue tu primera impresión de esa persona.",
        "Confiesa a {target} qué detalle suyo te parece atractivo.",
        "Dile a {target} qué canción le dedicarías.",
        "Dile a {target} qué tipo de cita tendrías con esa persona.",
        "Dile a {target}: 'Te estaba observando desde antes de este reto'.",
        "Dile a {target} una cualidad que te gustaría encontrar en alguien.",
        "Dile a {target} qué apodo romántico le pondrías.",
        "Dile a {target} una frase que usarías para romper el hielo en una cita.",
        "Dile a {target} qué crees que es lo más atractivo de su personalidad.",
    ],
    "sociales": [
        "Elige a {target} y dile tres cosas positivas sobre esa persona.",
        "Abraza virtualmente a {target} y luego dile algo divertido.",
        "Hazle a {target} una pregunta que obligue a responder con sinceridad.",
        "Dile a {target}: 'Eres oficialmente mi persona favorita durante este turno'.",
        "Haz una presentación exagerada de {target} ante toda la sala.",
        "Elige a {target} y dile algo que pueda hacerle reír.",
        "Dile a {target}: 'Te concedo una cita imaginaria de 10 minutos'.",
        "Haz que {target} elija una palabra y crea una frase romántica con ella.",
        "Dile a {target} un cumplido que no tenga nada que ver con su apariencia.",
        "Elige a {target} y dedícale una frase de película.",
    ],
    "atrevidos": [
        "Elige a {target} y dile: 'Si esto fuera una cita, ¿qué pediríamos primero?'",
        "Dile a {target}: 'Te toca decidir si somos amigos o algo más por este turno'.",
        "Hazle a {target} una declaración de amor de 10 segundos.",
        "Dile a {target}: 'No sé si me caes demasiado bien o me gustas'.",
        "Elige a {target} y dile quién crees que tendría más celos de ustedes dos.",
        "Dile a {target}: 'Si tuvieras que invitarme a salir, ¿a dónde me llevarías?'",
        "Dile a {target} qué fue lo primero que llamó tu atención.",
        "Elige a {target} y dile: 'Tú y yo necesitamos una revancha en una cita'.",
        "Dile a {target}: 'Te reto a que me sorprendas con un cumplido'.",
        "Elige a {target} y dile algo que pueda aumentar la tensión sin insultar.",
        "Dile a {target}: 'Eres la persona más peligrosa de esta sala para mi corazón'.",
        "Dile a {target}: 'Si te dijera que me gustas, ¿qué harías?'",
        "Dile a {target}: 'Hoy te toca soportar mi coqueteo durante 20 segundos'.",
        "Dile a {target}: 'No eres mi tipo... pero estás haciendo que lo reconsidere'.",
        "Elige a {target} y dile una frase que parezca una confesión sin decir 'me gustas'.",
        "Dile a {target}: 'Creo que deberíamos tener una cita ficticia después de esta ronda'.",
    ],
    "divertidos": [
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
        "Durante 20 segundos, responde solo con emojis.",
        "Haz una entrada dramática al centro de la sala.",
        "Inventa un apodo divertido para ti mismo.",
        "Escribe una frase sin usar la letra A.",
        "Haz una declaración de amor a una silla, pared u objeto de la sala.",
        "Baila como si acabaras de ganar un premio.",
        "Haz durante 20 segundos el emote más absurdo que tengas disponible.",
        "Inventa un anuncio publicitario sobre ti mismo en 15 segundos.",
    ],
}


@dataclass
class GroupPlayer:
    user_id: str
    username: str


class TruthOrDareGame:
    CHOICE_SECONDS = 20
    ACTION_SECONDS = 60
    PUNISHMENT_SECONDS = 60
    PUNISHMENT_RADIUS = 1.5
    PUNISHMENT_EMOTE = "emote-cheer"

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
        self.punishments: dict[str, dict] = {}
        self.punishment_votes: dict[str, set[str]] = {}
        self.punishment_zone: Position | None = None
        self.punishment_radius = self.PUNISHMENT_RADIUS
        self._truth_history: set[str] = set()
        self._dare_history: set[str] = set()
        self._load_punishment_zone()

    def _load_punishment_zone(self) -> None:
        try:
            from services.storage import load_json
            data = load_json(self.bot.state_file)
            zone = data.get("punishment_zone")
            if zone:
                self.punishment_zone = Position(zone["x"], zone["y"], zone["z"], zone.get("facing", "FrontRight"))
                self.punishment_radius = float(zone.get("radius", self.PUNISHMENT_RADIUS))
        except Exception as error:
            print(f"[FUN GAME] Error cargando zona de castigo: {error}")

    def _save_punishment_zone(self) -> None:
        try:
            from services.storage import load_json, save_json
            data = load_json(self.bot.state_file)
            data["punishment_zone"] = {
                "x": self.punishment_zone.x,
                "y": self.punishment_zone.y,
                "z": self.punishment_zone.z,
                "facing": self.punishment_zone.facing,
                "radius": self.punishment_radius,
            }
            save_json(self.bot.state_file, data)
        except Exception as error:
            print(f"[FUN GAME] Error guardando zona de castigo: {error}")

    async def set_punishment_zone(self, user: User, radius: float | None = None) -> None:
        try:
            response = await self.bot.highrise.get_room_users()
            for room_user, position in response.content:
                if room_user.id == user.id and isinstance(position, Position):
                    self.punishment_zone = position
                    if radius is not None:
                        self.punishment_radius = max(0.5, min(radius, 10.0))
                    self._save_punishment_zone()
                    await self._chat(f"<#66FF99>📍 Zona de castigo guardada. <#FFFFFF>Radio: {self.punishment_radius:.1f}.")
                    return
            await self._chat(f"<#FF6666>⚠️ No pude obtener la posición de @{user.username}.")
        except Exception as error:
            print(f"[FUN GAME] Error configurando zona de castigo: {error}")
            await self._chat("<#FF6666>⚠️ No pude guardar la zona de castigo.")

    async def _get_user_position(self, user_id: str) -> Position | None:
        try:
            response = await self.bot.highrise.get_room_users()
            for room_user, position in response.content:
                if room_user.id == user_id and isinstance(position, Position):
                    return position
        except Exception as error:
            print(f"[FUN GAME] Error obteniendo posición: {error}")
        return None

    def _punishment_is_active_for(self, user_id: str) -> bool:
        return user_id in self.punishments

    async def _stop_punishment(self, user_id: str, restore: bool = True) -> None:
        punishment = self.punishments.pop(user_id, None)
        if not punishment:
            return
        current = asyncio.current_task()
        for key in ("dance_task", "task"):
            task = punishment.get(key)
            if task and task is not current:
                self._cancel_task(task)
        if restore and punishment.get("original_position"):
            try:
                await self.bot.highrise.teleport(user_id, punishment["original_position"])
            except Exception as error:
                print(f"[FUN GAME] Error devolviendo al jugador: {error}")

    async def _restore_all_punishments(self) -> None:
        for user_id in list(self.punishments):
            await self._stop_punishment(user_id, restore=True)

    async def _punishment_dance_loop(self, user_id: str) -> None:
        try:
            while self._punishment_is_active_for(user_id):
                await self.bot.highrise.send_emote(self.PUNISHMENT_EMOTE, user_id)
                await asyncio.sleep(5)
        except asyncio.CancelledError:
            return
        except Exception as error:
            print(f"[FUN GAME] Error en baile de castigo: {error}")

    async def vote_punishment(self, voter: User, command: str) -> bool:
        if self.state != "playing":
            await self._chat("<#FFCC66>⚠️ El castigo por votación solo está disponible durante una partida grupal.")
            return True

        parts = command.split()
        if len(parts) != 2 or not parts[1].startswith("@"):
            await self._chat("<#FFCC66>⚠️ Uso: !castigo @usuario")
            return True

        if not any(player.user_id == voter.id for player in self.players):
            await self._chat("<#FF6666>🔒 Solo los jugadores de la partida pueden votar un castigo.")
            return True

        target_name = parts[1][1:].casefold()
        target = next(
            (player for player in self.players if player.username.casefold() == target_name),
            None,
        )
        if target is None:
            await self._chat(f"<#FFCC66>⚠️ No encuentro a @{parts[1][1:]} en la partida.")
            return True

        if target.user_id == voter.id:
            await self._chat("<#FFCC66>⚠️ No puedes votar un castigo para ti mismo.")
            return True

        if self._punishment_is_active_for(target.user_id):
            await self._chat(f"<#FFCC66>⚠️ @{target.username} ya está cumpliendo un castigo.")
            return True

        voters = self.punishment_votes.setdefault(target.user_id, set())
        if voter.id in voters:
            await self._chat(f"<#FFCC66>⚠️ @{voter.username}, tu voto para @{target.username} ya está contado.")
            return True

        voters.add(voter.id)
        count = len(voters)

        if count < 2:
            await self._chat(
                f"<#FFCC66>⚠️ @{voter.username} votó castigo para @{target.username}. "
                "Falta 1 jugador."
            )
            return True

        self.punishment_votes.pop(target.user_id, None)
        await self._chat(
            f"<#FF6666>🔥 ¡Castigo aprobado! Dos jugadores votaron contra @{target.username}."
        )
        punished = await self._start_punishment(
            target.user_id,
            target.username,
            "Dos jugadores confirmaron que debe cumplir el castigo.",
        )

        if punished and self._current_player() and self._current_player().user_id == target.user_id:
            await self._advance_turn()

        return True

    async def _start_punishment(self, user_id: str, username: str, reason: str) -> bool:
        if self.punishment_zone is None:
            await self._chat("<#FF6666>⚠️ No hay zona de castigo configurada. Usa !setcastigo desde el tubo.")
            return False

        original = await self._get_user_position(user_id)
        if original is None:
            await self._chat(f"<#FF6666>⚠️ No pude guardar la posición de @{username}. No puedo aplicar el castigo.")
            return False

        await self._stop_punishment(user_id, restore=False)
        self.punishments[user_id] = {
            "username": username,
            "original_position": original,
            "task": None,
            "dance_task": None,
        }

        try:
            await self.bot.highrise.teleport(user_id, self.punishment_zone)
            await self._chat(f"<#FF6666>🔥 @{username} no cumplió. {reason}")
            await self._chat(
                f"<#FFCC66>💃 CASTIGO: al tubo durante "
                f"{self.PUNISHMENT_SECONDS} segundos. No puedes salir de la zona."
            )
            self.punishments[user_id]["dance_task"] = asyncio.create_task(
                self._punishment_dance_loop(user_id)
            )
            self.punishments[user_id]["task"] = asyncio.create_task(
                self._punishment_timeout(user_id, username)
            )
            return True
        except Exception as error:
            print(f"[FUN GAME] Error iniciando castigo: {error}")
            self.punishments.pop(user_id, None)
            return False

    async def _punishment_timeout(self, user_id: str, username: str) -> None:
        try:
            await asyncio.sleep(self.PUNISHMENT_SECONDS)
            if not self._punishment_is_active_for(user_id):
                return

            await self._stop_punishment(user_id, restore=True)
            await self._chat(
                f"<#66FF99>✅ @{username} terminó su castigo y vuelve a la partida."
            )
        except asyncio.CancelledError:
            return

    async def on_user_move(self, user: User, position) -> None:
        if not self._punishment_is_active_for(user.id) or self.punishment_zone is None:
            return
        if not isinstance(position, Position):
            await self.bot.highrise.teleport(user.id, self.punishment_zone)
            return

        distance = (
            (position.x - self.punishment_zone.x) ** 2
            + (position.z - self.punishment_zone.z) ** 2
        ) ** 0.5
        if distance > self.punishment_radius or abs(position.y - self.punishment_zone.y) > 1.5:
            try:
                await self.bot.highrise.teleport(user.id, self.punishment_zone)
                await self._chat(
                    f"<#FFCC66>🚫 @{user.username}, sigues castigado. "
                    "Debes permanecer en el tubo."
                )
            except Exception as error:
                print(f"[FUN GAME] Error reforzando zona de castigo: {error}")

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
        await self._send_prompt(user.username, mode, individual=True, user_id=user.id)
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
        self._cancel_task(self.individual_actions.pop(user.id, None))
        self.individual_actions[user.id] = asyncio.create_task(
            self._individual_action_timeout(user.id, user.username)
        )

    async def _individual_action_timeout(self, user_id: str, username: str) -> None:
        try:
            await asyncio.sleep(self.ACTION_SECONDS)
            task = self.individual_actions.pop(user_id, None)
            if task is not None:
                await self._chat(
                    f"<#FFCC66>⏰ @{username}, se agotó el tiempo. No cumpliste el reto."
                )
                await self._start_punishment(
                    user_id, username, "Se agotó el tiempo del reto."
                )
        except asyncio.CancelledError:
            return

    async def _pick_random_room_target(self, exclude_user_id: str) -> User | None:
        """Selecciona una persona aleatoria de la sala para los retos dirigidos."""
        try:
            response = await self.bot.highrise.get_room_users()
            candidates = [
                room_user
                for room_user, _ in response.content
                if room_user.id != exclude_user_id
                and room_user.id != getattr(self.bot, "bot_id", None)
            ]
            if not candidates:
                return None
            return random.choice(candidates)
        except Exception as error:
            print(f"[FUN GAME] Error seleccionando objetivo aleatorio: {error}")
            return None

    def _choose_prompt(self, categories: dict[str, list[str]], mode: str) -> str:
        """Elige una pregunta/reto evitando repetir inmediatamente el mismo texto."""
        history_name = "_truth_history" if mode == "truth" else "_dare_history"
        history = getattr(self, history_name, set())

        available = [
            (category, prompt)
            for category, prompts in categories.items()
            for prompt in prompts
            if prompt not in history
        ]

        if not available:
            history.clear()
            available = [
                (category, prompt)
                for category, prompts in categories.items()
                for prompt in prompts
            ]

        category, prompt = random.choice(available)
        history.add(prompt)
        return prompt

    async def _send_prompt(self, username: str, mode: str, individual: bool = False, user_id: str | None = None) -> None:
        if not hasattr(self, "_truth_history"):
            self._truth_history: set[str] = set()
        if not hasattr(self, "_dare_history"):
            self._dare_history: set[str] = set()

        if mode == "truth":
            prompt = self._choose_prompt(TRUTH_CATEGORIES, "truth")
            await self._chat(
                f"<#66FF99>🟢 VERDAD para @{username}: "
                f"<#FFFFFF>{prompt}"
            )
        else:
            prompt = self._choose_prompt(DARE_CATEGORIES, "dare")
            if "{target}" in prompt:
                target = await self._pick_random_room_target(user_id or "")
                if target is not None:
                    prompt = prompt.replace("{target}", f"@{target.username}")
                else:
                    prompt = random.choice(DARE_CATEGORIES["divertidos"])
            await self._chat(
                f"<#FF6666>🔴 RETO para @{username}: "
                f"<#FFFFFF>{prompt}"
            )

        if individual:
            await self._chat(
                f"<#FFCC66>Cuando termines, @{username}, escribe !listo. "
                f"Tienes {self.ACTION_SECONDS} segundos."
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

        await self._chat(
            "<#66CCFF>🎭 VERDAD O RETO — COMANDOS\\n"
            "<#FFFFFF>!verdad - Elegir Verdad\\n"
            "<#FFFFFF>!reto - Elegir Reto\\n"
            "<#FFFFFF>!listo - Terminar tu turno\\n"
            "<#FFFFFF>!salirvd - Salir de la partida\\n"
            "<#FFFFFF>!castigo @usuario - Votar para aplicar un castigo\\n"
            "<#66FF99>🎮 ¡Comienza la partida!"
        )

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

        await self._send_prompt(user.username, mode, user_id=user.id)
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
                        "No cumpliste el reto."
                    )
                    await self._start_punishment(
                        user_id, username, "Se agotó el tiempo del reto."
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
        await self._restore_all_punishments()
        self.punishment_votes.clear()

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
        if self._punishment_is_active_for(user_id):
            await self._stop_punishment(user_id, restore=False)

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
        if command.startswith("!setcastigo"):
            if user.id != self.bot.owner_id and not await self.is_mod(user.id):
                await self._chat(f"<#FF6666>🔒 @{user.username}, solo el dueño o moderadores pueden configurar el tubo.")
                return True
            parts = command.split()
            radius = None
            if len(parts) > 1:
                try:
                    radius = float(parts[1])
                except ValueError:
                    await self._chat("<#FFCC66>⚠️ Uso: !setcastigo o !setcastigo <radio>")
                    return True
            await self.set_punishment_zone(user, radius)
            return True

        if command.startswith("!castigo"):
            return await self.vote_punishment(user, command)

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
