import aiosqlite
import os
from datetime import datetime

class Database:
    def __init__(self, db_path):
        self.db_path = db_path

    def get_connection(self):
        return aiosqlite.connect(self.db_path)

    async def execute_script(self, script):
        """複数のSQLを一括実行（VACUUMなどに使用）"""
        try:
            async with self.get_connection() as db:
                await db.executescript(script)
                await db.commit()
        except Exception as e:
            print(f"データベーススクリプト実行エラー: {e}")

    async def execute(self, query, params=None, fetch_one=False, fetch_all=False):
        try:
            async with self.get_connection() as db:
                if params:
                    cursor = await db.execute(query, params)
                else:
                    cursor = await db.execute(query)
                
                if fetch_one:
                    return await cursor.fetchone()
                elif fetch_all:
                    return await cursor.fetchall()
                else:
                    await db.commit()
                    return cursor.rowcount
        except Exception as e:
            print(f"データベースエラー: {e}")
            if fetch_all:
                return []
            return None

    async def setup(self):
        """データベーステーブルとインデックスの初期化"""
        async with self.get_connection() as db:
            await db.execute('''CREATE TABLE IF NOT EXISTS study_logs
                         (user_id INTEGER, username TEXT, start_time TEXT, duration_seconds INTEGER, created_at TEXT)''')
            await db.execute('''CREATE TABLE IF NOT EXISTS daily_summary
                         (user_id INTEGER, username TEXT, date TEXT, total_seconds INTEGER, PRIMARY KEY(user_id, date))''')
            await db.execute('''CREATE TABLE IF NOT EXISTS personal_timers
                         (user_id INTEGER, end_time TEXT, minutes INTEGER)''')
            await db.execute('''CREATE TABLE IF NOT EXISTS study_message_states
                         (user_id INTEGER PRIMARY KEY, join_msg_id INTEGER, leave_msg_id INTEGER)''')
            
            await db.execute('''CREATE INDEX IF NOT EXISTS idx_study_logs_user_created 
                         ON study_logs(user_id, created_at)''')
            await db.execute('''CREATE INDEX IF NOT EXISTS idx_study_logs_created 
                         ON study_logs(created_at)''')
            await db.execute('''CREATE INDEX IF NOT EXISTS idx_personal_timers_end_time 
                         ON personal_timers(end_time)''')
            await db.execute('''CREATE INDEX IF NOT EXISTS idx_daily_summary_date 
                         ON daily_summary(date)''')
            await db.commit()

    async def get_today_seconds(self, user_id):
        """ユーザーの本日の作業時間を取得"""
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_str = today_start.isoformat()
        
        result = await self.execute(
            '''SELECT SUM(duration_seconds) FROM study_logs WHERE user_id = ? AND created_at >= ?''',
            (user_id, today_str),
            fetch_one=True
        )
        return result[0] if result and result[0] else 0

    async def get_total_seconds(self, user_id):
        """ユーザーの累計作業時間を取得"""
        result = await self.execute(
            '''SELECT SUM(duration_seconds) FROM study_logs WHERE user_id = ?''',
            (user_id,),
            fetch_one=True
        )
        return result[0] if result and result[0] else 0

    async def get_message_state(self, user_id):
        """ユーザーのメッセージ状態を取得"""
        return await self.execute(
            '''SELECT join_msg_id, leave_msg_id FROM study_message_states WHERE user_id = ?''',
            (user_id,),
            fetch_one=True
        )

    async def set_message_state(self, user_id, join_msg_id, leave_msg_id):
        """ユーザーのメッセージ状態を保存 (INSERT OR REPLACE)"""
        await self.execute(
            '''INSERT OR REPLACE INTO study_message_states (user_id, join_msg_id, leave_msg_id) VALUES (?, ?, ?)''',
            (user_id, join_msg_id, leave_msg_id)
        )

    async def add_study_log(self, user_id, username, join_time, duration_seconds, leave_time):
        """学習ログを追加"""
        await self.execute(
            "INSERT INTO study_logs VALUES (?, ?, ?, ?, ?)",
            (user_id, username, join_time.isoformat(), duration_seconds, leave_time.isoformat())
        )
