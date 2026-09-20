import asyncio, json, os, sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
from highrise import BaseBot, SessionMetadata, User, __main__
from highrise.__main__ import BotDefinition
from bots.dj.services.youtube import search_youtube, YouTubeSearchError
from commands.dispatcher import CommandDispatcher
from common.bot_manager import should_handle_for_bot
from common.bot_runtime import BotRuntimeMixin
from common.avatar import AvatarManager
from common.positions import PositionManagerCommon
from common.dance import DanceManager
from common.bot_state import BotStateManager
from services.emotes import EmotesManager

ROOM_ID=os.getenv("MUSIC_ROOM_ID",os.getenv("ROOM_ID",""));API_KEY=os.getenv("MUSIC_API_KEY","")
AUTODJ=os.getenv("AUTODJ_URL","http://autodj:8090").rstrip("/");TOKEN=os.getenv("AUTODJ_TOKEN","")
DATA=Path(os.getenv("MUSIC_DATA_FILE","/app/music_bot_data.json"))

class Bot(BotRuntimeMixin, BaseBot):
    def __init__(self):
        super().__init__();self.bot_id=None;self.owner_id=None
        self.bot_username = os.getenv("DJ_BOT_USERNAME", "Dj.Z")
        self.avatar_manager = AvatarManager(self)
        self.position_manager_common = PositionManagerCommon(self, str(DATA))
        self.dance_manager = DanceManager(self)
        self.bot_state_manager = BotStateManager(self)
        self.state_file = str(DATA)
        self.playback_monitor_task = None
        self.last_announced_track_id = None
        try:
            self.emotes_list = json.loads((Path(ROOT_DIR) / "common" / "emotes.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.emotes_list = []
        self.emotes_manager = EmotesManager(self.emotes_list)
        self.command_dispatcher = CommandDispatcher()
    async def api(self,path,method="GET",data=None):
        body=None if data is None else json.dumps(data).encode()
        h={"Authorization":f"Bearer {TOKEN}"} if TOKEN else {}
        if body:
            h["Content-Type"]="application/json"

        req=Request(AUTODJ+path,data=body,headers=h,method=method)

        try:
            response=await asyncio.to_thread(urlopen,req,timeout=10)
            return json.loads(response.read().decode())

        except HTTPError as e:
            try:
                detail=e.read().decode()
            except Exception:
                detail=""

            try:
                payload=json.loads(detail)
                message=payload.get("error") or payload.get("message") or detail
            except Exception:
                message=detail or str(e)

            raise RuntimeError(f"AutoDJ respondió HTTP {e.code}: {message}") from e

        except (URLError,TimeoutError) as e:
            raise RuntimeError("AutoDJ no está disponible.") from e

        except ValueError as e:
            raise RuntimeError("Respuesta inválida de AutoDJ.") from e
    async def restore_position(self):
        for attempt in range(5):
            try:
                position = self.position_manager_common.get_saved_position()
                if position:
                    await asyncio.sleep(2 if attempt == 0 else 3)
                    await self.highrise.teleport(self.bot_id, position)
                    print(f"[MUSIC] Posición restaurada en {position}.")
                    return
            except Exception as error:
                print(f"[MUSIC] Error restaurando posición (intento {attempt + 1}): {error}")
            await asyncio.sleep(2)

    async def playback_monitor_loop(self):
        consecutive_errors = 0
        while True:
            try:
                status = await self.api("/status")
                consecutive_errors = 0
                current = status.get("current") or {}
                video_id = current.get("video_id")
                if video_id and video_id != self.last_announced_track_id:
                    metadata = current.get("metadata") or {}
                    title = metadata.get("title", "Pista desconocida")
                    requester = metadata.get("requested_by")
                    if requester:
                        await self.highrise.chat(
                            f"<#66CCFF>🎵 Ahora sonando: <#FFFFFF>{title} <#66FF99>• petición de @{requester}"
                        )
                    else:
                        await self.highrise.chat(
                            f"<#66CCFF>🎵 Ahora sonando: <#FFFFFF>{title}"
                        )
                    self.last_announced_track_id = video_id
            except asyncio.CancelledError:
                break
            except Exception as error:
                consecutive_errors += 1
                delay = min(30, 2 * consecutive_errors)
                print(f"[MUSIC] Error monitoreando reproducción (#{consecutive_errors}): {error}")
                await asyncio.sleep(delay)
                continue
            await asyncio.sleep(2)

    async def on_start(self,s:SessionMetadata):
        self.bot_id=s.user_id;self.owner_id=s.room_info.owner_id
        if self.playback_monitor_task:
            self.playback_monitor_task.cancel()
        self.playback_monitor_task = asyncio.create_task(self.playback_monitor_loop())
        asyncio.create_task(self.restore_position())
        try:
            await self.avatar_manager.restore_saved_outfit()
        except Exception as e:
            print("[MUSIC] outfit:", e)
        await self.dance_manager.restore()

    async def restart_with_message(self):
        try:
            await self.highrise.chat("<#FFCC66>🔄 Reiniciando el bot de música... <#FFFFFF>Vuelvo en unos segundos.")
        except Exception:
            pass
        await asyncio.sleep(1)
        os._exit(0)

    async def _is_targeted_for_me(self, message:str) -> bool:
        return await should_handle_for_bot(self, message)

    async def on_chat(self,user:User,message:str):
        parts=message.strip().split(maxsplit=1);cmd=parts[0].lower() if parts else ""
        protected={"!set","!home","!reset","!dancebot","!botdance","!stopdance","!stopbotdance","!color","!equip","/equip","!remove","/remove","!getoutfit","/getoutfit"}
        if cmd in protected and not await self._is_targeted_for_me(message):
            return

        if cmd in self.command_dispatcher.handlers:
            response = await self.command_dispatcher.handle(self, user, message.strip())
            if response:
                await self.highrise.send_whisper(user.id, response)
            return
        if cmd == "!emote":
            emote_parts = message.strip().split()
            if len(emote_parts) < 3 or not emote_parts[1].startswith("@"):
                return await self.highrise.send_whisper(user.id, "<#FFCC66>🎭 Uso: !emote @Dj.Z <emote> o !emote @Dj.Z stop")
            target = emote_parts[1][1:]
            if target.lower() != self.bot_username.lower():
                return
            if user.id != self.owner_id and not await self.is_mod(user.id):
                return await self.highrise.send_whisper(user.id, "<#FF6666>🔒 Solo el dueño o moderadores pueden controlar el emote del bot.")
            if " ".join(emote_parts[2:]).strip().lower() == "stop":
                response = await self.dance_manager.stop_bot_emote()
            else:
                emote_name = " ".join(emote_parts[2:]).strip().lower()
                if emote_name.isdigit():
                    matched = self.emotes_manager.get_by_index(int(emote_name) - 1)
                else:
                    matched = self.emotes_manager.get_by_name(emote_name)
                if not matched:
                    return await self.highrise.send_whisper(
                        user.id,
                        f"<#FFCC66>🎭 Emote no encontrado: {emote_name}."
                    )
                response = await self.dance_manager.start_bot_emote(matched["emote"])
            return await self.highrise.send_whisper(user.id, response)
        if cmd=="!play":
            q=parts[1] if len(parts)==2 else ""
            if not q:return await self.highrise.send_whisper(user.id,"<#FFCC66>🎵 Uso: !play canción")
            try:
                v=await asyncio.to_thread(search_youtube,q)
                metadata=dict(v)
                metadata["requested_by"]=user.username
                await self.api("/play","POST",{"video_id":v["video_id"],"metadata":metadata})
                await self.highrise.chat(f"<#66FF99>🎵 @{user.username} añadió a la cola: <#FFFFFF>{v['title']}")
            except (YouTubeSearchError,RuntimeError) as e:await self.highrise.send_whisper(user.id,f"<#FF6666>⚠️ {e}")
            return
        if cmd=="!skip":
            if user.id!=self.owner_id and not await self.is_mod(user.id):return await self.highrise.send_whisper(user.id,"<#FF6666>🔒 Solo el dueño o moderadores pueden saltar.")
            try:await self.api("/skip","POST");await self.highrise.chat("<#FFCC66>⏭️ Saltando la pista actual...")
            except RuntimeError as e:await self.highrise.send_whisper(user.id,f"<#FF6666>⚠️ {e}")
            return

        if message.strip().lower() == "!restart":
            if user.id == self.owner_id or await self.is_mod(user.id):
                await self.restart_with_message()
            else:
                await self.highrise.send_whisper(user.id, "<#FF6666>🔒 Solo el dueño o moderadores pueden reiniciar el bot.")
            return
        if cmd in ("!q","!queue","!review","!reviw"):
            try:
                s=await self.api("/status");cur=s.get("current") or {};m=cur.get("metadata",{})
                if cmd in ("!q","!queue"):
                    pending=await self.api("/queue")
                    items=pending if isinstance(pending,list) else []
                    count=len(items)
                    first_lines=[
                        f"<#66CCFF>🎵 Ahora: <#FFFFFF>{m.get('title','Nada')}",
                        f"<#66FF99>📋 Cola: <#FFFFFF>{count}",
                    ]
                    if not items:
                        first_lines.append("<#FFFFFF>Sin canciones pendientes.")
                    else:
                        first_lines.extend(
                            f"<#FFFFFF>{i}. {(x.get('metadata') or {}).get('title','Pista')}"
                            for i,x in enumerate(items[:5],1)
                        )
                    await self.highrise.send_whisper(user.id,"\n".join(first_lines))
                    for offset in range(5,count,5):
                        chunk=items[offset:offset+5]
                        lines=[
                            f"<#FFFFFF>{i}. {(x.get('metadata') or {}).get('title','Pista')}"
                            for i,x in enumerate(chunk,offset+1)
                        ]
                        await self.highrise.send_whisper(user.id,"\n".join(lines))
                    return
                e=int(s.get("elapsed",0));d=int(m.get("duration") or 0)
                return await self.highrise.send_whisper(user.id,f"<#66CCFF>🎵 {m.get('title','Nada')} <#FFFFFF>• {e//60}:{e%60:02d}"+(f" / {d//60}:{d%60:02d}" if d else ""))
            except RuntimeError as e:return await self.highrise.send_whisper(user.id,f"<#FF6666>⚠️ {e}")
        if cmd in ("!ap","!addplay","!rp","!removeplay"):
            if user.id!=self.owner_id and not await self.is_mod(user.id):return await self.highrise.send_whisper(user.id,"<#FF6666>🔒 Solo el dueño o moderadores pueden gestionar la playlist.")
            q=parts[1].strip() if len(parts)==2 else ""
            if not q:
                return await self.highrise.send_whisper(user.id,"<#FFCC66>🎵 Uso: !ap canción o !rp canción")
            try:
                v=await asyncio.to_thread(search_youtube,q);path="/default-add" if cmd in ("!ap","!addplay") else "/default-remove";await self.api(path,"POST",{"video_id":v["video_id"],"metadata":v})
                action="añadida a" if path.endswith("add") else "eliminada de"
                await self.highrise.chat(f"<#66FF99>🎵 «{v['title']}» {action} la playlist.")
            except (YouTubeSearchError,RuntimeError) as e:await self.highrise.send_whisper(user.id,f"<#FF6666>⚠️ {e}")

definitions=[BotDefinition(Bot(),ROOM_ID,API_KEY)]
if __name__=="__main__":asyncio.run(__import__("highrise").__main__.main(definitions))

