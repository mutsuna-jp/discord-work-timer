import aiosqlite
import os
import logging
from datetime import datetime
from typing import Optional, List, Any, Tuple, Union
from datetime import datetime, timedelta, date

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
            await db.execute('''CREATE TABLE IF NOT EXISTS user_readings
                         (user_id INTEGER PRIMARY KEY, reading TEXT)''')
            
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

    async def get_all_active_users_with_state(self) -> List[Tuple[int, int]]:
        """パネルが出っぱなし（入室中扱い）になっているユーザーとMSG_IDを取得"""
        return await self.execute(
            "SELECT user_id, join_msg_id FROM study_message_states WHERE join_msg_id IS NOT NULL",
            fetch_all=True
        )

    async def get_last_session_duration_if_recent(self, user_id: int, threshold_seconds: int = 300) -> int:
        """
        直近のログを取得し、その終了時間が現在から threshold_seconds 以内であれば、
        そのログの継続時間（秒）を返す。そうでなければ0を返す。
        Bot再起動時のセッション継続時間復元に使用。
        """
        # 最新のログ1件を取得
        query = '''
            SELECT end_time, duration_seconds 
            FROM study_logs 
            WHERE user_id = ? 
            ORDER BY created_at DESC 
            LIMIT 1
        '''
        result = await self.execute(query, (user_id,), fetch_one=True)
        
        if not result:
            return 0
            
        end_time_str, duration = result
        try:
            end_time = datetime.fromisoformat(end_time_str)
            now = datetime.now()
            
            # 経過時間をチェック
            diff = (now - end_time).total_seconds()
            
            if 0 <= diff <= threshold_seconds:
                return duration
        except Exception as e:
            logger.error(f"日時変換エラー: {e}")
            
        return 0

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

    async def get_user_reading(self, user_id: int) -> Optional[str]:
        """ユーザーの読み方を取得"""
        result = await self.execute(
            '''SELECT reading FROM user_readings WHERE user_id = ?''',
            (user_id,),
            fetch_one=True
        )
        return result[0] if result else None

    async def set_user_reading(self, user_id: int, reading: str) -> None:
        """ユーザーの読み方を設定"""
        await self.execute(
            '''INSERT OR REPLACE INTO user_readings (user_id, reading) VALUES (?, ?)''',
            (user_id, reading)
        )

    async def get_weekly_ranking(self, start_date: str) -> List[Tuple[str, int]]:
        """週間ランキングデータを取得"""
        return await self.execute(
            '''SELECT username, SUM(duration_seconds) as total_time
               FROM study_logs
               WHERE created_at >= ?
               GROUP BY user_id
               ORDER BY total_time DESC
               LIMIT 10''',
            (start_date,),
            fetch_all=True
        )

    async def get_first_log_date(self, user_id: int) -> Optional[str]:
        """ユーザーの最初のログ日時を取得"""
        result = await self.execute(
            '''SELECT MIN(created_at) FROM study_logs WHERE user_id = ?''',
            (user_id,),
            fetch_one=True
        )
        return result[0] if result else None

    async def get_study_logs_in_range(self, start_date: str, end_date: Optional[str] = None) -> List[Tuple[int, str, int]]:
        """指定期間の学習ログを集計して取得 (user_id, username, total_time)"""
        if end_date:
            query = '''SELECT user_id, username, SUM(duration_seconds) as total_time 
                       FROM study_logs 
                       WHERE created_at >= ? AND created_at < ?
                       GROUP BY user_id 
                       ORDER BY total_time DESC'''
            params = (start_date, end_date)
        else:
            query = '''SELECT user_id, username, SUM(duration_seconds) as total_time 
                       FROM study_logs 
                       WHERE created_at >= ? 
                       GROUP BY user_id 
                       ORDER BY total_time DESC'''
            params = (start_date,)
            
        return await self.execute(query, params, fetch_all=True)

    async def save_daily_summary(self, user_id: int, username: str, date_str: str, total_seconds: int) -> None:
        """日次サマリーを保存"""
        await self.execute(
            '''INSERT OR REPLACE INTO daily_summary (user_id, username, date, total_seconds) 
               VALUES (?, ?, ?, ?)''',
            (user_id, username, date_str, total_seconds)
        )

    async def cleanup_old_data(self, log_threshold: str, summary_threshold: str) -> Tuple[int, int]:
        """古いデータを削除 (戻り値: logs_deleted, summary_deleted)"""
        # 古いログを削除
        logs_deleted = await self.execute("DELETE FROM study_logs WHERE created_at < ?", (log_threshold,))
        if logs_deleted is None: logs_deleted = 0
            
        # 古いDaily Summaryデータを削除
        summary_deleted = await self.execute("DELETE FROM daily_summary WHERE date < ?", (summary_threshold,))
        if summary_deleted is None: summary_deleted = 0
            
        # VACUUM
        await self.execute_script("VACUUM")
        
        return logs_deleted, summary_deleted

    async def add_personal_timer(self, user_id: int, end_time_str: str, minutes: int) -> None:
        """個人タイマーを追加"""
        await self.execute(
            "INSERT INTO personal_timers VALUES (?, ?, ?)",
            (user_id, end_time_str, minutes)
        )

    async def get_and_delete_expired_timers(self, now_str: str) -> List[Tuple[int, int, int]]:
        """期限切れタイマーを取得し、取得したものは同時に削除する (rowid, user_id, minutes)"""
        # まず取得して、IDリストで削除する
        expired = await self.execute(
            "SELECT rowid, user_id, minutes FROM personal_timers WHERE end_time <= ?",
            (now_str,),
            fetch_all=True
        )
        
        if expired:
            for rowid, _, _ in expired:
                await self.execute("DELETE FROM personal_timers WHERE rowid = ?", (rowid,))
                
                
        return expired if expired else []

    async def get_user_streak(self, user_id: int) -> int:
        """ユーザーの連続ログイン日数を取得"""
        # 過去のログから一意の日付を取得 (降順)
        # substr(created_at, 1, 10) で 'YYYY-MM-DD' を抽出
        query = '''
            SELECT DISTINCT substr(created_at, 1, 10) as day 
            FROM study_logs 
            WHERE user_id = ? 
            ORDER BY day DESC
        '''
        rows = await self.execute(query, (user_id,), fetch_all=True)
        
        if not rows:
            return 1 # 初回は1日目

        # 文字列を日付オブジェクトに変換
        dates = []
        for row in rows:
            try:
                d = datetime.strptime(row[0], "%Y-%m-%d").date()
                dates.append(d)
            except ValueError:
                continue
        
        if not dates:
            return 1

        today = datetime.now().date()
        streak = 0
        current_check = today
        
        # 最新のログが今日かどうか確認
        if dates[0] == today:
            streak = 1
            start_idx = 1
            current_check = today - timedelta(days=1)
        else:
            # 今日はまだログがないが、今入室したので1日目としてカウント開始
            streak = 1 
            start_idx = 0
            current_check = today - timedelta(days=1)
            
        # 過去に遡って連続性をチェック
        for i in range(start_idx, len(dates)):
            if dates[i] == current_check:
                streak += 1
                current_check -= timedelta(days=1)
            else:
                break
                
        return streak
