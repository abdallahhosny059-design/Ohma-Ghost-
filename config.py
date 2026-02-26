import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
    if not DISCORD_TOKEN:
        raise ValueError("❌ DISCORD_TOKEN غير موجود في ملف .env")
    
    # Owner ID يتم تحديده تلقائيًا عند تشغيل البوت
    OWNER_ID = None

    # ===== متغيرات إضافية للبوت =====
    COMMAND_COOLDOWN = 3          # عدد الثواني بين الأوامر العادية
    ADMIN_COOLDOWN = 2            # عدد الثواني بين أوامر الأدمن
    MAX_PRICE = 10000             # أقصى سعر مسموح به للفصل

config = Config()
