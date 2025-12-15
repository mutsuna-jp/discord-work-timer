import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timedelta
from utils import safe_message_delete
from messages import MESSAGES

TIMER_MAX_MINUTES = 180
TIMER_CHECK_INTERVAL = 10

class TimerCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_timers_task.start()

    def cog_unload(self):
        self.check_timers_task.cancel()

    async def set_personal_timer(self, interaction: discord.Interaction, minutes: int):
        """個人タイマーを設定"""
        timer_msgs = MESSAGES.get("timer", {})

        if minutes <= 0:
            msg = timer_msgs.get("invalid", "⚠️ 時間は整数（分）で指定してください。")
            await interaction.response.send_message(msg, ephemeral=True)
            return
        
        if minutes > TIMER_MAX_MINUTES:
            msg = timer_msgs.get("too_long", "⚠️ タイマーは長すぎます。")
            await interaction.response.send_message(msg, ephemeral=True)
            return

        end_time = datetime.now() + timedelta(minutes=minutes)
        end_time_str = end_time.isoformat()
        end_time_disp = end_time.strftime('%H:%M')

        await self.bot.db.execute(
            "INSERT INTO personal_timers VALUES (?, ?, ?)",
            (interaction.user.id, end_time_str, minutes)
        )

        msg = timer_msgs.get("set", "⏰ {minutes}分後に通知します。").format(minutes=minutes, end_time=end_time_disp)
        
        # 設定完了メッセージをEphemeralで返す (通知は時間経過後にDMで届く)
        await interaction.response.send_message(f"{msg}\n(時間が来たらDMでお知らせします)", ephemeral=True)


    @app_commands.command(name="timer", description="指定した分数のタイマーを設定します")
    @app_commands.describe(minutes="設定する分数（分）")
    @app_commands.default_permissions(send_messages=True)
    async def timer(self, interaction: discord.Interaction, minutes: int):
        """タイマーコマンド"""
        await self.set_personal_timer(interaction, minutes)

    @tasks.loop(seconds=TIMER_CHECK_INTERVAL)
    async def check_timers_task(self):
        """期限切れのタイマーを確認して通知"""
        now_str = datetime.now().isoformat()
        
        expired_timers = await self.bot.db.execute(
            "SELECT rowid, user_id, minutes FROM personal_timers WHERE end_time <= ?",
            (now_str,),
            fetch_all=True
        )
        
        if not expired_timers:
            return
        
        timer_msgs = MESSAGES.get("timer", {})
        
        for rowid, user_id, minutes in expired_timers:
            try:
                user = self.bot.get_user(user_id)
                if not user:
                    try:
                        user = await self.bot.fetch_user(user_id)
                    except discord.NotFound:
                        user = None
                
                if user:
                    msg = timer_msgs.get("finish", "⏰ {minutes}分が経過しました！").format(minutes=minutes)
                    await user.send(msg)
            except Exception as e:
                print(f"タイマー通知エラー (User ID: {user_id}): {e}")
            
            await self.bot.db.execute("DELETE FROM personal_timers WHERE rowid = ?", (rowid,))

async def setup(bot):
    await bot.add_cog(TimerCog(bot))
