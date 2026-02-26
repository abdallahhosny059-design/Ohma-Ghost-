import discord
from discord.ext import commands
from discord import app_commands
import logging
from datetime import datetime, timedelta
from database import db          # 👈 استيراد db
from config import config

logger = logging.getLogger(__name__)

def is_admin():
    async def predicate(interaction: discord.Interaction):
        if await db.is_admin(str(interaction.user.id)):
            return True
        if interaction.user.guild_permissions.administrator:
            return True
        await interaction.response.send_message("❌ يحتاج صلاحية أدمن", ephemeral=True)
        return False
    return app_commands.check(predicate)

class AdminCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="تقرير_عام", description="تقرير عام للفريق (أدمن فقط)")
    @is_admin()
    async def general_report(self, interaction: discord.Interaction):
        await interaction.response.defer()
        stats = await db.get_team_stats()
        embed = discord.Embed(title="📊 تقرير الفريق", color=discord.Color.blue(), timestamp=datetime.now())
        embed.add_field(name="📚 إجمالي الفصول", value=stats['total_chapters'], inline=True)
        embed.add_field(name="💰 إجمالي الأرباح", value=f"${stats['total_earnings']}", inline=True)
        embed.add_field(name="⏳ مهام pending", value=stats['pending_tasks'], inline=True)
        embed.add_field(name="✅ مهام مسلمة", value=stats['submitted_tasks'], inline=True)
        if stats['top_users']:
            top_text = ""
            for i, user in enumerate(stats['top_users'], 1):
                top_text += f"{i}. {user['display_name']}: {user['count']} فصول (${user['total']})\n"
            embed.add_field(name="🏆 أفضل 5 أعضاء", value=top_text, inline=False)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="تقرير_اسبوعي", description="تقرير آخر 7 أيام (أدمن فقط)")
    @is_admin()
    async def weekly_report(self, interaction: discord.Interaction):
        await interaction.response.defer()
        weekly = await db.get_weekly_report()
        embed = discord.Embed(
            title="📆 تقرير الأسبوع",
            description=f"من {(datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')} إلى {datetime.now().strftime('%Y-%m-%d')}",
            color=discord.Color.purple()
        )
        if weekly:
            for item in weekly:
                embed.add_field(
                    name=item['display_name'],
                    value=f"📚 {item['chapters']} فصول | 💰 ${item['earnings']}",
                    inline=False
                )
        else:
            embed.description = "لا توجد إنجازات هذا الأسبوع"
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="تفاصيل", description="تفاصيل عضو معين (أدمن فقط)")
    @app_commands.describe(member="العضو")
    @is_admin()
    async def user_details(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer()
        stats = await db.get_user_stats(str(member.id))
        embed = discord.Embed(title=f"📋 تفاصيل {member.display_name}", color=discord.Color.orange())
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
        await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(AdminCog(bot))
