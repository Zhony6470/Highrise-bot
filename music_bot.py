import asyncio, json, os
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
from highrise import BaseBot, Position, SessionMetadata, User, __main__
from highrise.__main__ import BotDefinition
from services.youtube import search_youtube, YouTubeSearchError
from commands.color import handle_color
from commands.equip import handle_equip
from commands.remove import handle_remove
from commands.outfit import handle_get_outfit

ROOM_ID=os.getenv("MUSIC_ROOM_ID",os.getenv("ROOM_ID",""));API_KEY=os.getenv("MUSIC_API_KEY","")
AUTODJ=os.getenv("AUTODJ_URL","http://autodj:8090").rstrip("/");TOKEN=os.getenv("AUTODJ_TOKEN","")
DATA=Path(os.getenv("MUSIC_DATA_FILE","/app/music_bot_data.json"))

def load():
    try:return json.loads(DATA.read_text(encoding="utf-8"))
    except (FileNotFoundError,OSError,ValueError):return {}
def save(x):DATA.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding="utf-8")

class Bot(BaseBot):
    def __init__(self):super().__init__();self.bot_id=None;self.owner_id=None
    async def is_mod(self,uid):
        if uid==self.owner_id:return True
        try:
            p=await self.highrise.get_room_privilege(uid);return bool(getattr(p,"moderator",False) or getattr(p,"designer",False))
        except Exception:return False
    async def get_user_position(self,uid):
        for u,p in (await self.highrise.get_room_users()).content:
            if u.id==uid:return p
    async def api(self,path,method="GET",data=None):
        body=None if data is None else json.dumps(data).encode();h={"Authorization":f"Bearer {TOKEN}"} if TOKEN else {}
        if body:h["Content-Type"]="application/json"
        req=Request(AUTODJ+path,data=body,headers=h,method=method)
        try:return json.loads((await asyncio.to_thread(urlopen,req,10)).read().decode())
        except (HTTPError,URLError,TimeoutError,ValueError) as e:raise RuntimeError("AutoDJ no está disponible.") from e
    async def on_start(self,s:SessionMetadata):
        self.bot_id=s.user_id;self.owner_id=s.room_info.owner_id
        p=load().get("bot_position")
        if p:
            try:await asyncio.sleep(2);await self.highrise.teleport(self.bot_id,Position(p["x"],p["y"],p["z"],p["facing"]))
            except Exception as e:print("[MUSIC] posición:",e)
    async def on_chat(self,user:User,message:str):
        parts=message.strip().split(maxsplit=1);cmd=parts[0].lower() if parts else ""
        protected={"!set","!home","!color","!equip","/equip","!remove","/remove","!getoutfit","/getoutfit"}
        if cmd in protected:
            if user.id!=self.owner_id and not await self.is_mod(user.id):return await self.highrise.send_whisper(user.id,"🔒 Sin permisos.")
            if cmd=="!set":
                p=await self.get_user_position(user.id)
                if not p:return await self.highrise.send_whisper(user.id,"📍 No pude obtener tu posición.")
                save({"bot_position":{"x":p.x,"y":p.y,"z":p.z,"facing":p.facing}});await self.highrise.teleport(self.bot_id,p)
                return await self.highrise.send_whisper(user.id,"📍 Posición del bot de música guardada.")
            if cmd=="!home":
                p=load().get("bot_position")
                if p:await self.highrise.teleport(self.bot_id,Position(p["x"],p["y"],p["z"],p["facing"]))
                return await self.highrise.send_whisper(user.id,"🏠 Bot de música volvió a su posición.")
            fn={"!color":handle_color,"!equip":handle_equip,"/equip":handle_equip,"!remove":handle_remove,"/remove":handle_remove,"!getoutfit":handle_get_outfit,"/getoutfit":handle_get_outfit}[cmd]
            return await self.highrise.send_whisper(user.id,await fn(self,user,message) or "OK")
        if cmd=="!play":
            q=parts[1] if len(parts)==2 else ""
            if not q:return await self.highrise.send_whisper(user.id,"🎵 Uso: !play canción")
            try:
                v=await asyncio.to_thread(search_youtube,q);await self.api("/play","POST",{"video_id":v["video_id"],"metadata":v})
                await self.highrise.chat(f"🎵 @{user.username} añadió: {v['title']}")
            except (YouTubeSearchError,RuntimeError) as e:await self.highrise.send_whisper(user.id,f"⚠️ {e}")
            return
        if cmd=="!skip":
            if user.id!=self.owner_id and not await self.is_mod(user.id):return await self.highrise.send_whisper(user.id,"🔒 Solo dueño/mod.")
            try:await self.api("/skip","POST");await self.highrise.chat("⏭️ Saltando...")
            except RuntimeError as e:await self.highrise.send_whisper(user.id,f"⚠️ {e}")
            return
        if cmd in ("!q","!queue","!review","!reviw"):
            try:
                s=await self.api("/status");cur=s.get("current") or {};m=cur.get("metadata",{})
                if cmd in ("!q","!queue"):
                    lines=[f"🎵 Ahora: {m.get('title','Nada')}",f"📋 Cola: {len(s.get('queue',[]))}"]
                    lines += [f"{i}. {(x.get('metadata') or {}).get('title','Pista')}" for i,x in enumerate(s.get("queue",[])[:8],1)]
                    return await self.highrise.send_whisper(user.id,"\n".join(lines))
                e=int(s.get("elapsed",0));d=int(m.get("duration") or 0)
                return await self.highrise.send_whisper(user.id,f"🎧 {m.get('title','Nada')} • {e//60}:{e%60:02d}"+(f" / {d//60}:{d%60:02d}" if d else ""))
            except RuntimeError as e:return await self.highrise.send_whisper(user.id,f"⚠️ {e}")
        if cmd in ("!ap","!addplay","!rp","!removeplay"):
            if user.id!=self.owner_id and not await self.is_mod(user.id):return await self.highrise.send_whisper(user.id,"🔒 Solo dueño/mod.")
            q=parts[1].strip() if len(parts)==2 else ""
            if not q:
                return await self.highrise.send_whisper(user.id,"🎵 Uso: !ap canción o !rp canción")
            try:
                v=await asyncio.to_thread(search_youtube,q);path="/default-add" if cmd in ("!ap","!addplay") else "/default-remove";await self.api(path,"POST",{"video_id":v["video_id"],"metadata":v})
                await self.highrise.chat(f"🎵 «{v['title']}» {'añadida a' if path.endswith('add') else 'eliminada de'} la playlist.")
            except (YouTubeSearchError,RuntimeError) as e:await self.highrise.send_whisper(user.id,f"⚠️ {e}")

definitions=[BotDefinition(Bot(),ROOM_ID,API_KEY)]
if __name__=="__main__":asyncio.run(__import__("highrise").__main__.main(definitions))
