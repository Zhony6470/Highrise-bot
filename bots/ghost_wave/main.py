import asyncio, json, os, re
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from zoneinfo import ZoneInfo
from highrise import BaseBot, SessionMetadata
from highrise.__main__ import BotDefinition, main as highrise_main

DATA=Path(os.getenv("GHOST_WAVE_DATA_FILE","/app/bots/ghost_wave/data/ghost_wave.json"))
DEFAULT_INTERVAL=int(os.getenv("GHOST_WAVE_DEFAULT_INTERVAL","75"))
TZNAME=os.getenv("GHOST_WAVE_TIMEZONE","UTC")

class Store:
    def __init__(self):
        self.d={"enabled":False,"interval":DEFAULT_INTERVAL,"next":None,"last":None,"waiting":False,"alerted":False,"room":None,"rooms":{},"admins":[],"subs":[],"conversations":{},"names":{}}
        try:
            if DATA.exists(): self.d.update(json.loads(DATA.read_text(encoding="utf8")))
        except Exception as e: print("[GHOST] load:",e)
        for k,v in {"rooms":{},"admins":[],"subs":[],"conversations":{},"names":{}}.items(): self.d.setdefault(k,v)
    def save(self):
        DATA.parent.mkdir(parents=True,exist_ok=True)
        t=DATA.with_suffix(".tmp"); t.write_text(json.dumps(self.d,ensure_ascii=False,indent=2),encoding="utf8"); t.replace(DATA)

class Bot(BaseBot):
    def __init__(self):
        super().__init__(); self.owner_id=None; self.bot_id=None; self.store=Store(); self.task=None
    @property
    def tz(self):
        try:return ZoneInfo(str(self.store.d.get("timezone") or TZNAME))
        except:return ZoneInfo("UTC")
    def now(self): return datetime.now(self.tz)
    def clock(self,s,base=None):
        m=re.fullmatch(r"(\d{1,2}):(\d{2})",s.strip())
        if not m:return None
        h,n=map(int,m.groups())
        if h>23 or n>59:return None
        base=base or self.now(); x=base.replace(hour=h,minute=n,second=0,microsecond=0)
        return x if x>base else x+timedelta(days=1)
    def iso(self,x):
        try:return datetime.fromisoformat(x) if x else None
        except:return None
    def owner(self,u): return u==self.owner_id
    def admin(self,u): return self.owner(u) or u in self.store.d["admins"]
    def fmt(self,x): return x.astimezone(self.tz).strftime("%d/%m %H:%M") if x else "no configurada"
    async def inbox(self,u,msg):
        cid=self.store.d["conversations"].get(u)
        try:
            if cid and await self.highrise.send_message(cid,msg) is None:return True
        except Exception as e: print("[GHOST] inbox:",e)
        try:return await self.highrise.send_message_bulk([u],msg) is None
        except Exception as e: print("[GHOST] bulk:",e); return False
    async def broadcast(self,ids,msg):
        for u in list(dict.fromkeys(ids)):
            await self.inbox(u,msg); await asyncio.sleep(.15)
    async def find(self,name):
        name=name.lstrip("@")
        try:
            r=await self.webapi.get_users(username=name)
            x=next((u for u in r.users if u.username.casefold()==name.casefold()),None)
            if x:return x.id,x.username
        except Exception as e: print("[GHOST] find:",e)
        return None
    def room_id(self,link):
        q=parse_qs(urlparse(link).query)
        if q.get("id"):return q["id"][0]
        m=re.search(r"(?:room[=/]|id=)([A-Za-z0-9_-]{10,})",link)
        return m.group(1) if m else None
    def status(self):
        n=self.iso(self.store.d["next"]); l=self.iso(self.store.d["last"])
        r=self.store.d["rooms"].get(self.store.d["room"],{})
        return f"👻 GHOST WAVE\n{'🟢 ACTIVO' if self.store.d['enabled'] else '⏸️ DETENIDO'}\n⏱️ Intervalo: {self.store.d['interval']} min\n📅 Próxima: {self.fmt(n)}\n🕐 Última real: {self.fmt(l)}\n🏠 Sala: {r.get('name','no configurada')}\n🔗 {r.get('link','')}"+("\n⚠️ Esperando hora real." if self.store.d["waiting"] else "")
    def help(self):
        return "👻 GHOST WAVE\n!ghost estado\n!ghost iniciar HH:MM [min]\n!ghost parar\n!ghost reanudar\n!ghost hora HH:MM\n!ghost intervalo 75\n!ghost sala agregar nombre link\n!ghost sala principal nombre\n!ghost salas\n!ghost admin @usuario\n!ghost radmin @usuario\n!ghost suscribir @usuario\n!ghost quitar-suscripcion @usuario\n!ghost usuarios"
    async def command(self,u,msg):
        if not msg.lower().startswith("!ghost"):
            if self.admin(u) and self.store.d["waiting"]:
                x=self.clock(msg)
                if x: await self.actual(x); return f"✅ Registrada {x:%H:%M}.\n{self.status()}"
            return None
        p=msg.split(); a=p[1:]; c=a[0].lower() if a else "ayuda"
        if c in ("ayuda","help"):return self.help()
        if c=="estado":return self.status()
        if c=="salas":return self.room_list()
        if c=="iniciar":
            if not self.admin(u):return "🔒 Sin permiso."
            if len(a)<2:return "Uso: !ghost iniciar HH:MM [min]"
            x=self.clock(a[1])
            if not x:return "🕐 Hora inválida."
            if not self.store.d["room"]:return "🏠 Primero configura una sala principal."
            iv=int(a[2]) if len(a)>2 and a[2].isdigit() else self.store.d["interval"]
            if iv<=0:return "⏱️ Intervalo inválido."
            self.store.d.update(enabled=True,interval=iv,next=x.isoformat(),last=None,waiting=False,alerted=False);self.store.save()
            return f"🟢 Iniciado. Próxima {x:%H:%M}; aviso {(x-timedelta(minutes=5)):%H:%M}; intervalo {iv} min."
        if c in ("parar","detener","pausar"):
            if not self.admin(u):return "🔒 Sin permiso."
            self.store.d.update(enabled=False,waiting=False,alerted=False);self.store.save();return "⏸️ Anuncios detenidos. Al volver debes configurar una nueva hora."
        if c in ("reanudar","activar"):
            if not self.admin(u):return "🔒 Sin permiso."
            self.store.d.update(enabled=False,next=None,waiting=False,alerted=False);self.store.save();return "▶️ Listo. Configura de nuevo con !ghost iniciar HH:MM 75."
        if c=="hora":
            if not self.admin(u) or len(a)!=2:return "🔒 Sin permiso o uso: !ghost hora HH:MM"
            x=self.clock(a[1])
            if not x:return "🕐 Hora inválida."
            await self.actual(x);return f"✅ Hora real {x:%H:%M}.\n{self.status()}"
        if c=="intervalo":
            if not self.admin(u) or len(a)!=2 or not a[1].isdigit() or int(a[1])<=0:return "Uso: !ghost intervalo 75"
            self.store.d["interval"]=int(a[1]);self.store.save();return f"⏱️ Intervalo: {a[1]} min."
        if c=="admin" or c=="radmin" or c=="suscribir" or c=="quitar-suscripcion":
            if not self.owner(u):return "🔒 Solo el propietario puede administrar accesos."
            if len(a)!=2:return "Uso: !ghost admin|radmin|suscribir|quitar-suscripcion @usuario"
            x=await self.find(a[1])
            if not x:return "🔎 Usuario no encontrado."
            uid,name=x; self.store.d["names"][uid]=name
            if c=="admin":self.store.d["admins"]=sorted(set(self.store.d["admins"]+[uid]));out=f"🔐 @{name} puede configurar el bot."
            elif c=="radmin":self.store.d["admins"]=[i for i in self.store.d["admins"] if i!=uid];out=f"🔓 @{name} perdió el acceso de configuración."
            elif c=="suscribir":self.store.d["subs"]=sorted(set(self.store.d["subs"]+[uid]));out=f"📨 @{name} recibirá los avisos por buzón."
            else:self.store.d["subs"]=[i for i in self.store.d["subs"] if i!=uid];out=f"🔕 @{name} ya no recibirá avisos."
            self.store.save();return out
        if c=="usuarios":
            if not self.admin(u):return "🔒 Sin permiso."
            n=self.store.d["names"];return "👥 ACCESOS\n🔐 Admins:\n"+"\n".join("@"+n.get(i,i) for i in self.store.d["admins"])+"\n📨 Suscritos:\n"+"\n".join("@"+n.get(i,i) for i in self.store.d["subs"])
        if c=="sala":
            if not self.admin(u):return "🔒 Sin permiso."
            if len(a)<2:return self.room_list()
            act=a[1].lower()
            if act in ("agregar","editar") and len(a)>=4:
                name=a[2];link=a[3];rid=self.room_id(link)
                if not rid:return "🔗 Link de sala inválido."
                self.store.d["rooms"][name]={"name":name,"link":link,"room_id":rid,"enabled":True}
                self.store.d["room"]=self.store.d["room"] or name;self.store.save();return f"🏠 Sala {name} guardada."
            if act=="principal" and len(a)==3:
                if a[2] not in self.store.d["rooms"]:return "🔎 Sala no encontrada."
                self.store.d["room"]=a[2];self.store.save();return f"⭐ Sala principal: {a[2]}"
            if act in ("borrar","eliminar") and len(a)==3:
                if a[2] not in self.store.d["rooms"]:return "🔎 Sala no encontrada."
                del self.store.d["rooms"][a[2]]
                if self.store.d["room"]==a[2]:self.store.d["room"]=next(iter(self.store.d["rooms"]),None)
                self.store.save();return "🗑️ Sala eliminada."
            return "🏠 Uso: !ghost sala agregar nombre link | principal nombre | borrar nombre"
        return "❓ Usa !ghost ayuda."
    def room_list(self):
        if not self.store.d["rooms"]:return "🏠 No hay salas."
        return "\n".join(("⭐ " if k==self.store.d["room"] else "• ")+k+"\n  "+v["link"] for k,v in self.store.d["rooms"].items())
    async def actual(self,x):
        nxt=x+timedelta(minutes=int(self.store.d["interval"]))
        self.store.d.update(last=x.isoformat(),next=nxt.isoformat(),enabled=True,waiting=False,alerted=False);self.store.save()
        await self.broadcast([self.owner_id]+self.store.d["admins"],f"✅ Oleada real: {x:%H:%M}\n👻 Próxima: {nxt:%H:%M}\n🔔 Aviso: {(nxt-timedelta(minutes=5)):%H:%M}")
    async def invite(self,u,r):
        cid=self.store.d["conversations"].get(u)
        if cid and r.get("room_id"):
            try: await self.highrise.send_message(cid,f"👻 Invitación: {r['name']}","invite",r["room_id"])
            except Exception as e:print("[GHOST] invite:",e)
    async def scheduler(self):
        while True:
            try:
                if not self.store.d["enabled"] or self.store.d["waiting"]:await asyncio.sleep(3);continue
                x=self.iso(self.store.d["next"])
                if not x:await asyncio.sleep(3);continue
                now=self.now(); r=self.store.d["rooms"].get(self.store.d["room"],{})
                if not self.store.d["alerted"] and now>=x-timedelta(minutes=5):
                    msg=f"👻 OLEADA EN 5 MINUTOS\n⏰ {x:%H:%M}\n🏠 {r.get('name','Sala')}\n🔗 {r.get('link','')}"
                    await self.broadcast(self.store.d["subs"]+[self.owner_id],msg)
                    for u in self.store.d["subs"]+[self.owner_id]:await self.invite(u,r)
                    self.store.d["alerted"]=True;self.store.save()
                if now>=x:
                    await self.broadcast([self.owner_id]+self.store.d["admins"],f"👻 ¡HORA DE CONFIRMAR! Estaba prevista {x:%H:%M}. ¿A qué hora se activó realmente? Responde HH:MM.")
                    self.store.d["waiting"]=True;self.store.save()
                await asyncio.sleep(2)
            except asyncio.CancelledError:raise
            except Exception as e:print("[GHOST] scheduler:",e);await asyncio.sleep(5)
    async def on_start(self,meta:SessionMetadata):
        self.bot_id=meta.user_id;self.owner_id=meta.room_info.owner_id
        if self.owner_id not in self.store.d["subs"]:self.store.d["subs"].append(self.owner_id)
        self.store.save();self.task=asyncio.create_task(self.scheduler())
        print(f"[GHOST] conectado bot={self.bot_id} owner={self.owner_id} tz={self.tz.key}")
    async def on_message(self,user_id,conversation_id,is_new_conversation):
        try:
            self.store.d["conversations"][user_id]=conversation_id;self.store.save()
            c=await self.highrise.get_messages(conversation_id)
            if not c.messages:return
            response=await self.command(user_id,c.messages[0].content.strip())
            if response:await self.highrise.send_message(conversation_id,response)
        except Exception as e:print("[GHOST] message:",e)
    async def on_chat(self,user,message):return

async def main():
    rid=os.getenv("GHOST_WAVE_ROOM_ID","").strip();key=os.getenv("GHOST_WAVE_API_KEY","").strip()
    if not rid or not key:raise RuntimeError("Faltan GHOST_WAVE_ROOM_ID/GHOST_WAVE_API_KEY")
    await highrise_main([BotDefinition(Bot(),rid,key)])

if __name__=="__main__":asyncio.run(main())
