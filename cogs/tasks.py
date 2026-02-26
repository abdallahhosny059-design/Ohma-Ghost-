import discord
from discord.ext import commands
from discord import app_commands
import logging
from database import db
from config import config

logger = logging.getLogger(__name__)

def is_admin():
    async def predicate(interaction: discord.Interaction):
        try:
            if await db.is_admin(str(interaction.user.id)):
                return True
        except Exception as e:
            logger.error(f"Error checking admin status: {e}")
        if interaction.user.guild_permissions.administrator:
            return True
        await interaction.response.send_message("❌ هذا الأمر يتطلب صلاحية أدمن في البوت أو في السيرفر", ephemeral=True)
        return False
    return app_commands.check(predicate)

class TasksCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="تكليف", description="تكليف عضو بمهمة (أدمن فقط)")
    @app_commands.describe(member="العضو", work="اسم العمل", chapter="رقم الفصل", price="السعر بالدولار")
    @is_admin()
    @app_commands.checks.cooldown(1, config.ADMIN_COOLDOWN)
    async def assign_task(
        self, 
        interaction: discord.Interaction,
        member: discord.Member,
        work: str,
        chapter: int,
        price: int
    ):
        # التحقق من صحة المدخلات
        if price <= 0:
            await interaction.response.send_message("❌ السعر يجب أن يكون أكبر من 0", ephemeral=True)
            return
        if price > config.MAX_PRICE:
            await interaction.response.send_message(f"❌ السعر كبير جداً (الحد الأقصى {config.MAX_PRICE})", ephemeral=True)
            return
        if chapter <= 0:
            await interaction.response.send_message("❌ رقم الفصل غير صالح", ephemeral=True)
            return

        await interaction.response.defer()

        try:
            success, message = await db.create_task(
                user_id=str(member.id),
                username=member.name,
                display_name=member.display_name,
                work=work,
                chapter=chapter,
                price=price,
                assigned_by=interaction.user.id
            )

            if success:
                embed = discord.Embed(
                    title="📋 مهمة جديدة",
                    description=f"**العمل:** {work}\n**الفصل:** {chapter}\n**السعر:** ${price}",
                    color=discord.Color.green()
                )
                await interaction.followup.send(f"✅ {member.mention}", embed=embed)

                try:
                    await member.send(f"📢 مهمة جديدة: {work} فصل {chapter} بسعر ${price}")
                except:
                    pass
            else:
                await interaction.followup.send(message)
        except Exception as e:
            logger.error(f"Error in assign_task: {e}")
            await interaction.followup.send("❌ حدث خطأ غير متوقع أثناء إنشاء المهمة.")

    @app_commands.command(name="مهماتي", description="عرض مهامي")
    @app_commands.checks.cooldown(1, config.COMMAND_COOLDOWN)
    async def my_tasks(self, interaction: discord.Interaction):
        await interaction.response.defer()

        try:
            tasks = await db.get_user_tasks(str(interaction.user.id))

            if not tasks:
                await interaction.followup.send("📭 لا يوجد مهام")
                return

            embed = discord.Embed(
                title=f"📋 مهام {interaction.user.display_name}",
                color=discord.Color.blue()
            )

            pending = [t for t in tasks if t['status'] == 'pending']
            submitted = [t for t in tasks if t['status'] == 'submitted']

            if pending:
                text = "\n".join([f"• {t['work']} فصل {t['chapter']} (${t['price']})" for t in pending[:5]])
                embed.add_field(name="⏳ في الانتظار", value=text, inline=False)

            if submitted:
                text = "\n".join([f"• {t['work']} فصل {t['chapter']}" for t in submitted[:5]])
                embed.add_field(name="✅ مسلمة", value=text, inline=False)

            await interaction.followup.send(embed=embed)
        except Exception as e:
            logger.error(f"Error in my_tasks: {e}")
            await interaction.followup.send("❌ حدث خطأ أثناء جلب المهام.")

    @app_commands.command(name="تسليم", description="تسليم مهمة")
    @app_commands.describe(work="اسم العمل", chapter="رقم الفصل")
    @app_commands.checks.cooldown(1, config.COMMAND_COOLDOWN)
    async def submit_task(self, interaction: discord.Interaction, work: str, chapter: int):
        await interaction.response.defer()

        try:
            success = await db.submit_task(str(interaction.user.id), work, chapter)
            if success:
                await interaction.followup.send(f"✅ تم تسليم {work} فصل {chapter}")
            else:
                await interaction.followup.send("❌ لا توجد مهمة pending بهذه البيانات")
        except Exception as e:
            logger.error(f"Error in submit_task: {e}")
            await interaction.followup.send("❌ حدث خطأ أثناء تسليم المهمة.")

    @app_commands.command(name="اعتماد", description="اعتماد مهمة (أدمن فقط)")
    @app_commands.describe(member="العضو", work="اسم العمل", chapter="رقم الفصل")
    @is_admin()
    @app_commands.checks.cooldown(1, config.ADMIN_COOLDOWN)
    async def approve_task(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        work: str,
        chapter: int
    ):
        await interaction.response.defer()

        try:
            task = await db.approve_task(
                user_id=str(member.id),
                work=work,
                chapter=chapter,
                approved_by=interaction.user.id
            )

            if task:
                embed = discord.Embed(
                    title="✅ تم الاعتماد",
                    description=f"**{work} فصل {chapter}**\n💰 ${task['price']}",
                    color=discord.Color.green()
                )
                await interaction.followup.send(embed=embed)

                try:
                    await member.send(f"✅ تم اعتماد {work} فصل {chapter} (💰 ${task['price']})")
                except:
                    pass
            else:
                await interaction.followup.send("❌ لم يتم العثور على مهمة مسلمة بهذه البيانات")
        except Exception as e:
            logger.error(f"Error in approve_task: {e}")
            await interaction.followup.send("❌ حدث خطأ أثناء اعتماد المهمة.")

    @app_commands.command(name="رفض", description="رفض مهمة (أدمن فقط)")
    @app_commands.describe(member="العضو", work="اسم العمل", chapter="رقم الفصل", reason="السبب")
    @is_admin()
    @app_commands.checks.cooldown(1, config.ADMIN_COOLDOWN)
    async def reject_task(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        work: str,
        chapter: int,
        reason: str
    ):
        await interaction.response.defer()

        try:
            success = await db.reject_task(
                user_id=str(member.id),
                work=work,
                chapter=chapter,
                rejected_by=interaction.user.id,
                reason=reason
            )

            if success:
                await interaction.followup.send(f"❌ تم رفض {work} فصل {chapter}\nالسبب: {reason}")
                try:
                    await member.send(f"❌ تم رفض {work} فصل {chapter}\nالسبب: {reason}")
                except:
                    pass
            else:
                await interaction.followup.send("❌ لم يتم العثور على مهمة مسلمة بهذه البيانات")
        except Exception as e:
            logger.error(f"Error in reject_task: {e}")
            await interaction.followup.send("❌ حدث خطأ أثناء رفض المهمة.")

async def setup(bot):
    await bot.add_cog(TasksCog(bot))
