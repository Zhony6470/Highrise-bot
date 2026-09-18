import json, os, random, subprocess, time, threading
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

HOST=os.getenv("AUTODJ_HOST","0.0.0.0"); PORT=int(os.getenv("AUTODJ_PORT","8090"))
TOKEN=os.getenv("AUTODJ_TOKEN","")
ICECAST_HOST=os.getenv("ICECAST_HOST","icecast"); ICECAST_PORT=int(os.getenv("ICECAST_PORT","8000"))
ICECAST_SOURCE=os.getenv("ICECAST_SOURCE","source"); ICECAST_PASSWORD=os.getenv("ICECAST_PASSWORD","")
ICECAST_MOUNT=os.getenv("ICECAST_MOUNT","stream").strip("/")
CACHE=Path(os.getenv("AUTODJ_CACHE_DIR","/data/cache")); DEFAULT=Path(os.getenv("AUTODJ_DEFAULT_DIR","/data/default_music"))
QUEUE_FILE=Path(os.getenv("AUTODJ_QUEUE_FILE","/data/request_queue.json")); PLAYLIST=Path(os.getenv("AUTODJ_PLAYLIST_FILE","/data/default_playlist.json"))
COOKIES=os.getenv("YOUTUBE_COOKIES_PATH","/app/cookies.txt")
SR=44100; CH=2; BLOCK=4096*4
queue=deque(); lock=threading.RLock(); skip=threading.Event(); state={"current":None,"started_at":None}

def load(p,d):
    try:return json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError,OSError,ValueError):return d
def save(p,v):
    p.parent.mkdir(parents=True,exist_ok=True); t=p.with_suffix(p.suffix+".tmp"); t.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding="utf-8"); t.replace(p)
def key(x):return x.get("video_id") or x.get("file_path")
def meta(x):return x.get("metadata") or {"title":x.get("title","Pista desconocida"),"channel":x.get("channel","Highrise Radio"),"duration":x.get("duration")}
def auth(h):return not TOKEN or h.headers.get("Authorization","")==f"Bearer {TOKEN}"

def ensure_file(item):
    if item.get("file_path") and Path(item["file_path"]).exists(): return Path(item["file_path"])
    vid=item.get("video_id")
    if not vid: raise RuntimeError("Pista sin video_id")
    CACHE.mkdir(parents=True,exist_ok=True)
    matches=list(CACHE.glob(vid+".*"))
    if matches:return matches[0]
    cmd=["yt-dlp","--no-playlist","--no-part","-f","bestaudio/best","--extractor-args","youtube:player_client=ios,android,web_embedded","-o",str(CACHE/"%(id)s.%(ext)s")]
    if Path(COOKIES).exists():cmd+=["--cookies",COOKIES]
    subprocess.run(cmd+[f"https://www.youtube.com/watch?v={vid}"],check=True,timeout=180)
    matches=list(CACHE.glob(vid+".*"))
    if not matches:raise RuntimeError("yt-dlp no generó el archivo")
    return matches[0]

class Output:
    def __init__(self):self.p=None
    def connect(self):
        if self.p and self.p.poll() is None:return
        url=f"icecast://{quote(ICECAST_SOURCE,safe='')}:{quote(ICECAST_PASSWORD,safe='')}@{ICECAST_HOST}:{ICECAST_PORT}/{quote(ICECAST_MOUNT,safe='/')}"
        cmd=["ffmpeg","-hide_banner","-loglevel","warning","-f","s16le","-ar",str(SR),"-ac","2","-i","pipe:0","-c:a","libmp3lame","-b:a","128k","-ar",str(SR),"-ac","2","-content_type","audio/mpeg","-f","mp3",url]
        self.p=subprocess.Popen(cmd,stdin=subprocess.PIPE)
        print("[AUTODJ] salida Icecast conectada",flush=True)
    def write(self,b):
        while True:
            try:
                self.connect(); self.p.stdin.write(b); self.p.stdin.flush(); return
            except (BrokenPipeError,OSError):
                self.close(); time.sleep(1)
    def close(self):
        p=self.p; self.p=None
        if not p:return
        try:p.stdin.close()
        except Exception:pass
        try:p.terminate();p.wait(timeout=2)
        except Exception:
            try:p.kill()
            except Exception:pass

def decoder(path):
    return subprocess.Popen(["ffmpeg","-hide_banner","-loglevel","error","-i",str(path),"-f","s16le","-ar",str(SR),"-ac","2","pipe:1"],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)

def default_next():
    pl=load(PLAYLIST,[])
    items=[dict(x) for x in pl if isinstance(x,dict) and x.get("video_id")]
    if not items:
        items=[{"file_path":str(p),"metadata":{"title":p.stem,"channel":"Highrise Radio"}} for p in DEFAULT.glob("*") if p.is_file()]
    if not items:return None
    return random.choice(items)

def next_item():
    with lock:
        if queue:
            x=queue.popleft();save(QUEUE_FILE,list(queue));return x
    x=default_next()
    if x:x["default_track"]=True
    return x

def player():
    out=Output()
    while True:
        item=None
        try:
            item=next_item()
            if not item:time.sleep(1);continue
            item=dict(item);item["file_path"]=str(ensure_file(item));item["metadata"]=meta(item)
            with lock:state["current"]=item;state["started_at"]=time.time()
            print("[AUTODJ] "+item["metadata"].get("title","Pista"),flush=True)
            p=decoder(item["file_path"])
            try:
                while not skip.is_set():
                    b=p.stdout.read(BLOCK)
                    if not b:break
                    out.write(b)
            finally:
                try:p.stdout.close()
                except Exception:pass
                try:p.wait(timeout=2)
                except Exception:
                    try:p.kill()
                    except Exception:pass
            skip.clear()
            with lock:state["current"]=None
        except Exception as e:
            print("[AUTODJ] error:",e,flush=True);skip.clear();time.sleep(1)

class API(BaseHTTPRequestHandler):
    def reply(self,c,v):
        b=json.dumps(v,ensure_ascii=False).encode();self.send_response(c);self.send_header("Content-Type","application/json");self.send_header("Content-Length",str(len(b)));self.end_headers();self.wfile.write(b)
    def body(self):
        n=int(self.headers.get("Content-Length","0"));return json.loads(self.rfile.read(n) or b"{}")
    def do_GET(self):
        if not auth(self):return self.reply(401,{"error":"unauthorized"})
        if self.path=="/health":return self.reply(200,{"ok":True})
        if self.path=="/status":
            with lock:q=list(queue);s=dict(state)
            s["elapsed"]=time.time()-s["started_at"] if s["started_at"] else 0;s["queue"]=q;return self.reply(200,s)
        if self.path=="/queue":return self.reply(200,list(queue))
        if self.path=="/default-playlist":return self.reply(200,load(PLAYLIST,[]))
        return self.reply(404,{"error":"not_found"})
    def do_POST(self):
        if not auth(self):return self.reply(401,{"error":"unauthorized"})
        try:
            d=self.body()
            if self.path=="/play":
                with lock:queue.append({"video_id":d["video_id"],"metadata":d.get("metadata",{}),"requested_track":True});save(QUEUE_FILE,list(queue))
                return self.reply(200,{"ok":True})
            if self.path=="/skip":skip.set();return self.reply(200,{"ok":True})
            if self.path in ("/default-add","/default-remove"):
                pl=load(PLAYLIST,[]);vid=d["video_id"]
                if self.path.endswith("add"):
                    if any(x.get("video_id")==vid for x in pl):return self.reply(409,{"error":"already_exists"})
                    pl.append({"video_id":vid,"metadata":d.get("metadata",{})})
                else:
                    old=len(pl);pl=[x for x in pl if x.get("video_id")!=vid]
                    if old==len(pl):return self.reply(404,{"error":"not_found"})
                save(PLAYLIST,pl);return self.reply(200,{"ok":True,"playlist":pl})
            return self.reply(404,{"error":"not_found"})
        except Exception as e:return self.reply(400,{"error":str(e)})
    def log_message(self,*a):pass

if __name__=="__main__":
    CACHE.mkdir(parents=True,exist_ok=True);DEFAULT.mkdir(parents=True,exist_ok=True)
    queue.extend(load(QUEUE_FILE,[]));threading.Thread(target=player,daemon=True).start()
    ThreadingHTTPServer((HOST,PORT),API).serve_forever()
