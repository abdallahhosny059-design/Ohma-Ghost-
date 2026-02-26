import discord
from discord.ext import commands
from discord import app_commands
import logging
from database import db
from config import config

logger = logging.getLogger(__name__)

class EarningsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="انجازاتي", description="عرض إنجازاتي")
    @app_commands.checks.cooldown(1, config.COMMAND_COOLDOWN, key=lambda i: i.user.id)
    async def my_achievements(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        stats = await db.get_user_stats(str(interaction.user.id))
        display_name = stats.get("display_name") or interaction.user.display_name

        embed = discord.Embed(
            title=f"📋 إنجازات {display_name}",
            color=discord.Color.green()
        )

        embed.add_field(name="💰 الإجمالي", value=f"${stats['total_earned']}", inline=True)
        embed.add_field(name="📚 عدد الفصول", value=stats['chapters_count'], inline=True)
        embed.add_field(name="⏳ مهام pending", value=stats['pending_tasks'], inline=True)
        embed.add_field(name="✅ مهام مسلمة", value=stats['submitted_tasks'], inline=True)

        if stats['recent_chapters']:
            recent = "\n".join([
                f"• {c['work']} فصل {c['chapter']} (${c['price']})"
                for c in stats['recent_chapters'][:5]
            ])
            embed.add_field(name="🆕 آخر الإنجازات", value=recent, inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="راتبي", description="عرض راتبي")
    @app_commands.checks.cooldown(1, config.COMMAND_COOLDOWN, key=lambda i: i.user.id)
    async def my_salary(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        stats = await db.get_user_stats(str(interaction.user.id))
        display_name = stats.get("display_name") or interaction.user.display_name

        embed = discord.Embed(
            title=f"💰 راتب {display_name}",
            color=discord.Color.gold()
        )
        embed.add_field(name="الإجمالي", value=f"${stats['total_earned']}", inline=True)
        embed.add_field(name="عدد الفصول", value=stats['chapters_count'], inline=True)

        await interaction.followup.send(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(EarningsCog(bot))
