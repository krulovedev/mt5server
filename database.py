import asyncpg
import pytz
from typing import Dict
from pydantic import BaseModel
import os
from dotenv import load_dotenv

load_dotenv()

# ===========================
# GLOBALS & CONSTANTS
# ===========================
SECRET_KEY = os.getenv("SECRET_KEY", "MY_SUPER_SECRET_KEY")
DATABASE_URL = os.getenv("DATABASE_URL", "postgres://postgres:123456@localhost:5432/postgres")

# Fallback Telegram (จะถูกแทนที่ด้วยค่าจาก DB ถ้ามี)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

MAX_HISTORY = 100000
TZ_BANGKOK = pytz.timezone('Asia/Bangkok')

pool: asyncpg.Pool = None

latest_cache: Dict[str, Dict] = {}
alert_state: Dict[str, Dict] = {}

async def init_db(conn: asyncpg.Connection):
    """สร้างตารางถ้ายังไม่มี (PostgreSQL)"""
    # ตาราง accounts config
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            alias           TEXT PRIMARY KEY,
            display_name    TEXT DEFAULT '',
            account_number  BIGINT,
            broker          TEXT DEFAULT '',
            server          TEXT DEFAULT '',
            currency        TEXT DEFAULT 'USD',
            leverage        INTEGER DEFAULT 100,
            initial_balance DOUBLE PRECISION DEFAULT 10000.0,
            note            TEXT DEFAULT '',
            active          INTEGER DEFAULT 1,
            created_at      TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    # ตาราง snapshots
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS snapshots (
            id              BIGSERIAL PRIMARY KEY,
            alias           TEXT NOT NULL,
            account_number  BIGINT,
            balance         DOUBLE PRECISION,
            equity          DOUBLE PRECISION,
            margin          DOUBLE PRECISION,
            free_margin     DOUBLE PRECISION,
            margin_level    DOUBLE PRECISION,
            profit          DOUBLE PRECISION,
            credit          DOUBLE PRECISION,
            initial_balance DOUBLE PRECISION,
            drawdown_amount DOUBLE PRECISION,
            drawdown_pct    DOUBLE PRECISION,
            equity_dd_pct   DOUBLE PRECISION,
            open_orders     INTEGER,
            buy_orders      INTEGER DEFAULT 0,
            sell_orders     INTEGER DEFAULT 0,
            total_lots      DOUBLE PRECISION,
            buy_lots        DOUBLE PRECISION DEFAULT 0.0,
            sell_lots       DOUBLE PRECISION DEFAULT 0.0,
            withdrawal      DOUBLE PRECISION DEFAULT 0.0,
            net_deposit     DOUBLE PRECISION DEFAULT 0.0,
            ts              TEXT NOT NULL,
            received_at     TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    # Migrations
    migrations = [
        ("snapshots", "buy_orders",  "INTEGER DEFAULT 0"),
        ("snapshots", "sell_orders", "INTEGER DEFAULT 0"),
        ("snapshots", "buy_lots",    "DOUBLE PRECISION DEFAULT 0.0"),
        ("snapshots", "sell_lots",   "DOUBLE PRECISION DEFAULT 0.0"),
        ("snapshots", "withdrawal",  "DOUBLE PRECISION DEFAULT 0.0"),
        ("snapshots", "net_deposit", "DOUBLE PRECISION DEFAULT 0.0"),
        ("accounts",  "display_name","TEXT DEFAULT ''"),
    ]
    for table, col, col_def in migrations:
        exists = await conn.fetchval(
            "SELECT COUNT(*) FROM information_schema.columns WHERE table_name=$1 AND column_name=$2",
            table, col
        )
        if not exists:
            try:
                await conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}")
            except Exception:
                pass

    # Normalize existing ts data format (migration to fix charting bug)
    try:
        await conn.execute("UPDATE snapshots SET ts = REPLACE(REPLACE(ts, '.', '-'), ' ', 'T') WHERE ts LIKE '% %' OR ts LIKE '%.%'")
    except Exception as e:
        print("Migration error on ts:", e)

    # Index
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_snap_alias_ts ON snapshots(alias, ts DESC)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_snap_ts ON snapshots(ts DESC)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_snap_acct_num ON snapshots(account_number, ts DESC)")
    
    # Unique constraint: prevent same account_number with different aliases
    # (Migration-safe: add unique index on accounts.account_number if not exists)
    try:
        await conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_accounts_acct_num
            ON accounts(account_number)
            WHERE account_number IS NOT NULL
        """)
    except Exception as e:
        print("[DB] Note: account_number unique index:", e)

    # ตาราง global alert settings
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS alert_settings (
            id              SERIAL PRIMARY KEY,
            global_enabled  BOOLEAN DEFAULT TRUE,
            bot_token       TEXT DEFAULT '',
            chat_id         TEXT DEFAULT '',
            updated_at      TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    exists = await conn.fetchval("SELECT COUNT(*) FROM alert_settings")
    if not exists:
        await conn.execute(
            "INSERT INTO alert_settings (global_enabled, bot_token, chat_id) VALUES (TRUE, $1, $2)",
            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
        )

    # ตาราง per-account alert settings
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS account_alert_settings (
            alias       TEXT PRIMARY KEY,
            enabled     BOOLEAN DEFAULT TRUE,
            updated_at  TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    print("[DB] ฐานข้อมูล PostgreSQL พร้อมใช้งาน")

async def get_db_pool():
    global pool
    import ssl
    kwargs = {"init": init_db, "min_size": 1, "max_size": 10}
    if "supabase.co" in DATABASE_URL or "supabase.com" in DATABASE_URL:
        kwargs["statement_cache_size"] = 0
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode    = ssl.CERT_NONE
        kwargs["ssl"] = ssl_ctx
        print("[DB] ตรวจพบ Supabase URL → เปิด SSL + statement_cache_size=0")
    pool = await asyncpg.create_pool(DATABASE_URL, **kwargs)
    return pool

async def close_db_pool():
    global pool
    if pool:
        await pool.close()
