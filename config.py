import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
    if not DISCORD_TOKEN:
        raise ValueError("❌ DISCORD_TOKEN غير موجود في ملف .env")
    
    # Owner ID (يُضبط عبر الأمر /set_owner)
    OWNER_ID = None

    # إعدادات البوت
    COMMAND_COOLDOWN = 3
    ADMIN_COOLDOWN = 2
    MAX_PRICE = 10000

config = Config()
