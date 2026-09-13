class EmotesManager:
    def __init__(self, emotes):
        self.__id_to_emote = {}
        self.__name_to_emote = {}
        self.__init(emotes)

    def __init(self, emotes):
        for emote in emotes:
            self.__id_to_emote[emote["emote"]] = emote
            self.__name_to_emote[emote["command"]] = emote

    def get_by_id(self, emote_id):
        if not emote_id or not isinstance(emote_id, str):
            return None
        return self.__id_to_emote.get(emote_id)

    def get_by_name(self, emote_name):
        if not emote_name or not isinstance(emote_name, str):
            return None
        emote_name = emote_name.lower()
        for name, emote in self.__name_to_emote.items():
            if name.lower() == emote_name:
                return emote
        return None

    def get_by_index(self, index):
        if not isinstance(index, int) or index < 0:
            return None
        emotes_list = list(self.__id_to_emote.values())
        return emotes_list[index] if index < len(emotes_list) else None

    def get_index_by_name(self, emote_name):
        if not emote_name or not isinstance(emote_name, str):
            return None
        for index, emote in enumerate(self.__id_to_emote.values()):
            if emote.get("command", "").lower() == emote_name.lower():
                return index
        return None

    def get_all(self):
        return list(self.__id_to_emote.values())

    @property
    def size(self):
        return len(self.__id_to_emote)
