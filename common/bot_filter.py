from __future__ import annotations

import os


def _csv_env(name: str) -> set[str]:
    return {
        value.strip().casefold()
        for value in os.getenv(name, "").split(",")
        if value.strip()
    }


def is_known_bot(bot, user_id: str | None, username: str | None = None) -> bool:
    """Identify this project's bots and any bot IDs/usernames explicitly configured.

    Highrise's room-user model does not expose an is_bot flag, so arbitrary
    third-party bots cannot be detected reliably unless their IDs/usernames
    are configured in the environment.
    """
    if user_id and user_id == getattr(bot, "bot_id", None):
        return True

    known_ids = _csv_env("HIGHRISE_BOT_IDS")
    known_ids.update(
        value.strip()
        for value in (
            os.getenv("BOT1_USER_ID", ""),
            os.getenv("DJ_BOT_USER_ID", ""),
            os.getenv("BOT3_USER_ID", ""),
        )
        if value.strip()
    )
    # Known room bot: the games bot currently connects as @Dj.Zz.
    known_ids.add("6590cb69feb3f3d0238ee347")
    if user_id and user_id in known_ids:
        return True

    known_names = {
        "zeta_bot",
        "dj.z",
        "dj.zz",
        "botjuegos",
    }
    known_names.update(_csv_env("HIGHRISE_BOT_USERNAMES"))
    for env_name in (
        "BOT_USERNAME",
        "BOT1_USERNAME",
        "DJ_BOT_USERNAME",
        "BOT3_USERNAME",
    ):
        value = os.getenv(env_name, "").strip()
        if value:
            known_names.add(value.casefold().lstrip("@"))

    own_username = getattr(bot, "bot_username", "")
    if own_username:
        known_names.add(str(own_username).casefold().lstrip("@"))

    normalized_username = str(username or "").casefold().lstrip("@")
    return bool(normalized_username and normalized_username in known_names)
