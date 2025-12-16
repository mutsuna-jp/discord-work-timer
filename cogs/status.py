import discord
from discord.ext import commands, tasks
from datetime import datetime
from config import Config
import logging
import asyncio

logger = logging.getLogger(__name__)

class StatusCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.update_lock = asyncio.Lock()
        self.update_status_loop.start()

    def cog_unload(self):
        self.update_status_loop.cancel()

    @tasks.loop(minutes=5)
    async def update_status_loop(self):
        await self.update_status_board()

    @update_status_loop.before_loop
    async def before_update_status_loop(self):
        await self.bot.wait_until_ready()

    async def update_status_board(self):
        """ステータスボードを更新する"""
        # ロックを取得して、同時実行を防ぐ
        async with self.update_lock:
            channel_id = Config.STATUS_CHANNEL_ID
            if not channel_id:
                return

            channel = self.bot.get_channel(channel_id)
            if not channel:
                # キャッシュにない場合は取得を試みる
                try:
                    channel = await self.bot.fetch_channel(channel_id)
                except Exception:
                    logger.warning(f"ステータスチャンネルが見つかりません: {channel_id}")
                    return

            study_cog = self.bot.get_cog("StudyCog")
            if not study_cog:
                return
                
            active_users = study_cog.voice_state_log
            
            # 1. ゾンビユーザー（すでにいないユーザー）のチェックとクリーンアップ
            # 辞書をコピーして反復処理
            for user_id in list(active_users.keys()):
                member = channel.guild.get_member(user_id)
                
                # ユーザーが見つからない、またはボイスチャンネルにいない場合
                if not member or not member.voice or not member.voice.channel:
                    # ログから削除
                    del active_users[user_id]
                    logger.info(f"ステータスボード更新: 不正な状態のユーザーID {user_id} を削除しました。")

            # 2. メッセージの更新または削除
            # Botの過去のメッセージを検索
            my_messages = []
            try:
                async for message in channel.history(limit=20):
                    if message.author == self.bot.user:
                        my_messages.append(message)
            except Exception as e:
                logger.error(f"メッセージ履歴の取得に失敗: {e}")

            if not active_users:
                # 作業中のユーザーがいない場合 -> 全てのBotメッセージを削除
                if my_messages:
                    for msg in my_messages:
                        try:
                            await msg.delete()
                        except Exception as e:
                            logger.error(f"メッセージ削除失敗: {e}")
                return # Embed作成処理はスキップ

            # 以下、作業者がいる場合のEmbed作成
            embed = discord.Embed(title="📊 現在の作業状況", timestamp=datetime.now())
            embed.color = 0x00FF00 # 緑
            count = 0
            
            for user_id, start_time in active_users.items():
                member = channel.guild.get_member(user_id)
                # 上のチェックを通っているので member は存在するはずだが念の為
                if not member:
                     try:
                        member = await channel.guild.fetch_member(user_id)
                     except:
                        continue

                # タスクを取得
                task = await self.bot.db.get_user_task(user_id) or "作業"
                
                # 経過時間を計算
                now = datetime.now()
                duration = now - start_time
                total_seconds = int(duration.total_seconds())
                
                hours = total_seconds // 3600
                minutes = (total_seconds % 3600) // 60
                
                if hours > 0:
                    time_str = f"{hours}時間{minutes}分"
                else:
                    time_str = f"{minutes}分"
                
                embed.add_field(
                    name=f"👤 {member.display_name}",
                    value=f"📝 **{task}**\n⏱️ 接 続: {time_str}",
                    inline=False
                )
                count += 1
            
            embed.set_footer(text=f"現在 {count} 名が作業中")

            # メッセージの管理: 最新の1つだけ残し、他は削除
            target_message = None
            
            if my_messages:
                target_message = my_messages[0] # historyは新しい順なので先頭が最新
                
                # 2つ目以降（古いメッセージ）は削除
                if len(my_messages) > 1:
                    for msg in my_messages[1:]:
                        try:
                            await msg.delete()
                        except Exception as e:
                            logger.error(f"重複メッセージ削除失敗: {e}")
            
            try:
                if target_message:
                    await target_message.edit(embed=embed)
                else:
                    await channel.send(embed=embed)
            except Exception as e:
                logger.error(f"ステータスボードの更新に失敗しました: {e}")

async def setup(bot):
    await bot.add_cog(StatusCog(bot))
