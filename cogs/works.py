import discord
from discord.ext import commands
from discord import app_commands
import logging
from database import db

logger = logging.getLogger(__name__)

def is_admin():
    async def predicate(interaction: discord.Interaction):
        try:
            if await db.is_admin(str(interaction.user.id)):
                return True
        except Exception as e:
            logger.error(f"Error checking admin in DB: {e}")
        if interaction.user.guild_permissions.administrator:
            return True

        if not interaction.response.is_done():
            await interaction.response.send_message(
                "❌ هذا الأمر يتطلب صلاحية أدمن في البوت أو في السيرفر",
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                "❌ هذا الأمر يتطلب صلاحية أدمن في البوت أو في السيرفر",
                ephemeral=True
            )
        return False
    return app_commands.check(predicate)

class WorksCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="اضافة_عمل", description="إضافة عمل جديد (أدمن فقط)")
    @app_commands.describe(name="اسم العمل", link="رابط الدرايف")
    @is_admin()
    async def add_work(self, interaction: discord.Interaction, name: str, link: str):
        await interaction.response.defer(ephemeral=True)

        try:
            success, message = await db.add_work(name.strip(), link.strip(), interaction.user.id)
            embed = discord.Embed(
                title="✅ تمت الإضافة" if success else "❌ فشل",
                description=message,
                color=discord.Color.green() if success else discord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            logger.error(f"Error in add_work: {e}")
            await interaction.followup.send("❌ حدث خطأ غير متوقع أثناء إضافة العمل.", ephemeral=True)

    @app_commands.command(name="بحث", description="البحث عن عمل")
    @app_commands.describe(name="اسم العمل")
    async def search_work(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer(ephemeral=True)

        try:
            work = await db.get_work(name.strip())
            if work:
                embed = discord.Embed(
                    title=f"📚 {work['name']}",
                    description=work['link'],
                    color=discord.Color.blue()
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                results = await db.search_works(name.strip())
                if results:
                    embed = discord.Embed(
                        title="🔍 نتائج البحث",
                        description="اختر من الأعمال التالية:",
                        color=discord.Color.orange()
                    )
                    for w in results:
                        embed.add_field(name=w['name'], value=w['link'], inline=False)
                    await interaction.followup.send(embed=embed, ephemeral=True)
                else:
                    await interaction.followup.send(f"❌ العمل **{name}** غير موجود", ephemeral=True)
        except Exception as e:
            logger.error(f"Error in search_work: {e}")
            await interaction.followup.send("❌ حدث خطأ أثناء البحث.", ephemeral=True)

    @app_commands.command(name="حذف_عمل", description="حذف عمل (أدمن فقط)")
    @app_commands.describe(name="اسم العمل")
    @is_admin()
    async def delete_work(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer(ephemeral=True)

        try:
            success, message = await db.delete_work(name.strip(), interaction.user.id)
            await interaction.followup.send(message, ephemeral=True)
        except Exception as e:
            logger.error(f"Error in delete_work: {e}")
            await interaction.followup.send("❌ حدث خطأ أثناء الحذف.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(WorksCog(bot))
