import discord
from discord.ext import commands
import os
import signal
import sys
import logging
from config import Config
from database import Database

logger = logging.getLogger("main")

class WorkTimerBot(commands.Bot):
    def __init__(self):
        # インテント設定
        intents = discord.Intents.default()
        intents.voice_states = True
        intents.message_content = True
        
        # デフォルトのhelpコマンドを無効化
        super().__init__(command_prefix='!', intents=intents, help_command=None)
        
        # データベース管理
        self.db = Database(Config.DB_PATH)
        
        # 設定の保持 (互換性のため、またはアクセスしやすくするため)
        # 必要な場合は Config クラスを直接参照しても良い
        self.config = Config

    async def setup_hook(self):
        """起動時の初期化処理"""
        await self.db.setup()
        
        # Extension(Cog)の読み込み
        initial_extensions = [
            'cogs.study',
            'cogs.report',
            'cogs.timer_cog',
            'cogs.admin',
            'cogs.status'
        ]
        
        for extension in initial_extensions:
            try:
                await self.load_extension(extension)
                logger.info(f'Loaded extension: {extension}')
            except Exception as e:
                logger.error(f'Failed to load extension {extension}: {e}')
        
        # コマンドツリーの同期
        guild_id = Config.GUILD_ID
        try:
            if guild_id:
                guild = discord.Object(id=int(guild_id))
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                print(f'Synced {len(synced)} command(s) to guild {guild_id}.')
                
                # 重複回避のため、グローバルコマンドを削除する
                self.tree.clear_commands(guild=None)
                await self.tree.sync()
                print('Cleared global commands to prevent duplicates.')
            else:
                synced = await self.tree.sync()
                print(f'Synced {len(synced)} command(s) globally.')
        except Exception as e:
            logger.error(f'Failed to sync commands: {e}')

    async def on_ready(self):
        logger.info(f'ログインしました: {self.user}')
        
        # 1. ステータスの変更
        await self.change_presence(activity=discord.Game(name="作業時間を記録中"))

        # 2. 起動完了通知
        channel = self.get_channel(Config.LOG_CHANNEL_ID)
        if channel:
            embed = discord.Embed(
                title="✅ システム起動完了",
                description="再起動が完了しました。\nコマンドおよび入退室の記録機能が利用可能です。",
                color=0x00FF00 # 緑色
            )
            await channel.send(embed=embed)

    async def close(self):
        """Bot停止時に実行される処理"""
        print("Botの停止処理を開始します...")
        try:
            # 終了通知
            channel_id = Config.LOG_CHANNEL_ID
            channel = self.get_channel(channel_id)
            
            # キャッシュにない場合はAPIから取得を試みる
            if not channel and channel_id:
                try:
                    channel = await self.fetch_channel(channel_id)
                except Exception as e:
                    print(f"チャンネル情報取得エラー (ID: {channel_id}): {e}")

            if channel:
                embed = discord.Embed(
                    title="⚠️ システム停止",
                    description="メンテナンスのため一時的にシステムを停止します。\n**再起動するまでの間、記録は停止します。**",
                    color=0xFF0000 # 赤色
                )
                await channel.send(embed=embed)
                print("終了通知を送信しました。")
            else:
                print(f"通知先のチャンネルが見つかりません (ID: {channel_id})")
                
        except Exception as e:
            print(f"終了通知送信エラー: {e}")
        
        # 本来の終了処理を実行
        await super().close()

if __name__ == '__main__':
    if not Config.TOKEN:
        print("エラー: DISCORD_BOT_TOKEN 環境変数が設定されていません。")
    else:
        bot = WorkTimerBot()

        # ▼▼▼ 追加: 停止シグナルを強制的にキャッチする処理 ▼▼▼
        def force_close(signum, frame):
            print(f"🛑 停止シグナル ({signum}) を受信しました。終了処理を強制実行します。")
            # KeyboardInterruptを発生させることで、下の except ブロックに飛ばし、
            # discord.py の終了処理フローに乗せます。
            raise KeyboardInterrupt

        # SIGTERM (Docker停止コマンド) をキャッチするように登録
        signal.signal(signal.SIGTERM, force_close)
        # ▲▲▲ 追加終了 ▲▲▲

        print("🚀 Botプロセスを開始します...")
        try:
            bot.run(Config.TOKEN)
        except KeyboardInterrupt:
            print("🛑 KeyboardInterruptを受信しました。終了処理へ移行します。")
            # bot.run() は KeyboardInterrupt で抜けると自動的に cleanup を行いますが、
            # 念のためここで明示的な close は不要です（二重実行になるため）
        except SystemExit:
            print("🛑 SystemExitを受信しました。終了します。")
        except Exception as e:
            logger.critical(f"🛑 実行中にエラーが発生しました: {e}")
        finally:
            logger.info("🏁 プロセスが完全に終了しました。")
