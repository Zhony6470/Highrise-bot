from __future__ import annotations
from typing import Literal
from highrise import User
from services.storage import load_json,save_json
Role=Literal["owner","mod","vip","designer","user"]
class RoleManager:
    """Roles persistidos por ID estable de Highrise; usernames solo sirven para migración."""
    def __init__(self,roles_file): self.roles_file=roles_file; self.roles={}; self._legacy_vip_users=set(); self._load_roles()
    async def get_user_role(self,bot,user:User)->Role:
        if user.id==bot.owner_id:return "owner"
        saved=self.roles.get(user.id) or self.roles.get(user.username.casefold())
        if saved and user.id not in self.roles and user.username.casefold() in self.roles:
            self.roles[user.id]=saved; self.roles.pop(user.username.casefold(),None); self._save_roles()
        if saved in {"mod","vip","designer"}:return saved
        try:p=await bot.highrise.get_room_privilege(user.id)
        except Exception as e: print(f"[ROLES] privilegios @{user.username}: {e}"); p=None
        if p and getattr(p,"moderator",False):return "mod"
        if p and getattr(p,"designer",False):return "designer"
        if user.id in self._legacy_vip_users or saved=="vip":return "vip"
        return "user"
    async def set_role(self,bot,user_id,role:Role,username=""):
        if not user_id:return
        if role=="user":self.roles.pop(user_id,None)
        else:self.roles[user_id]=role
        self._save_roles()
        p=await bot.highrise.get_room_privilege(user_id); p.moderator=role=="mod"; p.designer=role=="designer"; await bot.highrise.set_room_privilege(user_id,p)
    async def apply_saved_role(self,bot,user):
        role=self.roles.get(user.id)
        if role in {"mod","vip","designer"}: await self.set_role(bot,user.id,role,user.username)
    def _load_roles(self):
        data=load_json(self.roles_file,default={})
        if not isinstance(data,dict):data={}
        self._legacy_vip_users=set(data.get("vip_users",[]))
        raw=data.get("users",{})
        if isinstance(raw,dict):
            for key,role in raw.items():
                if role in {"mod","vip","designer","user"}:self.roles[str(key)]=role
    def _save_roles(self):
        data=load_json(self.roles_file,default={}); data=data if isinstance(data,dict) else {}; data["users"]=self.roles; save_json(self.roles_file,data)
async def get_user_role(bot,user):return await bot.role_manager.get_user_role(bot,user)
async def has_role(bot,user,allowed_roles):return await get_user_role(bot,user) in allowed_roles
