from highrise import BaseBot, User


async def handle_help(bot: BaseBot, user: User, message: str) -> None:
    sections = await bot.get_command_help(user)
    content = "\n\n".join(section for section in sections if section)

    # Primero intentamos enviar la ayuda a la bandeja de entrada.
    # Si Highrise no permite iniciar la conversación desde este contexto,
    # usamos whisper como respaldo para que !help siempre funcione.
    try:
        conversations = await bot.highrise.get_conversations()
        conversation = next(
            (
                item
                for item in conversations.conversations
                if item.member_ids and user.id in item.member_ids
            ),
            None,
        )

        if conversation:
            result = await bot.highrise.send_message(conversation.id, content)
            if result is None:
                return
            print(f"[HELP] Error enviando ayuda a @{user.username}: {result}")
        else:
            result = await bot.highrise.send_message_bulk([user.id], content)
            if result is None:
                return
            print(f"[HELP] No se pudo iniciar la conversación para @{user.username}: {result}")
    except Exception as error:
        print(f"[HELP] Error enviando ayuda por bandeja a @{user.username}: {error}")

    # Respaldo: entregar la ayuda directamente por whisper, sin mostrar error.
    try:
        for section in sections:
            if section:
                result = await bot.highrise.send_whisper(user.id, section)
                if result is not None:
                    print(f"[HELP] Error enviando whisper a @{user.username}: {result}")
    except Exception as error:
        print(f"[HELP] Error en fallback whisper para @{user.username}: {error}")


COMMANDS = {"!help": handle_help}
