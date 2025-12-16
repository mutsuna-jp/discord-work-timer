import aiosqlite
import os
import logging
from datetime import datetime
from typing import Optional, List, Any, Tuple, Union

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def get_connection(self):
        return aiosqlite.connect(self.db_path)

    async def execute_script(self, script: str) -> None:
        """複数のSQLを一括実行（VACUUMなどに使用）"""
        try:
            async with self.get_connection() as db:
                await db.executescript(script)
                await db.commit()
        except Exception as e:
            logger.error(f"データベーススクリプト実行エラー: {e}")

    async def execute(self, query: str, params: Optional[Tuple] = None, fetch_one: bool = False, fetch_all: bool = False) -> Union[None, Tuple, List[Tuple], int]:
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
            logger.error(f"データベースエラー: {e} | Query: {query} | Params: {params}")
            if fetch_all:
                return []
            return None

    async def setup(self) -> None:
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
            await db.execute('''CREATE TABLE IF NOT EXISTS user_tasks
                         (user_id INTEGER PRIMARY KEY, task_content TEXT)''')
            
            await db.execute('''CREATE INDEX IF NOT EXISTS idx_study_logs_user_created 
                         ON study_logs(user_id, created_at)''')
            await db.execute('''CREATE INDEX IF NOT EXISTS idx_study_logs_created 
                         ON study_logs(created_at)''')
            await db.execute('''CREATE INDEX IF NOT EXISTS idx_personal_timers_end_time 
                         ON personal_timers(end_time)''')
            await db.execute('''CREATE INDEX IF NOT EXISTS idx_daily_summary_date 
                         ON daily_summary(date)''')
            await db.commit()

    async def get_today_seconds(self, user_id: int) -> int:
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

    async def get_total_seconds(self, user_id: int) -> int:
        """ユーザーの累計作業時間を取得"""
        result = await self.execute(
            '''SELECT SUM(duration_seconds) FROM study_logs WHERE user_id = ?''',
            (user_id,),
            fetch_one=True
        )
        return result[0] if result and result[0] else 0

    async def get_message_state(self, user_id: int) -> Optional[Tuple[int, int]]:
        """ユーザーのメッセージ状態を取得 (join_msg_id, leave_msg_id)"""
        return await self.execute(
            '''SELECT join_msg_id, leave_msg_id FROM study_message_states WHERE user_id = ?''',
            (user_id,),
            fetch_one=True
        )

    async def set_message_state(self, user_id: int, join_msg_id: Optional[int], leave_msg_id: Optional[int]) -> None:
        """ユーザーのメッセージ状態を保存 (INSERT OR REPLACE)"""
        await self.execute(
            '''INSERT OR REPLACE INTO study_message_states (user_id, join_msg_id, leave_msg_id) VALUES (?, ?, ?)''',
            (user_id, join_msg_id, leave_msg_id)
        )

    async def add_study_log(self, user_id: int, username: str, join_time: datetime, duration_seconds: int, leave_time: datetime) -> None:
        """学習ログを追加"""
        await self.execute(
            "INSERT INTO study_logs VALUES (?, ?, ?, ?, ?)",
            (user_id, username, join_time.isoformat(), duration_seconds, leave_time.isoformat())
        )

    async def get_user_task(self, user_id: int) -> Optional[str]:
        """ユーザーの現在取組中のタスクを取得"""
        result = await self.execute(
            '''SELECT task_content FROM user_tasks WHERE user_id = ?''',
            (user_id,),
            fetch_one=True
        )
        return result[0] if result else None

    async def set_user_task(self, user_id: int, task_content: str) -> None:
        """ユーザーのタスクを設定"""
        await self.execute(
            '''INSERT OR REPLACE INTO user_tasks (user_id, task_content) VALUES (?, ?)''',
            (user_id, task_content)
        )
