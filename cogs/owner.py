import discord
from discord.ext import commands
from discord import app_commands
import logging
from database import db
from config import config

logger = logging.getLogger(__name__)

def is_owner():
    async def predicate(interaction: discord.Interaction):
        if config.OWNER_ID is None:
            await interaction.response.send_message("⚠️ لا يوجد أونر محدد. استخدم /set_owner لتعيين نفسك.", ephemeral=True)
            return False
        if interaction.user.id == config.OWNER_ID:
            return True
        await interaction.response.send_message("❌ هذا الأمر للأونر فقط", ephemeral=True)
        return False
    return app_commands.check(predicate)

class OwnerCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="set_owner", description="تعيين نفسك كأونر للبوت (لأول مرة)")
    async def set_owner(self, interaction: discord.Interaction):
        """يسمح لأول شخص يستخدم الأمر بأن يصبح الأونر"""
        if config.OWNER_ID is not None:
            await interaction.response.send_message("❌ الأونر محدد مسبقاً.", ephemeral=True)
            return
        
        config.OWNER_ID = interaction.user.id
        await interaction.response.send_message(f"✅ تم تعيينك كأونر للبوت! (ID: {config.OWNER_ID})", ephemeral=True)
        logger.info(f"👑 Owner set to {interaction.user.name} (ID: {config.OWNER_ID}) via command.")

    @app_commands.command(name="حذف_السجلات", description="حذف جميع السجلات (الأونر فقط)")
    @is_owner()
    async def delete_logs(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await db.delete_all_logs(interaction.user.id)
        await interaction.followup.send("✅ تم حذف جميع السجلات (ما عدا المالية)", ephemeral=True)

    @app_commands.command(name="حالة_البوت", description="عرض حالة البوت (الأونر فقط)")
    @is_owner()
    async def status_command(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        embed = discord.Embed(title="🤖 حالة البوت", color=discord.Color.green())
        embed.add_field(name="⏰ وقت التشغيل", value="شغال", inline=True)
        embed.add_field(name="👤 الأونر", value=f"<@{config.OWNER_ID}>" if config.OWNER_ID else "لم يحدد", inline=True)

        # إحصائيات SQLite
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
