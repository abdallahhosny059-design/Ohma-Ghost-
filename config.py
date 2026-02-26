import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
    if not DISCORD_TOKEN:
        raise ValueError("❌ DISCORD_TOKEN غير موجود في ملف .env")
    
    # Owner ID يتم تحديده تلقائيًا عند تشغيل البوت
    OWNER_ID = None

config = Config()
