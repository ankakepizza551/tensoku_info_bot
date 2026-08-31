import os
from dotenv import load_dotenv

# Load env variables from .env file
load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN", "YOUR_DISCORD_BOT_TOKEN")
PREFIX = os.getenv("BOT_PREFIX", "/")
def _parse_channel_id(env_key: str) -> int:
    val = os.getenv(env_key, "0").strip()
    try:
        return int(val)
    except ValueError:
        import logging
        logging.getLogger("TensokuMatchBot").warning(
            f"環境変数 {env_key} の値 '{val}' は数値ではありません。"
            "チャンネルIDには数字を設定してください。0として扱います。"
        )
        return 0

LETTER_ADMIN_CHANNEL_ID = _parse_channel_id("LETTER_ADMIN_CHANNEL_ID")
SERVER_INVITE_URL = os.getenv("SERVER_INVITE_URL", "").strip()

# Railway環境では必ず /app/data のVolumeにDBを置く。
# Volumeが未マウントのまま起動するとコンテナの一時ディスクに空DBが作られ、
# 再起動・再デプロイのたびにデータが消えてしまうため、未マウント時は起動を止める。
if "RAILWAY_ENVIRONMENT" in os.environ:
    if not os.path.isdir("/app/data"):
        raise RuntimeError(
            "RailwayのVolumeが /app/data にマウントされていません。"
            "Railwayダッシュボードの Volumes タブでこのサービスに"
            "マウントパス /app/data のVolumeを追加してから再起動してください。"
            "（このまま起動するとデータが保存されません）"
        )
    DB_PATH = "/app/data/tensoku_stats.db"
else:
    DB_PATH = os.getenv("DB_PATH", "data/tensoku_stats.db")
    # Create data directory if it doesn't exist（ローカル開発用）
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
