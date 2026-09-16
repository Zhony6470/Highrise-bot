import asyncio
from types import SimpleNamespace

from highrise import User

from commands.userinfo import handle_userinfo


class FakeWebAPI:
    async def get_users(self, username):
        return SimpleNamespace(users=[SimpleNamespace(id="user-456", username=username)])

    async def get_user(self, user_id):
        return SimpleNamespace(
            user=SimpleNamespace(
                username="FueraDeSala",
                num_followers=10,
                num_friends=5,
                num_following=3,
                joined_at=SimpleNamespace(strftime=lambda format_string: "16/09/2026 12:00:00"),
            )
        )


class FakeBot:
    webapi = FakeWebAPI()


def test_userinfo_finds_user_outside_room():
    response = asyncio.run(
        handle_userinfo(FakeBot(), User("requester", "Solicitante"), "!userinfo @FueraDeSala")
    )

    assert "Perfil de FueraDeSala" in response