from highrise import BaseBot, Item, User
from highrise.models_webapi import Rarity


async def handle_equip(bot: BaseBot, user: User, message: str) -> str:
    if user.id != bot.owner_id and not await bot.is_mod(user.id):
        return "<#FF6666>👗 Solo el dueño o los moderadores pueden equipar prendas."

    parts = message.split()
    if len(parts) < 2:
        return "<#FFCC66>👗 Uso: !equip <nombre de la prenda> [numero]"

    result_index = 0
    item_name_parts = parts[1:]
    if item_name_parts[-1].isdigit():
        result_index = int(item_name_parts.pop()) - 1
        if result_index < 0:
            return "<#FFCC66>🔢 El número de resultado debe ser mayor que 0."

    item_name = " ".join(item_name_parts)
    if not item_name:
        return "<#FFCC66>👚 Debes indicar el nombre de la prenda."

    try:
        response = await bot.webapi.get_items(item_name=item_name)
        items = response.items
    except Exception as error:
        print(f"Error buscando el artículo: {error}")
        return "<#FF6666>⚠️ No se pudo buscar la prenda."

    if not items:
        return f"<#FFCC66>🔎 No se encontró la prenda '{item_name}'."
    if result_index >= len(items):
        return f"<#FFCC66>🔢 Resultado inválido. Hay {len(items)} resultados disponibles."

    selected_item = items[result_index]
    item_id = selected_item.item_id
    category = str(selected_item.category.value if selected_item.category else "").lower()

    try:
        inventory = (await bot.highrise.get_inventory()).items
        owns_item = any(inventory_item.id == item_id for inventory_item in inventory)
    except Exception as error:
        print(f"Error consultando el inventario: {error}")
        return "<#FF6666>⚠️ No se pudo consultar el inventario del bot."

    if not owns_item:
        if selected_item.rarity == Rarity.NONE:
            pass
        elif not selected_item.is_purchasable:
            return f"<#FFCC66>🛍️ La prenda '{selected_item.item_name}' no se puede comprar."
        else:
            try:
                purchase_result = await bot.highrise.buy_item(item_id)
            except Exception as error:
                print(f"Error comprando la prenda: {error}")
                return "<#FF6666>⚠️ No se pudo comprar la prenda."
            if purchase_result != "success":
                return f"<#FF6666>⚠️ No se pudo comprar la prenda '{selected_item.item_name}'."

    try:
        outfit = (await bot.highrise.get_my_outfit()).outfit
        outfit = [
            outfit_item
            for outfit_item in outfit
            if outfit_item.id.split("-", 1)[0].lower() != category
        ]
        outfit.append(
            Item(
                type="clothing",
                amount=1,
                id=item_id,
                account_bound=False,
                active_palette=0,
            )
        )

        if category == "hair_front" and selected_item.link_ids:
            outfit.append(
                Item(
                    type="clothing",
                    amount=1,
                    id=selected_item.link_ids[0],
                    account_bound=False,
                    active_palette=0,
                )
            )

        result = await bot.highrise.set_outfit(outfit)
        if result is not None:
            print(f"Error de Highrise equipando la prenda: {result}")
            return "<#FF6666>⚠️ No se pudo equipar la prenda."
    except Exception as error:
        print(f"Error equipando la prenda: {error}")
        return "<#FF6666>⚠️ No se pudo equipar la prenda."

    return f"<#66FF99>✨ Prenda equipada: {selected_item.item_name}."


COMMANDS = {"!equip": handle_equip, "/equip": handle_equip}
