import importlib
import pkgutil
from collections.abc import Awaitable, Callable


CommandHandler = Callable[..., Awaitable[str | list[str] | None]]


class CommandDispatcher:
    def __init__(self):
        self.handlers: dict[str, CommandHandler] = {}
        self._load_commands()

    def _load_commands(self) -> None:
        package = importlib.import_module("commands")
        for module_info in pkgutil.iter_modules(package.__path__):
            if module_info.name.startswith("_") or module_info.name == "dispatcher":
                continue

            module = importlib.import_module(f"commands.{module_info.name}")
            for command, handler in getattr(module, "COMMANDS", {}).items():
                self.handlers[command.lower()] = handler

    async def handle(self, bot, user, message: str) -> str | list[str] | None:
        command_name = message.strip().split(maxsplit=1)[0].lower()
        handler = self.handlers.get(command_name)
        if handler is None:
            return None
        return await handler(bot, user, message.strip())
