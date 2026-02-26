import discord
from discord.ext import commands
from discord import app_commands
import logging
from config import config
from database import db

logger = logging.getLogger(__name__)

class ManhwaBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True   # ضروري لاستقبال الأوامر النصية
        intents.members = True           # ضروري للتعامل مع معلومات الأعضاء
        intents.guilds = True            # ضروري لمعرفة السيرفرات

        super().__init__(
            command_prefix='!',
            intents=intents,
            help_command=None  # تعطيل أمر المساعدة الافتراضي (يمكنك تفعيله لاحقاً)
        )

    async def setup_hook(self):
        """تُستدعى عند بدء تشغيل البوت لتحميل الـ cogs ومزامنة الأوامر."""
        # تحميل جميع الـ cogs
        await self.load_extension("cogs.works")
        await self.load_extension("cogs.tasks")
        await self.load_extension("cogs.earnings")
        await self.load_extension("cogs.admin")
        await self.load_extension("cogs.owner")

        # مزامنة الأوامر مع Discord (تظهر في كل السيرفرات بعد فترة)
        await self.tree.sync()
        logger.info("✅ Synced global commands")


# إنشاء نسخة البوت
bot = ManhwaBot()


# ========== حدث التشغيل ==========
@bot.event
async def on_ready():
    """يُستدعى عندما يكون البوت جاهزاً للعمل."""
    logger.info(f'✅ Bot online as {bot.user}')

    # التحقق من وجود مالك (اختياري للعرض فقط)
    owner_id = await db.get_owner()
    if owner_id:
        logger.info(f"👑 Owner is set (ID: {owner_id})")
    else:
        logger.info("👑 No owner set. Use /set_owner to set yourself as owner.")

    # تعيين حالة البوت (what's playing)
    await bot.change_presence(
        activity=discord.Game(name="📚 إدارة فريق الترجمة"),
        status=discord.Status.online
    )


# ========== معالجة الأوامر النصية ==========
@bot.event
async def on_message(message):
    """يتم استدعاؤها لكل رسالة؛ ضروري لمعالجة الأوامر النصية."""
    if message.author.bot:
        return  # تجاهل رسائل البوتات الأخرى
    await bot.process_commands(message)


# ========== أوامر اختبار بسيطة ==========
@bot.command(name='ping')
async def ping(ctx):
    """أمر اختبار: يرجع Pong!"""
    await ctx.send('🏓 Pong!')

@bot.command(name='test')
async def test(ctx):
    """أمر اختبار: يتأكد من أن البوت يعمل."""
    await ctx.send('✅ البوت شغال!')


# ========== معالجة أخطاء الأوامر النصية ==========
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ ليس لديك صلاحية لاستخدام هذا الأمر.")
    elif isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"⏳ انتظر {error.retry_after:.1f} ثانية قبل استخدام الأمر مرة أخرى.")
    elif isinstance(error, commands.CommandNotFound):
        # تجاهل الأوامر غير الموجودة (لا تفعل شيئاً)
        pass
    else:
        logger.error(f"Unhandled command error: {error}")
        await ctx.send("❌ حدث خطأ غير متوقع.")


# ========== معالجة أخطاء أوامر السلاش (Slash Commands) ==========
@bot.event
async def on_app_command_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ ليس لديك صلاحية.", ephemeral=True)
    elif isinstance(error, app_commands.CommandOnCooldown):
        await interaction.response.send_message(
            f"⏳ انتظر {error.retry_after:.1f} ثانية.", ephemeral=True
        )
    elif isinstance(error, app_commands.CheckFailure):
        # فشل التحقق (مثل is_admin, is_owner)
        # الرسالة أُرسلت بالفعل داخل الدالة، لذلك نمرر فقط
        pass
    else:
        logger.error(f"Unhandled app command error: {error}")
        # نحاول الرد إن أمكن
        try:
            await interaction.response.send_message("❌ حدث خطأ غير متوقع.", ephemeral=True)
        except:
            pass
