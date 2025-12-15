import sqlite3
import os
from datetime import datetime

class Database:
    def __init__(self, db_path):
        self.db_path = db_path

    def get_connection(self):
        return sqlite3.connect(self.db_path)

    def execute(self, query, params=None, fetch_one=False, fetch_all=False):
        try:
            with self.get_connection() as conn:
                c = conn.cursor()
                if params:
                    c.execute(query, params)
                else:
                    c.execute(query)
                
                if fetch_one:
                    return c.fetchone()
                elif fetch_all:
                    return c.fetchall()
                else:
                    conn.commit()
                    return None
        except Exception as e:
            print(f"データベースエラー: {e}")
            return None

    def setup(self):
        """データベーステーブルとインデックスの初期化"""
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS study_logs
                         (user_id INTEGER, username TEXT, start_time TEXT, duration_seconds INTEGER, created_at TEXT)''')
            c.execute('''CREATE TABLE IF NOT EXISTS daily_summary
                         (user_id INTEGER, username TEXT, date TEXT, total_seconds INTEGER, PRIMARY KEY(user_id, date))''')
            c.execute('''CREATE TABLE IF NOT EXISTS personal_timers
                         (user_id INTEGER, end_time TEXT, minutes INTEGER)''')
            
            c.execute('''CREATE INDEX IF NOT EXISTS idx_study_logs_user_created 
                         ON study_logs(user_id, created_at)''')
            c.execute('''CREATE INDEX IF NOT EXISTS idx_study_logs_created 
                         ON study_logs(created_at)''')
            c.execute('''CREATE INDEX IF NOT EXISTS idx_personal_timers_end_time 
                         ON personal_timers(end_time)''')
            c.execute('''CREATE INDEX IF NOT EXISTS idx_daily_summary_date 
                         ON daily_summary(date)''')
            conn.commit()

    def get_today_seconds(self, user_id):
        """ユーザーの本日の作業時間を取得"""
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_str = today_start.isoformat()
        
        result = self.execute(
            '''SELECT SUM(duration_seconds) FROM study_logs WHERE user_id = ? AND created_at >= ?''',
            (user_id, today_str),
            fetch_one=True
        )
        return result[0] if result and result[0] else 0
