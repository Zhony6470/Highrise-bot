import asyncio

from highrise import Position, User

from main import Bot


class FakeHighrise:
    def __init__(self):
        self.whispers = []
        self.chats = []

    async def send_whisper(self, user_id, message):
        self.whispers.append((user_id, message))

    async def chat(self, message):
        self.chats.append(message)


class FakeRoleManager:
    async def get_user_role(self, bot, user):
        return "vip"

    async def apply_saved_role(self, bot, user):
        pass


def test_on_user_join_sends_private_welcome():
    bot = Bot.__new__(Bot)
    bot.highrise = FakeHighrise()
    bot.role_manager = FakeRoleManager()
    bot.user_positions = {}
    user = User("user-123", "Ana")
    position = Position(1, 2, 3, "FrontRight")

    asyncio.run(bot.on_user_join(user, position))

    assert bot.highrise.whispers == [
        (
            "user-123",
            "\n".join([
                "<#66FFCC>✨ ¡Hola, Ana! ✨",
                "<#FFFFFF>━━━━━━━━━━━━━━━━━━",
                "<#FFCC66>🎭 Tu rol en la sala: <#FFFFFF>vip",
                "<#66FF99>🎉 ¡Bienvenido/a! Pasa, disfruta y comparte buenas vibras.",
                "<#CC99FF>💫 Escribe <#FFFFFF>!help <#CC99FF>para descubrir mis comandos.",
                "<#FFFFFF>━━━━━━━━━━━━━━━━━━",
            ]),
        )
    ]


def test_userinfo_is_sent_to_public_chat():
    bot = Bot.__new__(Bot)
    bot.highrise = FakeHighrise()
    bot.command_dispatcher = type("FakeDispatcher", (), {
        "handlers": {"!userinfo": object()},
        "handle": lambda self, bot, user, message: _resolved_response("Perfil público"),
    })()

    asyncio.run(bot.on_chat(User("user-123", "Ana"), "!userinfo"))

    assert bot.highrise.chats == ["Perfil público"]
    assert bot.highrise.whispers == []


async def _resolved_response(response):
    return response