import discord
from discord.ext import commands
from datetime import datetime
from utils import format_duration, speak_in_vc, delete_previous_message
from messages import MESSAGES

class StudyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.voice_state_log = {}

    def is_active(self, voice_state):
        """ユーザーが実際にVCで活動中か判定"""
        return voice_state.channel is not None and not voice_state.self_deaf

    @commands.Cog.listener()
    async def on_ready(self):
        await self.recover_voice_sessions()

    async def recover_voice_sessions(self):
        """ボット再起動時にVCセッションを復旧"""
        print("現在のVC状態を確認中...")
        recovered_count = 0
        
        for guild in self.bot.guilds:
            for vc in guild.voice_channels:
                for member in vc.members:
                    if not member.bot and self.is_active(member.voice):
                        if member.id not in self.voice_state_log:
                            self.voice_state_log[member.id] = datetime.now()
                            recovered_count += 1
                            print(f"復旧: {member.display_name} さんの計測を再開しました")
        
        if recovered_count > 0:
            print(f"合計 {recovered_count} 名の作業セッションを復旧しました。")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """ボイスチャネルの状態変更を監視"""
        if member.bot:
            return

        log_channel_id = getattr(self.bot, 'LOG_CHANNEL_ID', 0)
        text_channel = self.bot.get_channel(log_channel_id)
        
        was_active = self.is_active(before)
        is_active_now = self.is_active(after)

        # 1. 作業開始
        if not was_active and is_active_now:
            await self.handle_voice_join(member, before, after, text_channel)

        # 2. 作業終了
        elif was_active and not is_active_now:
            await self.handle_voice_leave(member, after, text_channel)

    async def handle_voice_join(self, member, before, after, text_channel):
        """ユーザーがVCに参加した場合の処理"""
        # DBから以前のメッセージ状態を取得
        state = self.bot.db.get_message_state(member.id)
        # state is (join_msg_id, leave_msg_id) or None
        prev_leave_msg_id = state[1] if state else None

        if text_channel:
            await delete_previous_message(text_channel, prev_leave_msg_id)

        self.voice_state_log[member.id] = datetime.now()
        today_sec = self.bot.db.get_today_seconds(member.id)
        time_str_text = format_duration(today_sec, for_voice=False)
        time_str_speak = format_duration(today_sec, for_voice=True)

        msg_type = "join" if before.channel is None else "resume"
        
        if text_channel:
            embed = discord.Embed(
                title=MESSAGES[msg_type]["embed_title"],
                color=MESSAGES[msg_type]["embed_color"]
            )
            embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
            embed.add_field(
                name=MESSAGES[msg_type]["fields"][0]["name"],
                value=MESSAGES[msg_type]["fields"][0]["value"].format(current_total=time_str_text),
                inline=False
            )
            join_msg = await text_channel.send(embed=embed)
            # DB更新: join_msg_idを設定、leave_msg_idは削除(None)
            self.bot.db.set_message_state(member.id, join_msg.id, None)

        if msg_type == "join":
            speak_text = MESSAGES["join"]["message"].format(name=member.display_name, current_total=time_str_speak)
            self.bot.loop.create_task(speak_in_vc(after.channel, speak_text, member.id))

    async def handle_voice_leave(self, member, after, text_channel):
        """ユーザーがVCを離れた場合の処理"""
        # DBから以前のメッセージ状態を取得
        state = self.bot.db.get_message_state(member.id)
        prev_join_msg_id = state[0] if state else None

        if text_channel:
            await delete_previous_message(text_channel, prev_join_msg_id)

        if member.id in self.voice_state_log:
            join_time = self.voice_state_log[member.id]
            leave_time = datetime.now()
            duration = leave_time - join_time
            total_seconds = int(duration.total_seconds())

            self.bot.db.add_study_log(
                member.id, 
                member.display_name, 
                join_time, 
                total_seconds, 
                leave_time
            )
            
            del self.voice_state_log[member.id]
        else:
            total_seconds = 0

        current_str = format_duration(total_seconds, for_voice=False)
        today_sec = self.bot.db.get_today_seconds(member.id)
        total_str = format_duration(today_sec, for_voice=False)
        
        msg_type = "leave" if after.channel is None else "break"

        if text_channel:
            embed = discord.Embed(
                title=MESSAGES[msg_type]["embed_title"],
                color=MESSAGES[msg_type]["embed_color"]
            )
            embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
            
            embed.add_field(
                name=MESSAGES[msg_type]["fields"][0]["name"],
                value=MESSAGES[msg_type]["fields"][0]["value"].format(time=current_str),
                inline=False
            )
            embed.add_field(
                name=MESSAGES[msg_type]["fields"][1]["name"],
                value=MESSAGES[msg_type]["fields"][1]["value"].format(total=total_str),
                inline=False
            )
            
            leave_msg = await text_channel.send(embed=embed)
            # DB更新: join_msg_idは削除(None)、leave_msg_idを設定
            self.bot.db.set_message_state(member.id, None, leave_msg.id)

async def setup(bot):
    await bot.add_cog(StudyCog(bot))
