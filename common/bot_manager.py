from __future__ import annotations

import os


def normalize_bot_reference(value: str | None) -> str:
    if value is None:
        return ""
    return value.strip().strip("@").lower()


def parse_target_username(message: str) -> str | None:
    parts = message.strip().split()
    if len(parts) < 2:
        return None
    target = parts[1].strip()
    if not target.startswith("@"):
        return None
    normalized = normalize_bot_reference(target)
    return normalized or None


async def should_handle_for_bot(bot, message: str) -> bool:
    target_name = parse_target_username(message)
    if target_name is None:
        return False

    bot_name = normalize_bot_reference(getattr(bot, "bot_username", None) or os.getenv("BOT_USERNAME"))
    if not bot_name:
        return False

    return target_name == bot_name
