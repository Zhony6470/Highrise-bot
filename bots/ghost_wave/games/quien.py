import random

PROMPTS = [
    "¿Quién es más probable que se pierda incluso usando un mapa?",
    "¿Quién es más probable que se ría en el momento menos oportuno?",
    "¿Quién es más probable que sobreviva a una invasión de fantasmas?",
    "¿Quién es más probable que se quede dormido en una fiesta?",
    "¿Quién es más probable que se convierta en famoso por accidente?",
    "¿Quién es más probable que hable con una mascota como si entendiera todo?",
    "¿Quién es más probable que olvide por qué entró a una habitación?",
    "¿Quién es más probable que organice una aventura a última hora?",
]

class QuienGame:
    async def handle(self, message):
        text = message.strip().casefold()
        if text not in ("!quien", "!quien ayuda"):
            return None
        if text == "!quien ayuda":
            return "🎭 !quien — recibe una pregunta divertida para responder en privado. No etiqueta ni avisa a otros jugadores."
        return "🎭 ¿QUIÉN ES MÁS PROBABLE QUE...?\n" + random.choice(PROMPTS) + "\n\n💬 Piensa en tu respuesta o escríbela aquí; no se publicará en la sala."
