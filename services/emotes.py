from __future__ import annotations


class EmotesManager:
    """Catálogo e índices de emotes.

    Acepta tanto nuestro formato actual (command/emote) como el formato
    encontrado en el código compartido de Discord (name/id).
    """

    def __init__(self, emotes):
        self._emotes: list[dict] = []
        self._id_to_emote: dict[str, dict] = {}
        self._name_to_emote: dict[str, dict] = {}
        self._init(emotes)

    def _init(self, emotes) -> None:
        for raw in emotes or []:
            if not isinstance(raw, dict):
                continue

            emote_id = str(raw.get("emote") or raw.get("id") or "").strip()
            name = str(raw.get("command") or raw.get("name") or "").strip()

            if not emote_id or not name:
                continue

            # Conservamos el formato original y añadimos alias compatibles
            # con el catálogo compartido de Discord.
            item = dict(raw)
            item["emote"] = emote_id
            item["command"] = name
            item["id"] = emote_id
            item["name"] = name

            self._emotes.append(item)
            self._id_to_emote[emote_id] = item
            self._name_to_emote[name.casefold()] = item

    def get_by_id(self, emote_id):
        if not emote_id or not isinstance(emote_id, str):
            return None

        return self._id_to_emote.get(emote_id.strip())

    def get_by_name(self, emote_name):
        if not emote_name or not isinstance(emote_name, str):
            return None

        return self._name_to_emote.get(emote_name.strip().casefold())

    def get_by_index(self, index):
        if not isinstance(index, int) or index < 0:
            return None

        return self._emotes[index] if index < len(self._emotes) else None

    def get_index_by_name(self, emote_name):
        if not emote_name or not isinstance(emote_name, str):
            return None

        item = self.get_by_name(emote_name)
        if item is None:
            return None

        try:
            return self._emotes.index(item)
        except ValueError:
            return None

    def get_all(self):
        return list(self._emotes)

    @property
    def size(self):
        return len(self._emotes)
