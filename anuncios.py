import asyncio


ROOM_ANNOUNCEMENTS = [
    "<#66FF99>✨ ¡Bienvenidos a la sala! Disfruten, compartan y pásenla genial. ✨",
    "<#66CCFF>💫 ¿Quieres descubrir los comandos? Escribe !help y te los envío por privado.",
    "<#FFCC66>🎭 Dale vida a tu avatar con un emote y disfruta el ambiente. 🎶",
    "<#CC99FF>💛 Las buenas vibras hacen la sala más divertida. ¡Gracias por estar aquí!",
    "<#FF6699>🎉 Atención, habitantes de la sala: queda oficialmente inaugurado el modo fiesta. 💃",
    "<#66FFFF>🧊 Hace frío afuera, pero aquí sobran las buenas vibras. ¡Entren en calor bailando! 🔥",
    "<#FFFF66>😂 Si tu avatar empieza a bailar solo, no te preocupes... probablemente tiene mejor ritmo que nosotros.",
    "<#FF9966>🍕 Se busca: una persona que diga ‘solo cinco minutos más’ y se quede toda la noche. 👀",
    "<#99FF66>🌈 Regla no oficial de la sala: quien entre con mal humor debe pagar una ronda de risas. 😄",
    "<#CC66FF>🪩 ¡Pista imaginaria abierta! Trae tu mejor pose, tu peor chiste y cero vergüenza. ✨",
    "<#FFCCFF>🐸 Un aplauso para todos los que llegaron a la sala sin saber qué hacer y terminaron haciendo amigos. 👏",
    "<#66FFCC>🎤 Micrófono invisible disponible: canta en tu mente y presume que todos te están aplaudiendo. 😎",
    "<#FF6666>🚨 Alerta de diversión: se recomienda sonreír, bailar y culpar al lag si sale mal. 📶",
    "<#6699FF>🧭 Si te pierdes, sigue las risas. Si no escuchas risas, empieza tú una. 😜",
    "<#FF66CC>💌 Mensaje del día: tu avatar se ve genial, pero con un emote se ve legendario. 🎭",
    "<#99CCFF>🌙 La sala está oficialmente en modo chill. Pónganse cómodos y dejen que fluya el caos. ✨",
    "<#CCFF99>🏆 Premio simbólico para quien consiga hacer reír a toda la sala. El trofeo es imaginario, pero el honor es real. 😄",
]


async def announcement_loop(bot) -> None:
    announcement_index = 0
    try:
        await asyncio.sleep(300)
        while True:
            await bot.highrise.chat(ROOM_ANNOUNCEMENTS[announcement_index])
            announcement_index = (announcement_index + 1) % len(ROOM_ANNOUNCEMENTS)
            await asyncio.sleep(300)
    except asyncio.CancelledError:
        pass
    except Exception as error:
        print(f"Error en los anuncios periódicos: {error}")
