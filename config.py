import os
from dotenv import load_dotenv

# Load env variables from .env file
load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN", "YOUR_DISCORD_BOT_TOKEN")
PREFIX = os.getenv("BOT_PREFIX", "/")

# Railway環境（ボリュームマウント先 /app/data があるか、または環境変数がある場合）は自動でパスを設定
if os.path.exists("/app/data") or "RAILWAY_ENVIRONMENT" in os.environ:
    DB_PATH = "/app/data/tensoku_stats.db"
else:
    DB_PATH = os.getenv("DB_PATH", "data/tensoku_stats.db")

# Create data directory if it doesn't exist
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
