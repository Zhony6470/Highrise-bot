from __future__ import annotations

from typing import Any

from highrise import Item


class AvatarManager:
    """Servicios comunes para ropa, outfit y avatar del bot."""

    def __init__(self, bot):
        self.bot = bot

    async def get_my_outfit(self):
        return await self.bot.highrise.get_my_outfit()

    async def set_outfit(self, outfit):
        result = await self.bot.highrise.set_outfit(outfit)
        if result is None:
            self._save_outfit(outfit)
        return result

    @staticmethod
    def _serialize_outfit(outfit) -> list[dict[str, Any]]:
        return [
            {
                "id": item.id,
                "type": getattr(item, "type", "clothing"),
                "amount": getattr(item, "amount", 1),
                "account_bound": getattr(item, "account_bound", False),
                "active_palette": getattr(item, "active_palette", 0),
            }
            for item in outfit
            if getattr(item, "id", None)
        ]

    def _save_outfit(self, outfit) -> None:
        state_manager = getattr(self.bot, "bot_state_manager", None)
        if state_manager is None:
            return
        state = state_manager.get_state()
        state.outfit = self._serialize_outfit(outfit)
        state_manager.save_state(state)

    async def restore_saved_outfit(self) -> bool:
        state_manager = getattr(self.bot, "bot_state_manager", None)
        if state_manager is None:
            return False
        saved_outfit = state_manager.get_state().outfit
        if not saved_outfit:
            return False
        outfit = [
            Item(**item)
            for item in saved_outfit
            if isinstance(item, dict) and item.get("id")
        ]
        if not outfit:
            return False
        return await self.set_outfit(outfit) is None

    async def change_color(self, category: str, palette: int) -> str:
        try:
            outfit = (await self.bot.highrise.get_my_outfit()).outfit
            found_item = False
            for outfit_item in outfit:
                item_category = outfit_item.id.split("-", 1)[0].lower()
                if item_category == category:
                    outfit_item.active_palette = palette
                    found_item = True
            if not found_item:
                return f"<#FFCC66>👕 El bot no usa ningún artículo de la categoría '{category}'."
            result = await self.set_outfit(outfit)
            if result is not None:
                return "<#FF6666>⚠️ No se pudo cambiar el color del vestuario."
            return f"<#66FF99>✨ Color de '{category}' actualizado correctamente."
        except Exception:
            return "<#FF6666>⚠️ No se pudo cambiar el color del vestuario."

    async def equip_item(self, item_id: str, category: str, item_name: str = "") -> str:
        try:
            outfit = (await self.bot.highrise.get_my_outfit()).outfit
            filtered = [item for item in outfit if item.id.split("-", 1)[0].lower() != category]
            filtered.append(type("TmpItem", (), {"id": item_id, "type": "clothing", "amount": 1, "account_bound": False, "active_palette": 0})())
            result = await self.set_outfit(filtered)
            if result is not None:
                return "<#FF6666>⚠️ No se pudo equipar la prenda."
            return f"<#66FF99>✨ Prenda equipada: {item_name or item_id}."
        except Exception:
            return "<#FF6666>⚠️ No se pudo equipar la prenda."

    async def remove_category(self, category: str) -> str:
        try:
            outfit = (await self.bot.highrise.get_my_outfit()).outfit
            filtered = [item for item in outfit if item.id.split("-", 1)[0].lower() != category]
            if len(filtered) == len(outfit):
                return f"<#FFCC66>👕 El bot no usa ninguna prenda de la categoría '{category}'."
            result = await self.set_outfit(filtered)
            if result is not None:
                return "<#FF6666>⚠️ No se pudo modificar el vestuario."
            return f"<#66FF99>✨ Categoría '{category}' eliminada correctamente."
        except Exception:
            return "<#FF6666>⚠️ No se pudo modificar el vestuario."

    async def get_outfit_summary(self) -> str:
        try:
            outfit_response = await self.bot.highrise.get_my_outfit()
            outfit_items = outfit_response.outfit
            if not outfit_items:
                return "<#FFCC66>🧺 El bot no tiene prendas equipadas."
            return "<#66CCFF>👔 Vestuario actual:\n" + "\n".join(f"<#FFFFFF>• {item.id}" for item in outfit_items)
        except Exception:
            return "<#FF6666>⚠️ No se pudo obtener el vestuario del bot."
