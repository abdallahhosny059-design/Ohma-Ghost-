import discord
from discord.ext import commands
from discord import app_commands
import logging
from database import db
from config import config

logger = logging.getLogger(__name__)

def is_owner():
    async def predicate(interaction: discord.Interaction):
        if interaction.user.id == config.OWNER_ID:
            return True
        await interaction.response.send_message("❌ هذا الأمر للأونر فقط", ephemeral=True)
        return False
    return app_commands.check(predicate)

class OwnerCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name="حذف_السجلات", description="حذف جميع السجلات (الأونر فقط)")
    @is_owner()
    async def delete_logs(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await db.delete_all_logs(interaction.user.id)
        await interaction.followup.send("✅ تم حذف جميع السجلات (ما عدا المالية)", ephemeral=True)
    
    @app_commands.command(name="حالة_البوت", description="حالة البوت (الأونر فقط)")
    @is_owner()
    async def bot_status(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        embed = discord.Embed(title="🤖 حالة البوت", color=discord.Color.green())
        embed.add_field(name="⏰ وقت التشغيل", value="شغال", inline=True)
        embed.add_field(name="👤 الأونر", value=f"<@{config.OWNER_ID}>" if config.OWNER_ID else "لم يحدد", inline=True)
        
        # استخدام استعلامات SQLite الصحيحة
        try:
            async with db.conn.execute("SELECT COUNT(*) FROM users") as cursor:
                users_count = (await cursor.fetchone())[0]
            async with db.conn.execute("SELECT COUNT(*) FROM works WHERE is_active = 1") as cursor:
                works_count = (await cursor.fetchone())[0]
            async with db.conn.execute("SELECT COUNT(*) FROM tasks") as cursor:
                tasks_count = (await cursor.fetchone())[0]
            async with db.conn.execute("SELECT COUNT(*) FROM chapters") as cursor:
                chapters_count = (await cursor.fetchone())[0]
            async with db.conn.execute("SELECT COUNT(*) FROM logs") as cursor:
                logs_count = (await cursor.fetchone())[0]
        except Exception as e:
            logger.error(f"Error getting counts: {e}")
            users_count = works_count = tasks_count = chapters_count = logs_count = 0
        
        embed.add_field(name="👥 الأعضاء", value=users_count, inline=True)
        embed.add_field(name="📚 الأعمال", value=works_count, inline=True)
        embed.add_field(name="📋 المهام", value=tasks_count, inline=True)
        embed.add_field(name="✅ الفصول", value=chapters_count, inline=True)
        embed.add_field(name="📝 السجلات", value=logs_count, inline=True)
        
        await interaction.followup.send(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(OwnerCog(bot))
