import random

RIDDLES = [
    ("Tengo agujas y no sé coser; tengo números y no sé leer. ¿Qué soy?", "reloj"),
    ("Cuanto más quitas, más grande se vuelve. ¿Qué es?", "agujero"),
    ("Tiene dientes y no come. ¿Qué es?", "peine"),
    ("Sube y baja, pero siempre está en el mismo sitio. ¿Qué es?", "escalera"),
    ("Si me nombras, desaparezco. ¿Qué soy?", "silencio"),
    ("Tiene ciudades pero no casas, ríos pero no agua. ¿Qué es?", "mapa"),
]

class AdivinaGame:
    def __init__(self):
        self.sessions = {}
        self.points = {}

    async def handle(self, user_id, message):
        text = message.strip().casefold()
        if text == "!adivina":
            riddle = random.choice(RIDDLES)
            self.sessions[user_id] = riddle
            return "🧩 ADIVINANZA PERSONAL\n" + riddle[0] + "\n\nEscribe tu respuesta aquí. Usa !adivina otra para cambiar de pregunta."
        if text == "!adivina otra":
            riddle = random.choice(RIDDLES)
            self.sessions[user_id] = riddle
            return "🧩 Nueva adivinanza:\n" + riddle[0]
        if text == "!puntos":
            return f"⭐ Tus puntos de adivinanzas: {self.points.get(user_id, 0)}"
        if user_id not in self.sessions:
            if text == "!adivina ayuda":
                return "🧩 !adivina — empieza una adivinanza individual. Responde en tu conversación privada. !adivina otra cambia la pregunta; !puntos muestra tu puntaje."
            return None
        if text in ("!adivina ayuda", "!puntos"):
            return f"⭐ Tus puntos: {self.points.get(user_id, 0)}. Responde la adivinanza o escribe !adivina otra."
        answer = text.strip(" .!?¿¡")
        if answer == self.sessions[user_id][1]:
            self.points[user_id] = self.points.get(user_id, 0) + 1
            self.sessions.pop(user_id, None)
            return f"🎉 ¡Correcto! Ganaste 1 punto. Total: {self.points[user_id]}. Escribe !adivina para otra."
        return "❌ No es esa. ¡Inténtalo de nuevo! Si te rindes, escribe !adivina otra."
