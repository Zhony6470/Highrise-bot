from highrise import BaseBot, User


async def handle_help(bot: BaseBot, user: User, message: str) -> None:
    sections = await bot.get_command_help(user)
    content = "\n\n".join(section for section in sections if section)

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
        else:
            result = await bot.highrise.send_message_bulk([user.id], content)

        if result is None:
            return None

        print(f"[HELP] Error enviando ayuda a @{user.username}: {result}")
    except Exception as error:
        print(f"[HELP] Error enviando ayuda a @{user.username}: {error}")

    await bot.highrise.chat(
        f"<#FFCC66>📨 No pude enviar la ayuda a tu bandeja. "
        "Escríbeme primero por mensaje privado y vuelve a usar !help."
    )


COMMANDS = {"!help": handle_help}
