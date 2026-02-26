import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
    if not DISCORD_TOKEN:
        raise ValueError("❌ DISCORD_TOKEN غير موجود في ملف .env")
    
    # Owner ID (يتم تعيينه يدوياً عبر الأمر)
    OWNER_ID = None

    # إعدادات البوت
    COMMAND_COOLDOWN = 3          # ثواني بين الأوامر العادية
    ADMIN_COOLDOWN = 2            # ثواني بين أوامر الأدمن
    MAX_PRICE = 10000              # أقصى سعر للفصل

config = Config()
