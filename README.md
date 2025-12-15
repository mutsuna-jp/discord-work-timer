# Discord Work Timer Bot ⏳

Discord のボイスチャンネル（VC）での滞在時間を自動で記録し、作業時間の管理やモチベーション向上を支援するボットです。
Docker を使用して簡単にデプロイでき、SQLite によるデータの永続化と豊富な統計機能に対応しています。

## 🚀 機能

- **自動記録**: VC への入退室を検知し、滞在時間を自動で計算・データベースに保存します。
- **入退室通知**: 入退室時に音声読み上げ（日本語）で通知し、作業終了時に今回の作業時間を指定のテキストチャンネルに通知します。
- **週間ランキング**: `!rank` コマンドで、今週（月曜始まり）の作業時間ランキング TOP10 を表示します。
- **個人統計**: `!stats` コマンドで、ユーザーの累計作業時間と計測開始日を表示します。
- **カスタムタイマー**: `!timer <分数>` で個人用タイマーを設定でき、時間になると DM で通知が来ます（最大 180 分）。
- **日次レポート**: 毎日 23:59 に前日の作業レポートを送信します。
- **自動バックアップ**: データベースを毎日自動的にバックアップし、指定チャンネルに送信します。
- **自動クリーンアップ**: 古いログ（デフォルト 30 日以上前）を自動削除してディスク容量を節約します。
- **データ永続化**: SQLite を使用しているため、ボットを再起動しても記録は消えません。
- **Docker 対応**: 環境構築が不要で、すぐに稼働させることができます。

## 📦 必要要件

- Docker / Docker Compose
- Discord Bot Token

## 🛠️ セットアップ手順

### 1. リポジトリのクローン

```bash
git clone [https://github.com/mutsuna-jp/discord-work-timer.git](https://github.com/mutsuna-jp/discord-work-timer.git)
cd discord-work-timer
```

### 2. 環境変数の設定

プロジェクトルートに .env ファイルを作成し、以下の内容を記述してください。 ※ .env は .gitignore に含まれているため、GitHub にはアップロードされません。

```Ini
DISCORD_BOT_TOKEN=ここにあなたのボットトークン
LOG_CHANNEL_ID=ここに作業ログを送るチャンネルのID(数字)
SUMMARY_CHANNEL_ID=日次サマリーを送るチャンネルのID(数字)※オプション
BACKUP_CHANNEL_ID=バックアップを送るチャンネルのID(数字)※オプション
```

**必須項目**

- `DISCORD_BOT_TOKEN`: Discord ボットのトークン
- `LOG_CHANNEL_ID`: ユーザーの入退室ログが送られるチャンネル ID

**オプション項目**

- `SUMMARY_CHANNEL_ID`: 日次の作業サマリーを送りたい場合に設定
- `BACKUP_CHANNEL_ID`: ログのバックアップを送りたい場合に設定

### 3. 起動

Docker Compose を使用してビルド・起動します。

```Bash
docker compose up -d --build
```

### 4. 停止・ログ確認

ログ確認: `docker compose logs -f`

停止: `docker compose down`

## 📖 使い方

### 基本操作

- **記録開始**: ボイスチャンネルに入室すると自動でスタートします。
- **記録終了**: ボイスチャンネルから退室すると自動で終了し、通知が飛びます。

## コマンド

テキストチャンネルで以下を入力してください。

| コマンド                 | 説明                                                                              |
| :----------------------- | :-------------------------------------------------------------------------------- |
| `!rank`                  | 今週の作業時間ランキング TOP10 を表示します                                       |
| `!stats`                 | あなたの累計作業時間と計測開始日を表示します                                      |
| `!timer <分数>`          | 指定した分数のタイマーを設定します（最大 180 分）。時間になると DM で通知が来ます |
| `!help`                  | ボットのヘルプを表示します                                                        |
| `!add <ユーザー> <分数>` | 管理者コマンド：ユーザーの作業時間に指定分数を追加します                          |

## 📂 ディレクトリ構成

```
.
├── data/                # SQLiteのデータベースファイルが保存されます (永続化領域)
├── main.py              # ボットのメインソースコード
├── messages.py          # メッセージテンプレート定義
├── requirements.txt     # Python依存ライブラリ
├── Dockerfile           # Dockerイメージ定義
├── docker-compose.yml   # Docker Compose設定
├── .env                 # 環境変数 (作成が必要)
└── .gitignore           # Git除外設定
```

## 🔧 技術スタック

- **discord.py**: Discord Bot API
- **SQLite3**: ローカルデータベース
- **edge-tts**: テキスト音声合成（入退室通知用）
- **Docker**: コンテナ化
- **FFmpeg**: 音声再生

## 🛡️ ライセンス

This project is licensed under the MIT License.

## ⚙️ 設定のカスタマイズ

### 音声設定

[main.py](main.py) の `VOICE_NAME` 変数で音声を変更できます。

```python
VOICE_NAME = "ja-JP-NanamiNeural"  # デフォルトは七海さん
```

### ログ保持期間

[main.py](main.py) の `KEEP_LOG_DAYS` で古いログの自動削除期間を設定できます。

```python
KEEP_LOG_DAYS = 30  # デフォルトは30日
```

### タイマーの最大時間

[main.py](main.py) の `TIMER_MAX_MINUTES` でタイマーの最大設定時間を変更できます。

```python
TIMER_MAX_MINUTES = 180  # デフォルトは180分（3時間）
```

### リソース制限

[docker-compose.yml](docker-compose.yml) で CPU とメモリの使用制限を変更できます。

```yaml
deploy:
  resources:
    limits:
      cpus: "0.50" # CPU使用率（デフォルト50%）
      memory: 256M # メモリ（デフォルト256MB）
```

## 💾 バックアップと復元

### 自動バックアップ

ボットは毎日 23:59 に自動的にデータベースをバックアップし、`BACKUP_CHANNEL_ID` に指定したチャンネルに送信します。

バックアップには以下の情報が含まれます：

- **データベースファイル** (`backup_YYYY-MM-DD.db`)
- **クリーンアップ情報**: 削除されたログ数、消費メモリ

### バックアップからの復元方法

#### 1. バックアップファイルの取得

Discord の指定チャンネルから復元したいバックアップファイルをダウンロードします。

#### 2. ボットの停止

```bash
docker compose down
```

#### 3. バックアップファイルの配置

ダウンロードしたバックアップファイルを `data/` ディレクトリに配置します：

```bash
# ローカルの data/ フォルダに backup_YYYY-MM-DD.db を置く
cp path/to/backup_YYYY-MM-DD.db ./data/
```

#### 4. ファイル名の変更

復元するファイルを `study_log.db` にリネームします：

```bash
cd data/
mv backup_YYYY-MM-DD.db study_log.db
```

#### 5. ボットの再起動

```bash
docker compose up -d
```

ボットが起動し、バックアップから復元したデータが使用可能になります。

**⚠️ 注意**: 既存の `study_log.db` は上書きされます。必要に応じて先にバックアップを取ってください。
