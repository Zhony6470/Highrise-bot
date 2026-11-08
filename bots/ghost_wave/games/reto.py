import random

CHALLENGES = [
    "Escribe tres cosas que te hacen reír 😄",
    "Di un cumplido sincero a alguien de tu elección (sin etiquetar a nadie aquí). 💛",
    "Inventa un nombre gracioso para un fantasma 👻",
    "Describe tu día usando solo tres emojis. 🎭",
    "Cuenta una habilidad curiosa que tengas. ✨",
    "Escribe una frase dramática como protagonista de una película. 🎬",
    "Inventa un grito de guerra para tu equipo fantasma. 📣",
    "Di cuál sería tu superpoder más inútil. 🦸",
]

class RetoGame:
    async def handle(self, message):
        if message.strip().casefold() not in ("!reto", "!reto ayuda"):
            return None
        if message.strip().casefold() == "!reto ayuda":
            return "🎲 !reto — recibe un reto aleatorio solo en tu conversación privada con Ghost Wave."
        return "🎲 TU RETO PERSONAL\n" + random.choice(CHALLENGES) + "\n\n🔒 Este mensaje solo te llega a ti."
