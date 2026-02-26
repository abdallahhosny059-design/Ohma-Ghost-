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
        intents.message_content = True
        intents.members = True
        intents.guilds = True

        super().__init__(
            command_prefix='!',
            intents=intents,
            help_command=None
        )

    async def setup_hook(self):
        await self.load_extension("cogs.works")
        await self.load_extension("cogs.tasks")
        await self.load_extension("cogs.earnings")
        await self.load_extension("cogs.admin")
        await self.load_extension("cogs.owner")

        await self.tree.sync()
        logger.info("✅ Synced global commands")

bot = ManhwaBot()

@bot.event
async def on_ready():
    logger.info(f'✅ Bot online as {bot.user}')
    owner_id = await db.get_owner()
    if owner_id:
        logger.info(f"👑 Owner is set (ID: {owner_id})")
    else:
        logger.info("👑 No owner set. Use /set_owner to set yourself as owner.")
    await bot.change_presence(
        activity=discord.Game(name="📚 إدارة فريق الترجمة"),
        status=discord.Status.online
    )

@bot.command(name='ping')
async def ping(ctx):
    await ctx.send('🏓 Pong!')

@bot.command(name='test')
async def test(ctx):
    await ctx.send('✅ البوت شغال!')

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    await bot.process_commands(message)

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ ليس لديك صلاحية")
    elif isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"⏳ انتظر {error.retry_after:.1f} ثانية")
    elif isinstance(error, commands.CommandNotFound):
        pass
    else:
        logger.error(f"Command error: {error}")
        await ctx.send("❌ حدث خطأ")

@bot.event
async def on_app_command_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ ليس لديك صلاحية", ephemeral=True)
    elif isinstance(error, app_commands.CommandOnCooldown):
        await interaction.response.send_message(
            f"⏳ انتظر {error.retry_after:.1f} ثانية",
            ephemeral=True
        )
    elif isinstance(error, app_commands.CheckFailure):
        # يتم التعامل معه داخل الدالة check
        pass
    else:
        logger.error(f"Unhandled app command error: {error}")
        try:
            await interaction.response.send_message("❌ حدث خطأ غير متوقع.", ephemeral=True)
        except:
            pass
