import asyncio, json, os, sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
from highrise import BaseBot, CurrencyItem, SessionMetadata, User, __main__
from highrise.__main__ import BotDefinition
from bots.dj.services.youtube import search_youtube, YouTubeSearchError
from commands.dispatcher import CommandDispatcher
from common.bot_manager import should_handle_for_bot
from common.bot_runtime import BotRuntimeMixin
from common.avatar import AvatarManager
from common.positions import PositionManagerCommon
from common.dance import DanceManager
from common.bot_state import BotStateManager
from services.music_tickets import MusicTicketManager
from services.storage import load_json
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
        self.ticket_manager = MusicTicketManager()
        self.state_file = str(DATA)
        self.playback_monitor_task = None
        self.announcement_task = None
        self.last_announced_track_id = None
        self.processed_ticket_result_ids = set()
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

                results = status.get("last_request_results") or []
                for result in results:
                    result_id = result.get("request_id")
                    if not result_id or result_id in self.processed_ticket_result_ids:
                        continue
                    self.processed_ticket_result_ids.add(result_id)
                    if result.get("status") == "played":
                        self.ticket_manager.mark_played(result_id)
                    elif result.get("status") == "failed":
                        refund = self.ticket_manager.refund_request(result_id)
                        if refund:
                            await self.highrise.send_whisper(
                                refund["user_id"],
                                f"<#FFCC66>↩️ Tu canción «{refund['title']}» no pudo reproducirse. "
                                f"Te devolví 1 ticket. <#FFFFFF>🎟️ Tickets disponibles: {refund['tickets']}"
                            )
            except asyncio.CancelledError:
                break
            except Exception as error:
                consecutive_errors += 1
                delay = min(30, 2 * consecutive_errors)
                print(f"[MUSIC] Error monitoreando reproducción (#{consecutive_errors}): {error}")
                await asyncio.sleep(delay)
                continue
            await asyncio.sleep(2)

    async def _requires_ticket(self, user:User) -> bool:
        if user.id == self.owner_id or await self.is_mod(user.id):
            return False

        try:
            privileges = await self.highrise.get_room_privilege(user.id)
            if getattr(privileges, "designer", False):
                return False
        except Exception as error:
            print(f"[TICKETS] Error comprobando privilegios de @{user.username}: {error}")

        try:
            data = load_json(os.path.join(ROOT_DIR, "roles.json"), default={})
            users = data.get("users", {}) if isinstance(data, dict) else {}
            saved_role = str(users.get(user.id, "")).lower()
            if saved_role == "vip":
                return True
            if saved_role in {"mod", "designer", "owner"}:
                return False

            legacy_vips = {
                str(value).casefold()                for value in (data.get("vip_users", []) if isinstance(data, dict) else [])            }
            if user.username.casefold() in legacy_vips:
                return True
        except Exception as error:
            print(f"[TICKETS] Error leyendo roles de @{user.username}: {error}")

        return True

    async def on_tip(self, sender:User, receiver:User, tip:CurrencyItem|object) -> None:
        if receiver.id != self.bot_id or not isinstance(tip, CurrencyItem):
            return

        try:
            result = self.ticket_manager.register_tip(
                sender.id,
                sender.username,
                int(tip.amount),
            )
            await self.highrise.send_whisper(
                sender.id,
                f"<#66FF99>💰 ¡Gracias por tu {tip.amount}g!\n"
                f"<#66CCFF>🎟️ Tickets recibidos: <#FFFFFF>{result['tickets_added']}\n"
                f"<#66CCFF>🎟️ Tickets disponibles: <#FFFFFF>{result['tickets']}\n"            )
        except Exception as error:
            print(f"[TICKETS] Error procesando oro de @{sender.username}: {error}")

    async def announcement_loop(self):
        messages = [
            "<#66CCFF>🎵 ¿Quieres pedir una canción? Usa !play canción.",
            "<#FFCC66>🎟️ Cada 10g que das al bot te da tickets para pedir canciones.",
            "<#66FF99>🎶 ¡Anímate y pide tu canción favorita con !play! Hagamos ambiente en la sala.",
            "<#CC99FF>💜 Dale vida a la sala: pide música, baila y disfruta con todos.",
        ]
        index = 0
        try:
            await asyncio.sleep(300)
            while True:
                if index % len(messages) == 1:
                    rate = self.ticket_manager.get_rate()
                    message = f"<#FFCC66>🎟️ Cada 10g que das al bot te da <#FFFFFF>{rate} ticket(s) <#FFCC66>para pedir canciones."
                else:
                    message = messages[index % len(messages)]
                await self.highrise.chat(message)
                index += 1
                await asyncio.sleep(300)
        except asyncio.CancelledError:
            pass
        except Exception as error:
            print(f"[MUSIC] Error en anuncios periódicos: {error}")
    async def on_start(self,s:SessionMetadata):
        self.bot_id=s.user_id;self.owner_id=s.room_info.owner_id
        if self.playback_monitor_task:
            self.playback_monitor_task.cancel()
        if self.announcement_task:
            self.announcement_task.cancel()
        self.announcement_task = asyncio.create_task(self.announcement_loop())
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

        # !home / !reset admiten uso sin @ para controlar ambos bots.
        if cmd in {"!home","!reset"}:
            parts_full=message.strip().split()
            if len(parts_full) != 2 or not parts_full[1].startswith("@"):
                await self.highrise.send_whisper(user.id, f"Uso: {cmd} @Dj.Z")
                return
            target=parts_full[1][1:].casefold()
            if target != self.bot_username.casefold():
                return
            if user.id != self.owner_id and not await self.is_mod(user.id):
                await self.highrise.send_whisper(user.id,"🔒 Solo el dueño o moderadores pueden usar este comando.")
                return
            if cmd=="!home":
                await self.restore_position()
                await self.highrise.send_whisper(
                    user.id, f"<#66FF99>📍 @{self.bot_username} volvió a su posición guardada."
                )
                return
            asyncio.create_task(self.restart_with_message())
            return

        protected={"!set","!home","!reset","!dancebot","!botdance","!stopdance","!stopbotdance","!color","!equip","/equip","!remove","/remove","!getoutfit","/getoutfit"}
        if cmd in protected and not await self._is_targeted_for_me(message):
            return

        if cmd == "!help" and len(parts) == 2 and parts[1].strip().lower() == "music":
            role = "user"
            if user.id == self.owner_id:
                role = "owner"
            else:
                try:
                    privileges = await self.highrise.get_room_privilege(user.id)
                    if getattr(privileges, "moderator", False):
                        role = "mod"
                    elif getattr(privileges, "designer", False):
                        role = "designer"
                except Exception as error:
                    print(f"[MUSIC HELP] Error comprobando privilegios de @{user.username}: {error}")

                try:
                    data = load_json(os.path.join(ROOT_DIR, "roles.json"), default={})
                    users = data.get("users", {}) if isinstance(data, dict) else {}
                    saved_role = str(users.get(user.id, "")).lower()
                    if saved_role in {"vip", "mod", "designer"}:
                        role = saved_role
                except Exception as error:
                    print(f"[MUSIC HELP] Error leyendo roles de @{user.username}: {error}")

            sections = [
                "<#66CCFF>🎵 COMANDOS DE MÚSICA",
                "<#FFFFFF>• !play canción - Solicitar una canción (usa 1 ticket).",
                "<#FFFFFF>• !q - Ver la cola actual.",
                "<#FFFFFF>• !review / !r - Ver la canción que está sonando.",
                "<#FFFFFF>• !ticket - Ver cuántos tickets entrega el bot por 10g.",
            ]
            if role in {"owner", "mod"}:
                sections.extend([
                    "<#FFFFFF>• !skip - Saltar la canción actual.",
                    "<#FFFFFF>• !ap canción - Agregar una canción a la playlist.",
                    "<#FFFFFF>• !rp canción - Quitar una canción de la playlist.",
                    "<#FFFFFF>• !addticket numero @usuario - Regalar tickets.",
                    "<#FFFFFF>• !at numero @usuario - Alias para regalar tickets.",
                    "<#FFFFFF>• !ticket for numero - Configurar tickets por cada 10g.",
                ])
            elif role == "designer":
                sections.append("<#FFFFFF>• !skip - Saltar la canción actual.")
            await self.highrise.send_whisper(user.id, "\n".join(sections))
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
            if user.id != self.owner_id and not await self.is_mod(user.id):                return await self.highrise.send_whisper(user.id, "<#FF6666>🔒 Solo el dueño o moderadores pueden controlar el emote del bot.")
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
            if not q:
                return await self.highrise.send_whisper(user.id,"<#FFCC66>🎵 Uso: !play canción")

            try:
                role_requires_ticket = await self._requires_ticket(user)
                v=await asyncio.to_thread(search_youtube,q)
                request_id = None
                if role_requires_ticket:
                    request_id, ticket_error = self.ticket_manager.charge_request(
                        user.id, user.username, v["video_id"], v["title"]
                    )
                    if ticket_error:
                        return await self.highrise.send_whisper(
                            user.id,
                            f"<#FF6666>🎟️ {ticket_error}"
                        )

                metadata=dict(v)
                metadata["requested_by"]=user.username
                if request_id:
                    metadata["request_id"]=request_id

                try:
                    await self.api(
                        "/play",
                        "POST",
                        {"video_id":v["video_id"],"metadata":metadata,"request_id":request_id},
                    )
                except Exception:
                    if request_id:
                        self.ticket_manager.refund_request(request_id)
                    raise

                if request_id:
                    balance=self.ticket_manager.get_balance(user.id,user.username)
                    await self.highrise.send_whisper(
                        user.id,
                        f"<#66FF99>🎵 Petición enviada: <#FFFFFF>{v['title']}\n"
                        f"<#66CCFF>🎟️ Te queda(n): <#FFFFFF>{balance['tickets']} ticket(s)."
                    )
                else:
                    await self.highrise.chat(
                        f"<#66FF99>🎵 @{user.username} añadió a la cola: <#FFFFFF>{v['title']}"
                    )
            except (YouTubeSearchError,RuntimeError) as e:
                await self.highrise.send_whisper(user.id,f"<#FF6666>⚠️ {e}")
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
        if cmd in ("!ticket","!addticket","!at"):
            parts_full=message.strip().split()
            if cmd=="!ticket":
                if len(parts_full)==3 and parts_full[1].lower()=="for":
                    if user.id!=self.owner_id and not await self.is_mod(user.id):
                        return await self.highrise.send_whisper(user.id,"<#FF6666>🔒 Solo el dueño o moderadores pueden configurar los tickets.")
                    try:
                        amount=int(parts_full[2])
                        rate=self.ticket_manager.set_rate(amount)
                        return await self.highrise.send_whisper(
                            user.id,
                            f"<#66FF99>🎟️ Configuración actualizada: <#FFFFFF>{rate} ticket(s) por cada 10g."
                        )
                    except ValueError as error:
                        return await self.highrise.send_whisper(user.id,f"<#FFCC66>🎟️ {error}")
                rate=self.ticket_manager.get_rate()
                return await self.highrise.send_whisper(
                    user.id,
                    f"<#66CCFF>🎟️ El bot entrega <#FFFFFF>{rate} ticket(s) por cada 10g."
                )

            if user.id!=self.owner_id and not await self.is_mod(user.id):
                return await self.highrise.send_whisper(user.id,"<#FF6666>🔒 Solo el dueño o moderadores pueden regalar tickets.")
            if len(parts_full)!=3 or not parts_full[2].startswith("@"):
                return await self.highrise.send_whisper(
                    user.id,
                    f"<#FFCC66>🎟️ Uso: {parts_full[0]} numero @usuario"
                )
            try:
                amount=int(parts_full[1])
                if amount<1:
                    raise ValueError("La cantidad de tickets debe ser mayor que 0.")
            except ValueError as error:
                return await self.highrise.send_whisper(user.id,f"<#FFCC66>🎟️ {error}")

            target_username=parts_full[2][1:]
            target_id=await self.get_user_id(target_username)
            if not target_id:
                return await self.highrise.send_whisper(user.id,"<#FFCC66>🔎 Usuario no encontrado en la sala.")

            try:
                balance=self.ticket_manager.add_tickets(target_id,target_username,amount)
                await self.highrise.send_whisper(
                    user.id,
                    f"<#66FF99>🎁 Añadiste {amount} ticket(s) a @{target_username}. "
                    f"<#FFFFFF>Ahora tiene {balance['tickets']} ticket(s)."
                )
                await self.highrise.send_whisper(
                    target_id,
                    f"<#66FF99>🎁 @{user.username} te regaló {amount} ticket(s). "
                    f"<#FFFFFF>Ahora tienes {balance['tickets']} ticket(s)."
                )
            except Exception as error:
                print(f"[TICKETS] Error regalando tickets: {error}")
                return await self.highrise.send_whisper(user.id,"<#FF6666>⚠️ No se pudieron agregar los tickets.")
            return

        if cmd in ("!q","!queue","!review","!r"):
            try:
                s=await self.api("/status");cur=s.get("current") or {};m=cur.get("metadata",{})
                requester=m.get("requested_by")
                now_line=f"<#66CCFF>🎵 Ahora: <#FFFFFF>{m.get('title','Nada')}"
                if requester:
                    now_line += f" <#66FF99>• solicitada por @{requester}"
                if cmd in ("!q","!queue"):
                    pending=await self.api("/queue")
                    items=pending if isinstance(pending,list) else []
                    count=len(items)
                    lines=[
                        now_line,
                        f"<#66FF99>📋 Cola: <#FFFFFF>{count}",
                    ]
                    if not items:
                        lines.append("<#FFFFFF>Sin canciones pendientes.")
                    else:
                        for i,x in enumerate(items,1):
                            metadata=x.get("metadata") or {}
                            title=metadata.get("title","Pista")
                            requested_by=metadata.get("requested_by")
                            line=f"<#FFFFFF>{i}. {title}"
                            if requested_by:
                                line += f" <#66FF99>• @{requested_by}"
                            lines.append(line)                    await self.highrise.chat("\n".join(lines))
                    return
                e=int(s.get("elapsed",0));d=int(m.get("duration") or 0)
                review=f"{now_line} <#FFFFFF>• {e//60}:{e%60:02d}"
                if d:
                    review += f" / {d//60}:{d%60:02d}"
                return await self.highrise.chat(review)
            except RuntimeError as e:
                return await self.highrise.send_whisper(user.id,f"<#FF6666>⚠️ {e}")
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