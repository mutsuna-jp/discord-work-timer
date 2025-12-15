# Discord Work Timer Bot ⏳

Discordのボイスチャンネル（VC）での滞在時間を自動で記録し、作業時間の管理やモチベーション向上を支援するボットです。
Dockerを使用して簡単にデプロイでき、SQLiteによるデータの永続化と週間ランキング機能に対応しています。

## 🚀 機能

* **自動記録**: VCへの入退室を検知し、滞在時間を自動で計算・データベースに保存します。
* **退室通知**: 作業終了時に、今回の作業時間を指定のテキストチャンネルに通知します。
* **週間ランキング**: `!rank` コマンドで、今週（月曜始まり）の作業時間ランキングTOP10を表示します。
* **データ永続化**: SQLiteを使用しているため、ボットを再起動しても記録は消えません。
* **Docker対応**: 環境構築が不要で、すぐに稼働させることができます。

## 📦 必要要件

* Docker / Docker Compose
* Discord Bot Token

## 🛠️ セットアップ手順

### 1. リポジトリのクローン
```bash
git clone [https://github.com/mutsuna-jp/discord-work-timer.git](https://github.com/mutsuna-jp/discord-work-timer.git)
cd discord-work-timer
```

### 2. 環境変数の設定
プロジェクトルートに .env ファイルを作成し、以下の内容を記述してください。 ※ .env は .gitignore に含まれているため、GitHubにはアップロードされません。

```Ini, TOML
DISCORD_BOT_TOKEN=ここにあなたのボットトークン
LOG_CHANNEL_ID=ここに通知を送りたいチャンネルのID(数字)
```

### 3. 起動
Docker Composeを使用してビルド・起動します。

```Bash
docker compose up -d --build
```

### 4. 停止・ログ確認
ログ確認: `docker compose logs -f`

停止: `docker compose down`


## 📖 使い方
### 基本操作
* **記録開始**: ボイスチャンネルに入室すると自動でスタートします。
* **記録終了**: ボイスチャンネルから退室すると自動で終了し、通知が飛びます。

## コマンド
テキストチャンネルで以下を入力してください。

| コマンド | 説明 |
| :--- | :--- |
| `!rank` | 今週の作業時間ランキングを表示します |

## 📂 ディレクトリ構成
```
.
├── data/                # SQLiteのデータベースファイルが保存されます (永続化領域)
├── main.py              # ボットのソースコード
├── requirements.txt     # Python依存ライブラリ
├── Dockerfile           # Dockerイメージ定義
├── docker-compose.yml   # Docker Compose設定
├── .env                 # 環境変数 (作成が必要)
└── .gitignore           # Git除外設定
```
## 🛡️ ライセンス
This project is licensed under the MIT License.
