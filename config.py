import os
from dotenv import load_dotenv
import discord

load_dotenv()

class Config:
    # Discord
    DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
    if not DISCORD_TOKEN:
        raise ValueError("❌ DISCORD_TOKEN غير موجود في ملف .env")
    
    # Owner
    OWNER_ID = int(os.getenv("OWNER_ID", "0"))
    if OWNER_ID == 0:
        raise ValueError("❌ OWNER_ID غير موجود في ملف .env")
    
    # Guild (for fast command sync)
    GUILD_ID = os.getenv("GUILD_ID")
    GUILD_OBJ = None
    if GUILD_ID:
        try:
            GUILD_OBJ = discord.Object(id=int(GUILD_ID))
        except:
            pass
    
    # Database
    DB_NAME = "manhwa_bot"
    
    # Rate Limits
    COMMAND_COOLDOWN = 3
    ADMIN_COOLDOWN = 2
    MAX_PRICE = 10000
    
    # Logging
    LOG_RETENTION_DAYS = 90
    LOG_RETENTION_SECONDS = 90 * 24 * 60 * 60

config = Config()
