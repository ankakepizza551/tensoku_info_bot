# AGENTS.md

## Cursor Cloud specific instructions

### What this is
A Python Discord bot (`discord.py`) for Touhou 非想天則 match stats: Elo ratings, leaderboards, polls/surveys, recruitment, calendar, and rich embed posting. Entry point is `main.py`, which initializes a SQLite DB (`aiosqlite`) and loads the cogs in `cogs/`. Setup/run steps are in `README.md`.

### Dependencies
Installed into a local virtualenv at `.venv` by the startup update script (`python3 -m venv .venv` + `pip install -r requirements.txt`). Run everything with `.venv/bin/python`. The `python3.12-venv` system package is preinstalled in the VM snapshot.

### Running the bot
- Run with `.venv/bin/python main.py`.
- Requires a real `DISCORD_TOKEN` (set it as a secret). Without a valid token the process still initializes the DB and loads all cogs, then exits at login with `discord.errors.LoginFailure: Improper token has been passed.` — that is expected, not an environment problem.
- `LETTER_ADMIN_CHANNEL_ID` (and other IDs) are optional env vars; unset values default to `0`.
- The `PyNaCl`/`davey` "voice will NOT be supported" warnings at startup are harmless (voice is unused).

### Fresh-database gotcha (important)
`database/db_manager.py::init_db` has a migration-ordering bug that only bites on a **brand-new/empty** DB: it runs `ALTER TABLE polls ADD COLUMN is_anonymous ...` before the `polls` table is created, so a cold start crashes with `sqlite3.OperationalError: no such table: polls`. The deployed instance never hits this because its DB persists and already has `polls`. The DB lives under `data/` which is gitignored, so a fresh Cloud VM will hit it. Workaround before the first run on a fresh DB (do NOT edit app code):
```bash
.venv/bin/python -c "import sqlite3;c=sqlite3.connect('data/tensoku_stats.db');c.execute('CREATE TABLE IF NOT EXISTS polls (poll_id TEXT PRIMARY KEY, channel_id INTEGER NOT NULL, creator_id INTEGER NOT NULL, question TEXT NOT NULL, options TEXT NOT NULL, is_active INTEGER DEFAULT 1, allow_multiple INTEGER DEFAULT 1, is_anonymous INTEGER DEFAULT 1, deadline TEXT DEFAULT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)');c.commit();c.close()"
```
Once `polls` exists, `init_db` runs cleanly and is idempotent thereafter.

### Testing core logic without Discord
The business logic (Elo, stats, leaderboard, deletion/rollback) lives in `database/db_manager.py` and can be driven directly with `asyncio` against the SQLite DB — no Discord connection needed. Compile-check everything with `.venv/bin/python -m py_compile main.py config.py database/db_manager.py cogs/*.py`.
