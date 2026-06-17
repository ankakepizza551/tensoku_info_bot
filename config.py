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

LETTER_CHANNEL_ID = _parse_channel_id("LETTER_CHANNEL_ID")
LETTER_ADMIN_CHANNEL_ID = _parse_channel_id("LETTER_ADMIN_CHANNEL_ID")

# Railway環境（ボリュームマウント先 /app/data があるか、または環境変数がある場合）は自動でパスを設定
if os.path.exists("/app/data") or "RAILWAY_ENVIRONMENT" in os.environ:
    DB_PATH = "/app/data/tensoku_stats.db"
else:
    DB_PATH = os.getenv("DB_PATH", "data/tensoku_stats.db")

# Create data directory if it doesn't exist
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
