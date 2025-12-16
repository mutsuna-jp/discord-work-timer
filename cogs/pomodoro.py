import discord
from discord.ext import commands, tasks
from datetime import datetime
import logging
from config import Config
from utils import speak_in_vc

logger = logging.getLogger(__name__)

class PomodoroCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.last_triggered_minute = -1
        self.pomodoro_task.start()

    def cog_unload(self):
        self.pomodoro_task.cancel()

    @tasks.loop(seconds=1.0)
    async def pomodoro_task(self):
        now = datetime.now()
        current_minute = now.minute

        # すでにこの分で実行済みならスキップ
        if current_minute == self.last_triggered_minute:
            return

        # 秒が0になるのを待つ必要はないが、あまりにズレて実行されるのを防ぐため
        # 0秒付近（例えば0~5秒）で実行されるようにするか、
        # あるいは「分が変わった瞬間」に即時実行する（今のロジックなら即時実行される）
        
        self.last_triggered_minute = current_minute

        channel_id = Config.POMODORO_CHANNEL_ID
        if not channel_id:
            return

        # スケジュール確認
        # 作業開始: 毎時 00分, 30分
        if current_minute == 0 or current_minute == 30:
            await self.announce(channel_id, "start")
        
        # 休憩開始: 毎時 25分, 55分
        elif current_minute == 25 or current_minute == 55:
            await self.announce(channel_id, "break")

    async def announce(self, channel_id, type):
        try:
            channel = self.bot.get_channel(channel_id)
            if not channel:
                try:
                    channel = await self.bot.fetch_channel(channel_id)
                except Exception as e:
                    logger.error(f"ポモドーロ用チャンネル(ID:{channel_id})の取得に失敗: {e}")
                    return
            
            # ボイスチャンネルか確認
            if not isinstance(channel, discord.VoiceChannel):
                logger.warning(f"指定されたチャンネル(ID:{channel_id})はボイスチャンネルではありません。")
                return

            # メンバーがいるか確認 (Botは除外)
            non_bot_members = [m for m in channel.members if not m.bot]
            if not non_bot_members:
                # 誰もいない場合はアナウンスしない
                return

            if type == "start":
                text = "作業の時間です。25分間集中しましょう。"
                logger.info("ポモドーロ: 作業開始アナウンスを実行します")
            elif type == "break":
                text = "25分経過しました。5分間休憩しましょう。"
                logger.info("ポモドーロ: 休憩アナウンスを実行します")
            else:
                return

            # 音声再生 ("pomodoro"という固定IDを使用)
            await speak_in_vc(channel, text, "pomodoro")

        except Exception as e:
            logger.error(f"ポモドーロアナウンス中にエラーが発生: {e}")

async def setup(bot):
    await bot.add_cog(PomodoroCog(bot))
