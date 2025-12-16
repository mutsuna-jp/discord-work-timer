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
                    logger.warning(f"ステータスボード更新: チャンネルが見つかりません: {channel_id}")
                    return

            # 権限チェック
            permissions = channel.permissions_for(channel.guild.me)
            if not permissions.view_channel:
                logger.warning(f"ステータスボード更新: チャンネル {channel.id} を閲覧する権限がありません。")
                return
            if not permissions.send_messages:
                logger.warning(f"ステータスボード更新: チャンネル {channel.id} にメッセージを送信する権限がありません。")
                return
            if not permissions.read_message_history:
                logger.warning(f"ステータスボード更新: チャンネル {channel.id} のメッセージ履歴を読む権限がありません（重複防止のために必要です）。")
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
                    del active_users[user_id]
                    logger.info(f"ステータスボード更新: 不正な状態のユーザーID {user_id} を削除しました。")

            # Botの過去のメッセージを検索 (Limitを増やして対応)
            my_messages = []
            try:
                # 新しい順に取得される
                async for message in channel.history(limit=50):
                    if message.author == self.bot.user:
                        my_messages.append(message)
            except Exception as e:
                logger.error(f"メッセージ履歴の取得に失敗: {e}")
                return

            # 新しい順 -> 古い順 に並べ替え（上から順に表示するため）
            my_messages.reverse()

            if not active_users:
                # 作業中のユーザーがいない場合 -> 全てのBotメッセージを削除
                for msg in my_messages:
                    try:
                        await msg.delete()
                    except Exception as e:
                        logger.error(f"メッセージ削除失敗: {e}")
                return 

            # --- Embed作成処理 (複数メッセージページネーション対応) ---
            all_embeds = []
            
            # 1. ヘッダー用Embed
            header_embed = discord.Embed(
                title="📊 現在の作業状況", 
                description=f"現在の作業人数: **{len(active_users)}** 名",
                timestamp=datetime.now(),
                color=0x00FF00
            )
            all_embeds.append(header_embed)
            
            # 2. ユーザーごとのEmbed作成
            # 入室順（開始時間が早い順）にソート
            sorted_users = sorted(active_users.items(), key=lambda item: item[1])

            for user_id, start_time in sorted_users:
                member = channel.guild.get_member(user_id)
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
                
                user_embed = discord.Embed(
                    description=f" {task} ({time_str})",
                    color=0x00FF00
                )
                user_embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
                all_embeds.append(user_embed)

            # 3. チャンク分け (1メッセージにつきEmbed10個まで)
            chunk_size = 10
            embed_chunks = [all_embeds[i:i + chunk_size] for i in range(0, len(all_embeds), chunk_size)]

            # 4. 既存メッセージとの同期 (更新、新規送信、削除)
            max_len = max(len(embed_chunks), len(my_messages))

            for i in range(max_len):
                # A. 更新または新規送信が必要な場合
                if i < len(embed_chunks):
                    chunk = embed_chunks[i]
                    
                    if i < len(my_messages):
                        # 既存メッセージを更新
                        try:
                            await my_messages[i].edit(embeds=chunk)
                        except discord.Forbidden:
                            logger.error(f"ステータスボード更新削除エラー: 権限不足 (Channel ID: {channel.id})")
                        except Exception as e:
                            logger.error(f"ステータスボード更新失敗: {e}")
                    else:
                        # 新規メッセージを送信
                        try:
                            await channel.send(embeds=chunk)
                        except discord.Forbidden:
                            logger.error(f"ステータスボード送信エラー: 権限不足 (Channel ID: {channel.id})")
                        except Exception as e:
                            logger.error(f"ステータスボード送信失敗: {e}")
                
                # B. 不要なメッセージの削除
                else:
                    msg_to_delete = my_messages[i]
                    try:
                        await msg_to_delete.delete()
                    except Exception as e:
                        logger.error(f"余剰メッセージ削除失敗: {e}")

async def setup(bot):
    await bot.add_cog(StatusCog(bot))
