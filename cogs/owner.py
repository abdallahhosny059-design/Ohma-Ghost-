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
        
        embed = discord.Embed(
            title="🤖 حالة البوت",
            color=discord.Color.green()
        )
        
        embed.add_field(name="⏰ وقت التشغيل", value="شغال", inline=True)
        embed.add_field(name="👤 الأونر", value=f"<@{config.OWNER_ID}>", inline=True)
        
        # Get counts
        users = await db.users.count_documents({})
        works = await db.works.count_documents({"is_active": True})
        tasks = await db.tasks.count_documents({})
        chapters = await db.chapters.count_documents({})
        logs = await db.logs.count_documents({})
        
        embed.add_field(name="👥 الأعضاء", value=users, inline=True)
        embed.add_field(name="📚 الأعمال", value=works, inline=True)
        embed.add_field(name="📋 المهام", value=tasks, inline=True)
        embed.add_field(name="✅ الفصول", value=chapters, inline=True)
        embed.add_field(name="📝 السجلات", value=logs, inline=True)
        
        await interaction.followup.send(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(OwnerCog(bot))