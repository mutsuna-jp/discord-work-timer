import os
import logging
from dotenv import load_dotenv

# .env ファイルをロード (ローカル開発用)
load_dotenv()

# ロギング設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("config")

class Config:
    # Discord Bot Token
    TOKEN = os.getenv('DISCORD_BOT_TOKEN')

    # Channel IDs
    LOG_CHANNEL_ID = int(os.getenv('LOG_CHANNEL_ID', 0))
    SUMMARY_CHANNEL_ID = int(os.getenv('SUMMARY_CHANNEL_ID', 0))
    BACKUP_CHANNEL_ID = int(os.getenv('BACKUP_CHANNEL_ID', 0))
    STATUS_CHANNEL_ID = int(os.getenv('STATUS_CHANNEL_ID', 0))
    GUILD_ID = os.getenv('GUILD_ID')

    # Application Settings
    DB_PATH = "/data/study_log.db"
    KEEP_LOG_DAYS = 30 
    DAILY_REPORT_HOUR = 23
    DAILY_REPORT_MINUTE = 59

    # Milestones (Hours: Role Name)
    MILESTONES = {
        10: "🥉 10時間達成",
        50: "🥈 50時間達成",
        100: "🥇 100時間達成",
        500: "🏆 500時間達成",
        1000: "👑 レジェンド"
    }

    @classmethod
    def validate(cls):
        if not cls.TOKEN:
             logger.error("DISCORD_BOT_TOKEN 環境変数が設定されていません。")
             # raise ValueError("DISCORD_BOT_TOKEN is missing") # Optional: raise error

