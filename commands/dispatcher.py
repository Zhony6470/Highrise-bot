from __future__ import annotations
import importlib,pkgutil
from collections.abc import Awaitable,Callable
CommandHandler=Callable[...,Awaitable[str|list[str]|None]]
class CommandDispatcher:
    def __init__(self): self.handlers={}; self._load_commands()
    def _load_commands(self):
        package=importlib.import_module("commands")
        for info in pkgutil.iter_modules(package.__path__):
            if info.name.startswith("_") or info.name=="dispatcher": continue
            module=importlib.import_module(f"commands.{info.name}")
            commands=getattr(module,"COMMANDS",{})
            if not isinstance(commands,dict): continue
            for command,handler in commands.items():
                if isinstance(command,str) and callable(handler): self.handlers[command.strip().lower()]=handler
    def get(self,command): return self.handlers.get(command.strip().lower())
    async def handle(self,bot,user,message):
        parts=message.strip().split(maxsplit=1)
        if not parts:return None
        handler=self.get(parts[0])
        return await handler(bot,user,message.strip()) if handler else None
