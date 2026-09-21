from __future__ import annotations

import json
import os
import re
import unicodedata
from types import SimpleNamespace
from urllib.parse import parse_qs, quote, urlencode, urlparse
from urllib.request import Request, urlopen

from highrise import BaseBot, User

from common.avatar import CATEGORY_LABELS


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _extract_item_id(value: str) -> str | None:
    value = value.strip()
    if value.startswith(("http://", "https://")):
        parsed = urlparse(value)
        item_id = parse_qs(parsed.query).get("id", [None])[0]
        return item_id.strip() if item_id else None

    category = value.split("-", 1)[0].lower() if "-" in value else ""
    if category in CATEGORY_LABELS and value.count("-") >= 1:
        return value

    return None


def _is_avatar_category(category: str) -> bool:
    return bool(category) and category in CATEGORY_LABELS


def _item_category(item) -> str:
    category = getattr(item, "category", None)
    return str(getattr(category, "value", category) or "").lower()


def _pick_item(items, query: str, result_index: int):
    if not items:
        return None

    normalized_query = _normalize(query)
    exact = [
        item for item in items
        if _normalize(getattr(item, "item_name", "")) == normalized_query
    ]
    candidates = exact or [
        item for item in items
        if _is_avatar_category(_item_category(item))
    ]
    if not candidates:
        return None

    if not exact:
        query_tokens = set(normalized_query.split())

        def score(item):
            name = _normalize(getattr(item, "item_name", ""))
            name_tokens = set(name.split())
            return (
                len(query_tokens & name_tokens),
                int(normalized_query in name),
                -abs(len(name_tokens) - len(query_tokens)),
            )

        candidates = sorted(candidates, key=score, reverse=True)

    if result_index < 0 or result_index >= len(candidates):
        return None
    return candidates[result_index]


def _public_item_request(path: str, params: dict | None = None):
    url = f"https://webapi.highrise.game{path}"
    if params:
        url = f"{url}?{urlencode(params)}"
    api_key = os.environ.get("MUSIC_API_KEY") or os.environ.get("BOT1_API_KEY") or os.environ.get("HIGHRISE_API_KEY") or ""
    headers = {"Accept": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key
    request = Request(url, headers=headers)
    with urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def _public_item_to_object(data):
    return SimpleNamespace(
        item_id=data.get("item_id", ""),
        item_name=data.get("item_name", ""),
        category=SimpleNamespace(value=data.get("category")),
        is_purchasable=bool(data.get("is_purchasable", False)),
        rarity=str(data.get("rarity", "none") or "none").lower(),
        link_ids=data.get("link_ids", []) or [],
    )


async def _get_public_item(item_id: str):
    try:
        data = _public_item_request(f"/items/{quote(item_id, safe='')}")
        return _public_item_to_object(data.get("item", data))
    except Exception as error:
        print(f"Error obteniendo artículo público '{item_id}': {error}")
        return None


async def _search_item(bot: BaseBot, query: str, result_index: int):
    queries = [query]
    words = query.split()
    if len(words) >= 3:
        queries.extend([" ".join(words[:2]), " ".join(words[-2:])])

    seen = set()
    all_items = []
    for search_query in queries:
        if not search_query or search_query.lower() in seen:
            continue
        seen.add(search_query.lower())
        try:
            data = _public_item_request(
                "/items",
                {"item_name": search_query, "limit": 50},
            )
            items = [_public_item_to_object(item) for item in data.get("items", [])]
        except Exception as error:
            print(f"Error buscando el artículo '{search_query}': {error}")
            continue

        existing_ids = {existing.item_id for existing in all_items}
        for item in items:
            if item.item_id not in existing_ids:
                all_items.append(item)
                existing_ids.add(item.item_id)

        selected = _pick_item(all_items, query, result_index)
        if selected is not None:
            return selected

    return _pick_item(all_items, query, result_index)


async def handle_equip(bot: BaseBot, user: User, message: str) -> str:
    if user.id != bot.owner_id and not await bot.is_mod(user.id):
        return "<#FF6666>👗 Solo el dueño o los moderadores pueden equipar prendas."

    parts = message.split()
    if len(parts) >= 2 and parts[1].startswith("@"):
        parts = [parts[0], *parts[2:]]
    if len(parts) < 2:
        return "<#FFCC66>👗 Uso: !equip @BotUsuario <nombre, ID o URL de la prenda> [numero]"

    result_index = 0
    item_name_parts = parts[1:]
    if item_name_parts[-1].isdigit():
        result_index = int(item_name_parts.pop()) - 1
        if result_index < 0:
            return "<#FFCC66>🔢 El número de resultado debe ser mayor que 0."

    item_query = " ".join(item_name_parts).strip()
    if not item_query:
        return "<#FFCC66>👚 Debes indicar el nombre, ID o URL de la prenda."

    try:
        inventory = (await bot.highrise.get_inventory()).items
    except Exception as error:
        print(f"Error consultando el inventario: {error}")
        return "<#FF6666>⚠️ No se pudo consultar el inventario del bot."

    item_id = _extract_item_id(item_query)
    selected_item = None
    owns_item = False
    item_display_name = item_query
    category = ""

    if item_id:
        inventory_item = next((item for item in inventory if item.id == item_id), None)
        if inventory_item is not None:
            owns_item = True
            item_display_name = item_id
            category = item_id.split("-", 1)[0].lower()
        else:
            # Para IDs/URLs directos no dependemos del Web API público:
            # ese endpoint puede devolver 403 desde ciertos servidores.
            item_display_name = item_id
            category = item_id.split("-", 1)[0].lower()
            owns_item = False
    else:
        selected_item = await _search_item(bot, item_query, result_index)
        if selected_item is None:
            return f"<#FFCC66>🔎 No se encontró la prenda '{item_query}'."

        item_id = selected_item.item_id
        item_display_name = selected_item.item_name or item_id
        category = _item_category(selected_item)
        if not category:
            category = item_id.split("-", 1)[0].lower()
        owns_item = any(item.id == item_id for item in inventory)

    if not item_id or not _is_avatar_category(category):
        return "<#FF6666>⚠️ El artículo encontrado no es una prenda de avatar válida."

    if not owns_item:
        if selected_item is None:
            return f"<#FFCC66>🛍️ La prenda '{item_display_name}' no está en el inventario."

        rarity = getattr(selected_item, "rarity", "none")
        if rarity != "none" and not selected_item.is_purchasable:
            return (
                f"<#FFCC66>🛍️ La prenda '{item_display_name}' no está disponible "
                "para compra directa."
            )

        if rarity != "none":
            try:
                purchase_result = await bot.highrise.buy_item(item_id)
            except Exception as error:
                print(f"Error comprando la prenda '{item_id}': {error}")
                return "<#FF6666>⚠️ No se pudo comprar la prenda."

            if purchase_result != "success":
                return (
                    f"<#FF6666>⚠️ No se pudo comprar '{item_display_name}'. "
                    "Verifica que el bot tenga suficiente oro."
                )

    return await bot.avatar_manager.equip_item(item_id, category, item_display_name)


COMMANDS = {"!equip": handle_equip, "/equip": handle_equip}
