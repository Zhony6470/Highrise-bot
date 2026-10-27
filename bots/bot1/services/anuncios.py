import asyncio


ROOM_ANNOUNCEMENTS = [
    "<#66CCFF>💎 ¿Quieres disfrutar de todos los comandos de Zeta? ¡Consigue tu VIP y desbloquea la diversión!",
    "<#CC99FF>💘 ¿Quieres saber qué tanta compatibilidad tienes con esa persona especial? ¡Usa !love @usuario!",
    "<#FF9966>🥊 ¿Tienes una rivalidad amistosa? ¡Usa !fight @usuario y que comience el duelo!",
    "<#FF66CC>💋 ¡Un beso para esa persona especial! Prueba el comando !kiss @usuario.",
    "<#FF6699>💖 ¡Comparte cariño en la sala! Usa !heart @usuario para enviar un corazón.",
    "<#FFCC66>✨ Los comandos de Zeta hacen cada visita diferente. Escribe !help y descubre todo lo que puedes hacer.",
    "<#6699FF>🌆 ¿Recuerdas Club Rise? Aquella sala tenía algo especial: las risas, la música y tantas noches inolvidables.",
    "<#CC99FF>🕰️ Hay salas que no se olvidan. Club Rise fue más que un lugar: fueron momentos y personas que dejaron huella. 💜",
    "<#66CCFF>🎶 A veces una canción basta para volver a recordar las noches que vivimos en Club Rise. ¡Qué buenos tiempos!",
    "<#FF9966>💫 Los mejores recuerdos de Club Rise siguen vivos en quienes compartieron allí tantas aventuras. ¿Quién más lo recuerda?",
    "<#66FF99>🫶 Gracias por formar parte de esta comunidad. Cada persona aporta algo único a la historia de la sala.",
    "<#99CCFF>🌙 Recordar Club Rise es recordar amistades, música y momentos que nos sacaban una sonrisa. ¡Qué nostalgia!",
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
