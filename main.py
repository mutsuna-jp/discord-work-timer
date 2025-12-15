import discord
from discord.ext import commands
import os
import asyncio
from dotenv import load_dotenv
from database import Database

# .env ファイルをロード (ローカル開発用)
load_dotenv()

# 環境変数
TOKEN = os.getenv('DISCORD_BOT_TOKEN')
LOG_CHANNEL_ID = int(os.getenv('LOG_CHANNEL_ID', 0))
SUMMARY_CHANNEL_ID = int(os.getenv('SUMMARY_CHANNEL_ID', 0))
BACKUP_CHANNEL_ID = int(os.getenv('BACKUP_CHANNEL_ID', 0))

# 定数
DB_PATH = "/data/study_log.db"
KEEP_LOG_DAYS = 30 
DAILY_REPORT_HOUR = 23
DAILY_REPORT_MINUTE = 59

class WorkTimerBot(commands.Bot):
    def __init__(self):
        # インテント設定
        intents = discord.Intents.default()
        intents.voice_states = True
        intents.message_content = True
        
        # デフォルトのhelpコマンドを無効化
        super().__init__(command_prefix='!', intents=intents, help_command=None)
        
        # データベース管理
        self.db = Database(DB_PATH)
        
        # 設定の保持
        self.LOG_CHANNEL_ID = LOG_CHANNEL_ID
        self.SUMMARY_CHANNEL_ID = SUMMARY_CHANNEL_ID
        self.BACKUP_CHANNEL_ID = BACKUP_CHANNEL_ID
        self.DAILY_REPORT_HOUR = DAILY_REPORT_HOUR
        self.DAILY_REPORT_MINUTE = DAILY_REPORT_MINUTE
        self.KEEP_LOG_DAYS = KEEP_LOG_DAYS

    async def setup_hook(self):
        """起動時の初期化処理"""
        await self.db.setup()
        
        # Extension(Cog)の読み込み
        initial_extensions = [
            'cogs.study',
            'cogs.report',
            'cogs.timer_cog',
            'cogs.admin'
        ]
        
        for extension in initial_extensions:
            try:
                await self.load_extension(extension)
                print(f'Loaded extension: {extension}')
            except Exception as e:
                print(f'Failed to load extension {extension}: {e}')
        
        # コマンドツリーの同期
        # 注意: グローバル同期は反映に時間がかかる場合があります (最大1時間)
        # 環境変数 GUILD_ID が設定されている場合は、特定のギルドのみ即時同期します
        guild_id = os.getenv('GUILD_ID')
        try:
            if guild_id:
                guild = discord.Object(id=int(guild_id))
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                print(f'Synced {len(synced)} command(s) to guild {guild_id}.')
                
                # 重複回避のため、グローバルコマンドを削除する
                # これにより、開発環境で予測変換が2重に出るのを防ぎます
                self.tree.clear_commands(guild=None)
                await self.tree.sync()
                print('Cleared global commands to prevent duplicates.')
            else:
                synced = await self.tree.sync()
                print(f'Synced {len(synced)} command(s) globally.')
        except Exception as e:
            print(f'Failed to sync commands: {e}')

    async def on_ready(self):
        print(f'ログインしました: {self.user}')
        
        # 1. ステータスの変更（「作業時間を記録中」と表示され、稼働中か一目でわかります）
        await self.change_presence(activity=discord.Game(name="作業時間を記録中"))

        # 2. 起動完了通知
        channel = self.get_channel(self.LOG_CHANNEL_ID)
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
            channel_id = self.LOG_CHANNEL_ID
            channel = self.get_channel(channel_id)
            
            # キャッシュにない場合はAPIから取得を試みる
            if not channel and channel_id:
                try:
                    channel = await self.fetch_channel(channel_id)
                except Exception as e:
                    print(f"チャンネル情報取得エラー (ID: {channel_id}): {e}")

            if channel:
                embed = discord.Embed(
                    title="⚠️ システム再起動",
                    description="メンテナンスのため再起動を行います。\n**完了通知が出るまでの間、記録は停止します。**",
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
    if not TOKEN:
        print("エラー: DISCORD_BOT_TOKEN 環境変数が設定されていません。")
    else:
        bot = WorkTimerBot()
        print("🚀 Botプロセスを開始します...")
        try:
            bot.run(TOKEN)
        except KeyboardInterrupt:
            print("🛑 KeyboardInterruptを受信しました。終了します。")
        except SystemExit:
            print("🛑 SystemExitを受信しました。終了します。")
        except Exception as e:
            print(f"🛑 実行中にエラーが発生しました: {e}")
        finally:
            print("🏁 プロセスが完全に終了しました。")
