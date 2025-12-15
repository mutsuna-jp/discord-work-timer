# メッセージ管理ファイル

MESSAGES = {
    # ---------------------------
    # 👋 入室時
    # ---------------------------
    "join": {
        "voice": "{name}さん、現在、{current_total}です。",
        "embed_title": "🚀 作業スタート！",
        "embed_color": 0x00FF00, # 緑色
        # フィールド名と値
        "field_name": "本日の作業時間",
        "field_value": "**{current_total}** "
    },

    # ---------------------------
    # 🍵 退室時
    # ---------------------------
    "leave": {
        "embed_title": "🍵 お疲れ様でした",
        "embed_color": 0x00BFFF, # 水色
        "field1_name": "今回の作業時間",
        "field1_value": "**{time}**",
        "field2_name": "本日の総作業時間",
        "field2_value": "**{total}**",
    },

    # ---------------------------
    # 🏆 ランキング (!rank)
    # ---------------------------
    "rank": {
        "empty": "今週はまだ誰も作業していません...！一番乗りを目指しましょう！🏃‍♂️",
        "embed_title": "🏆 今週の作業時間ランキング",
        "embed_color": 0xFFD700, # 金色
        "row": "{icon} **{name}**: {time}\n"
    },

    # ---------------------------
    # 🔥 作業再開時 (追加)
    # ---------------------------
    "resume": {
        "voice": "{name}さん、作業再開です。",
        "embed_title": "🔥 作業再開！",
        "embed_color": 0xFF4500, # オレンジ色
        "field_name": "今日の積み上げ",
        "field_value": "**{current_total}**"
    },

    # ---------------------------
    # ☕ 休憩時 (追加)
    # ---------------------------
    "break": {
        "embed_title": "☕ 休憩中...",
        "embed_color": 0xFFA500, # 黄色
        "field1_name": "今回の作業時間",
        "field1_value": "**{time}**",
        "field2_name": "本日の総作業時間",
        "field2_value": "**{total}**",
    },

    # ---------------------------
    # 📅 日報 (23:59)
    # ---------------------------
    "report": {
        "empty": "今日は誰も作業しませんでした...明日は頑張りましょう！🛌",
        "embed_title": "📅 本日の作業レポート ({date})",
        "embed_desc": "みなさんお疲れ様でした！本日の成果です✨",
        "embed_color": 0xFF69B4, # ピンク色
        "row": "• **{name}**: {time}\n"
    }
}
