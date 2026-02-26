import os
from dotenv import load_dotenv
import discord

load_dotenv()

class Config:
    DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
    if not DISCORD_TOKEN:
        raise ValueError("❌ DISCORD_TOKEN غير موجود في ملف .env")
    
    OWNER_ID = int(os.getenv("OWNER_ID", "0"))
    if OWNER_ID == 0:
        raise ValueError("❌ OWNER_ID غير موجود في ملف .env")
    
    # ✅ إضافة GUILD_ID للتزامن السريع للأوامر
    GUILD_ID = os.getenv("GUILD_ID")
    GUILD_OBJ = None
    if GUILD_ID:
        try:
            GUILD_OBJ = discord.Object(id=int(GUILD_ID))
        except:
            pass

config = Config()
