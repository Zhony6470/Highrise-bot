from __future__ import annotations
import json,os
from pathlib import Path
from threading import RLock
try:
 from supabase import Client,create_client
except ImportError: Client=None; create_client=None
SUPABASE_URL=os.environ.get("SUPABASE_URL",""); SUPABASE_KEY=os.environ.get("SUPABASE_KEY","")
_client=create_client(SUPABASE_URL,SUPABASE_KEY) if create_client and SUPABASE_URL and SUPABASE_KEY else None
_lock=RLock()
def _default_data(name,default=None):
 return {"data.json":{"users":{},"bot_position":{"x":0,"y":0,"z":0,"facing":"FrontRight"}},"posiciones.json":{"posiciones":{}},"roles.json":{"vip_users":[],"users":{}}}.get(name,default if default is not None else {})
def load_json(file_path,default=None):
 path=Path(file_path)
 if _client:
  response=_client.table("bot_files").select("file_name,content").eq("file_name",path.name).limit(1).execute()
  if response.data:return response.data[0]["content"]
  data=_default_data(path.name,default); save_json(file_path,data); return data
 try:
  with _lock,path.open(encoding="utf-8") as f:return json.load(f)
 except (FileNotFoundError,json.JSONDecodeError,OSError):return _default_data(path.name,default)
def save_json(file_path,data):
 path=Path(file_path)
 if _client:
  _client.table("bot_files").upsert({"file_name":path.name,"content":data},returning="representation").execute(); return
 path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_suffix(path.suffix+".tmp")
 with _lock,tmp.open("w",encoding="utf-8") as f: json.dump(data,f,indent=4,ensure_ascii=False); f.flush(); os.fsync(f.fileno())
 tmp.replace(path)
