import os
from dotenv import load_dotenv

# Load env variables from .env file
load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN", "YOUR_DISCORD_BOT_TOKEN")
PREFIX = os.getenv("BOT_PREFIX", "/")
DB_PATH = os.getenv("DB_PATH", "data/tensoku_stats.db")

# Create data directory if it doesn't exist
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
