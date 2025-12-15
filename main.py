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

if __name__ == '__main__':
    if not TOKEN:
        print("エラー: DISCORD_BOT_TOKEN 環境変数が設定されていません。")
    else:
        bot = WorkTimerBot()
        bot.run(TOKEN)
