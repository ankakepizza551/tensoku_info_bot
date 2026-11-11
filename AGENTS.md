# AGENTS.md

## Cursor Cloud specific instructions

This repo is a single Python `discord.py` bot ("東方非想天則 戦績管理BOT" / Touhou Hisoutensoku match-stats bot). It is one long-running worker process (`python main.py`) backed by an embedded SQLite file (`aiosqlite`). There is no web server and no port binding. See `README.md` (setup section) and `Procfile` for the canonical run command.

### Environment / running
- Dependencies live in a local virtualenv at `.venv` (gitignored). The startup update script creates/refreshes it from `requirements.txt`. Run tools via `.venv/bin/python`.
- System `python3` is 3.12 (`.python-version` pins `3.11`, but README states 3.8+ and the code runs fine on 3.12).
- Config is read from environment / a `.env` file via `config.py`. The only hard requirement to actually connect is `DISCORD_TOKEN`; optional: `BOT_PREFIX` (default `/`), `DB_PATH` (default `data/tensoku_stats.db`), `LETTER_ADMIN_CHANNEL_ID`.
- Run the bot: `DISCORD_TOKEN=... .venv/bin/python main.py`. Without a real token it boots fully (DB init + all 11 cogs load) and then fails at Discord login with `401 Unauthorized` — that error means everything except credentials is working. A real `DISCORD_TOKEN` requires a Discord bot account with the Message Content + Server Members intents enabled.

### Known startup gotcha (fresh database)
- `database/db_manager.py::init_db()` has a migration-ordering bug: the `polls.is_anonymous` `ALTER TABLE` migration runs *before* the `polls` table is created, so on a brand-new empty DB startup crashes with `sqlite3.OperationalError: no such table: polls`. Production doesn't hit this because the Railway volume already holds an initialized DB.
- Workaround to run against a fresh DB without editing app code: pre-create the `polls` table before first launch, e.g.
  ```bash
  .venv/bin/python -c "import sqlite3;c=sqlite3.connect('data/tensoku_stats.db');c.execute('CREATE TABLE IF NOT EXISTS polls (poll_id TEXT PRIMARY KEY, channel_id INTEGER NOT NULL, creator_id INTEGER NOT NULL, question TEXT NOT NULL, options TEXT NOT NULL, is_active INTEGER DEFAULT 1, allow_multiple INTEGER DEFAULT 1, is_anonymous INTEGER DEFAULT 1, deadline TEXT DEFAULT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)');c.commit()"
  ```
  After the `polls` table exists, `init_db()` is idempotent and all other `CREATE TABLE IF NOT EXISTS` / migrations succeed.

### Testing
- No test framework is configured. Core logic (match recording, Elo, stats, leaderboard) lives in `database/db_manager.py` and can be exercised headlessly by importing it and calling the async functions (`add_match`, `get_user_stats`, `get_leaderboard`, `delete_match`) — these are what `/report`, `/stats`, `/leaderboard`, `/delete_match` call.
- Lint/syntax check: `.venv/bin/python -m py_compile main.py config.py database/db_manager.py cogs/*.py`.
