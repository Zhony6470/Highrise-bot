from __future__ import annotations
import os

def normalize_bot_reference(value: str | None) -> str:
    return value.strip().lstrip("@").casefold() if value else ""

def parse_target_username(message: str) -> str | None:
    parts = message.strip().split()
    if len(parts) < 2 or not parts[1].startswith("@"):
        return None
    target = normalize_bot_reference(parts[1])
    return target or None

def get_bot_username(bot) -> str:
    return normalize_bot_reference(getattr(bot, "bot_username", None) or os.getenv("BOT_USERNAME"))

async def should_handle_for_bot(bot, message: str) -> bool:
    target = parse_target_username(message)
    return bool(target and target == get_bot_username(bot))
