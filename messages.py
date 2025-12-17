# メッセージ管理ファイル



class Colors:
    GREEN = 0x00FF00
    RED = 0xFF0000
    BLUE = 0x00BFFF # Deep Sky Blue
    GOLD = 0xFFD700
    PURPLE = 0x9932CC
    ORANGE = 0xFF4500
    YELLOW = 0xFFA500
    PINK = 0xFF69B4
    GRAY = 0x808080
    DARK_GRAY = 0x36393F
    NAVY = 0x000080

MESSAGES = {
    # ---------------------------
    # 👋 入室時
    # ---------------------------
    "join": {
        "message": "{name}さんが{task}を始めました。",
        "embed_title": "🚀 {task}スタート！",
        "embed_color": Colors.GREEN, # 緑色
        "fields": [
            {"name": "", "value": "{days}日継続中！"},
            {"name": "", "value": "**{current_total}**～"}
        ]
    },

    # ---------------------------
    # 🍵 退室時
    # ---------------------------
    "leave": {
        "embed_title": "🍵 お疲れ様でした",
        "embed_color": Colors.BLUE, # 水色
        "fields": [
            {"name": "今回の記録", "value": "**{time}**"},
            {"name": "本日の総記録", "value": "**{total}**"}
        ]
    },

    # ---------------------------
    # 🏆 ランキング (!rank)
    # ---------------------------
    "rank": {
        "empty_message": "今週はまだ誰も作業していません...！一番乗りを目指しましょう！🏃‍♂️",
        "embed_title": "🏆 今週の作業時間ランキング",
        "embed_desc": "",
        "embed_color": Colors.GOLD, # 金色
        "row": "{icon} **{name}**: {time}\n"
    },

    # ---------------------------
    # 📊 個人成績 (!stats)
    # ---------------------------
    "stats": {
        "embed_title": "📊 {name} さんの通算記録",
        "embed_desc": "",
        "embed_color": Colors.PURPLE, # 紫色
        "fields": [
            {"name": "⏳ 累計作業時間", "value": "**{total_time}**"},
            {"name": "📅 計測開始日", "value": "{date} ({days}日前)"}
        ]
    },

    # ---------------------------
    # 🔥 作業再開時
    # ---------------------------
    "resume": {
        "message": "{name}さん、作業再開です。",
        "embed_title": "🔥 作業再開！",
        "embed_color": Colors.ORANGE, # オレンジ色
        "fields": [{"name": "今日の記録", "value": "**{current_total}**"}]
    },

    # ---------------------------
    # ☕ 休憩時
    # ---------------------------
    "break": {
        "embed_title": "☕ 休憩中...",
        "embed_color": Colors.YELLOW, # 黄色
        "fields": []
    },

    # ---------------------------
    # 📅 日報 (23:59)
    # ---------------------------
    "report": {
        "empty_message": "今日は誰も作業しませんでした...明日は頑張りましょう！🛌",
        "embed_title": "📅 本日の作業レポート ({date})",
        "embed_desc": "昨日の成果です✨",
        "embed_color": Colors.PINK, # ピンク色
        "row": "• **{name}**: {time}\n"
    },

    # ---------------------------
    # ⏰ 個人用タイマー
    # ---------------------------
    "timer": {
        "set": "⏰ **{minutes}分** のタイマーをセットしました。\n(終了予定: {end_time})",
        "finish": "⏰ **{minutes}分** が経過しました！\nお疲れ様です、少し休憩しませんか？☕",
        "invalid": "⚠️ 時間は整数（分）で指定してください。\n例: `!30` (30分)",
        "too_long": "⚠️ タイマーは最大 180分 (3時間) まで設定可能です。"
    },

    # ---------------------------
    # ℹ️ ヘルプ (!help)
    # ---------------------------
    "help": {
        "embed_title": "📖 ボットの使い方",
        "embed_desc": "作業通話を記録・応援するボットです。\nVCに入ると自動で計測が始まります。",
        "embed_color": Colors.GRAY, # グレー
        "commands": [
            ("🏆 `/rank`", "今週の作業時間ランキングを表示します。"),
            ("📊 `/stats`", "あなたのこれまでの累計作業時間を表示します。"),
            ("📝 `/task [内容]`", "現在取り組んでいるタスク内容を設定します。"),
            ("🗣️ `/reading [名前]`", "読み上げ用の名前(読み仮名)を設定します。"),
            ("⏰ `/timer [分]`", "個人用タイマーをセットします。"),
            ("✏️ `/add`", "[管理者] 時間を手動で修正します。"),
            ("🗑️ `/clear_log`", "[管理者] ログチャンネルを掃除します。")
        ]
    }
}
