from __future__ import annotations

class EmotesManager:
    def __init__(self, emotes):
        self._emotes=[]; self._id_to_emote={}; self._name_to_emote={}
        for raw in emotes or []:
            if not isinstance(raw,dict): continue
            eid=str(raw.get("emote",raw.get("id",""))).strip(); name=str(raw.get("command",raw.get("name",""))).strip()
            if not eid or not name: continue
            item=dict(raw); item["emote"]=eid; item["command"]=name
            self._emotes.append(item); self._id_to_emote[eid]=item; self._name_to_emote[name.casefold()]=item
    def get_by_id(self, emote_id): return self._id_to_emote.get(str(emote_id).strip()) if emote_id else None
    def get_by_name(self, emote_name): return self._name_to_emote.get(str(emote_name).strip().casefold()) if emote_name else None
    def get_by_index(self,index): return self._emotes[index] if isinstance(index,int) and 0<=index<len(self._emotes) else None
    def get_index_by_name(self,name):
        item=self.get_by_name(name); return self._emotes.index(item) if item else None
    def get_all(self): return list(self._emotes)
    @property
    def size(self): return len(self._emotes)
