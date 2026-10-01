async def is_owner_or_mod(bot,user_id:str)->bool:
    return user_id==getattr(bot,"owner_id",None) or await bot.is_mod(user_id)
