import discord
from discord.ext import commands
from discord import app_commands
import logging
from database import db
from config import config

logger = logging.getLogger(__name__)

def is_owner():
    async def predicate(interaction: discord.Interaction):
        owner_id = await db.get_owner()
        if owner_id is None:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "⚠️ لم يتم تعيين الأونر بعد. استخدم /set_owner لتعيينه.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "⚠️ لم يتم تعيين الأونر بعد. استخدم /set_owner لتعيينه.",
                    ephemeral=True
                )
            return False
        if interaction.user.id == owner_id:
            return True
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ هذا الأمر للأونر فقط", ephemeral=True)
        else:
            await interaction.followup.send("❌ هذا الأمر للأونر فقط", ephemeral=True)
        return False
    return app_commands.check(predicate)

class OwnerCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="set_owner", description="تعيين نفسك كأونر للبوت (مرة واحدة فقط)")
    async def set_owner(self, interaction: discord.Interaction):
        existing_owner = await db.get_owner()
        if existing_owner is not None:
            await interaction.response.send_message("❌ الأونر محدد مسبقاً ولا يمكن تغييره.", ephemeral=True)
            return

        success = await db.set_owner(interaction.user.id)
        if success:
            await interaction.response.send_message(
                f"✅ تم تعيينك كأونر للبوت! (ID: {interaction.user.id})",
                ephemeral=True
            )
            logger.info(f"👑 Owner set to {interaction.user.name} (ID: {interaction.user.id}) via command.")
        else:
            await interaction.response.send_message("❌ حدث خطأ أثناء تعيين الأونر.", ephemeral=True)

    @is_owner()
    @app_commands.command(name="اضافة_ادمن", description="إضافة عضو كأدمن في البوت (الأونر فقط)")
    @app_commands.describe(member="العضو المراد إضافته")
    async def add_admin(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer(ephemeral=True)
        success = await db.add_admin(str(member.id), interaction.user.id)
        if success:
            await interaction.followup.send(f"✅ تمت إضافة {member.mention} كأدمن في البوت.", ephemeral=True)
        else:
            await interaction.followup.send(f"⚠️ {member.mention} هو بالفعل أدمن.", ephemeral=True)

    @is_owner()
    @app_commands.command(name="ازالة_ادمن", description="إزالة عضو من قائمة الأدمن (الأونر فقط)")
    @app_commands.describe(member="العضو المراد إزالته")
    async def remove_admin(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer(ephemeral=True)
        success = await db.remove_admin(str(member.id))
        if success:
            await interaction.followup.send(f"✅ تمت إزالة {member.mention} من قائمة الأدمن.", ephemeral=True)
        else:
            await interaction.followup.send(f"⚠️ {member.mention} ليس أدمن في البوت.", ephemeral=True)

    @is_owner()
    @app_commands.command(name="قائمة_الادمن", description="عرض قائمة الأدمن في البوت")
    async def list_admins(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        admins = await db.get_admins()
        if not admins:
            await interaction.followup.send("📭 لا يوجد أدمن حالياً.", ephemeral=True)
            return

        embed = discord.Embed(title="👥 قائمة الأدمن", color=discord.Color.blue())
        for admin in admins:
            user = self.bot.get_user(int(admin["user_id"]))
            name = user.name if user else f"Unknown ({admin['user_id']})"
            embed.add_field(name=name, value=f"منذ: {admin['added_at']}", inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @is_owner()
    @app_commands.command(name="حذف_السجلات", description="حذف جميع السجلات (الأونر فقط)")
    async def delete_logs(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await db.delete_all_logs(interaction.user.id)
        await interaction.followup.send("✅ تم حذف جميع السجلات (ما عدا المالية)", ephemeral=True)

    @is_owner()
    @app_commands.command(name="حالة_البوت", description="عرض حالة البوت (الأونر فقط)")
    async def status_command(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        owner_id = await db.get_owner()
        embed = discord.Embed(title="🤖 حالة البوت", color=discord.Color.green())
        embed.add_field(name="⏰ وقت التشغيل", value="شغال", inline=True)
        embed.add_field(name="👤 الأونر", value=f"<@{owner_id}>" if owner_id else "لم يحدد", inline=True)

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
