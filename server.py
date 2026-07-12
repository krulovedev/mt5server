"""
MT5 Monitor Server
==================
FastAPI + PostgreSQL (Supabase) server สำหรับรับข้อมูลจาก MT5 หลาย Account
รองรับ Render.com + Supabase (free PostgreSQL ไม่มีหมดอายุ)

Requirements:
    pip install fastapi uvicorn asyncpg pydantic

Run:
    python server.py
    หรือ uvicorn server:app --host 0.0.0.0 --port 8000
"""
import asyncio
import json
import os
import re
import socket
import ssl as _ssl
from urllib.parse import urlparse, urlunparse
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any

import asyncpg
from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

# ===========================
# CONFIG
# ===========================
def force_ipv4_in_url(url: str) -> str:
    """แปลง Hostname ใน Connection string ให้เป็น IPv4 เสมอ เพื่อแก้ปัญหา Render ไม่รองรับ IPv6"""
    try:
        parsed = urlparse(url)
        if not parsed.hostname:
            return url
        # ค้นหาเฉพาะ IPv4 (AF_INET)
        addrinfo = socket.getaddrinfo(parsed.hostname, parsed.port or 5432, family=socket.AF_INET, proto=socket.IPPROTO_TCP)
        if not addrinfo:
            return url
        ipv4_host = addrinfo[0][4][0]
        print(f"[DB] resolved {parsed.hostname} -> IPv4: {ipv4_host}")
        
        auth = ""
        if parsed.username:
            auth = parsed.username
            if parsed.password is not None:
                auth += f":{parsed.password}"
            auth += "@"
        
        new_netloc = f"{auth}{ipv4_host}"
        if parsed.port:
            new_netloc += f":{parsed.port}"
            
        new_parsed = parsed._replace(netloc=new_netloc)
        return urlunparse(new_parsed)
    except Exception as e:
        print(f"[DB] Warning forcing IPv4: {e}")
        return url

# รองรับ Supabase URL ที่อาจขึ้นต้น "postgres://" และมี ?sslmode=require
_raw_url   = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/mt5monitor")
# 1. แก้ scheme
DATABASE_URL = _raw_url.replace("postgres://", "postgresql://", 1) if _raw_url.startswith("postgres://") else _raw_url
# 2. ลบเครื่องหมาย [ ] ที่อาจครอบรหัสผ่านอยู่ (กรณีคัดลอกจากเทมเพลต Supabase ตรงๆ)
DATABASE_URL = re.sub(r':\[([^\]@:/]+)\]@', r':\1@', DATABASE_URL)
# 3. ตัด query parameters ทั้งหมดออก (เช่น ?pgbouncer=true, ?sslmode=require) เพราะ asyncpg ไม่รองรับ
DATABASE_URL = DATABASE_URL.split('?')[0]
# 4. บังคับเป็น IPv4 เพื่อป้องกัน Network is unreachable จาก IPv6 บน Render
DATABASE_URL = force_ipv4_in_url(DATABASE_URL)

SECRET_KEY  = os.environ.get("SECRET_KEY", "mysecretkey")   # ตั้งใน Render env vars
MAX_HISTORY = 100_000                # เก็บ record สูงสุดต่อ account
HOST        = "0.0.0.0"
PORT        = int(os.environ.get("PORT", 8000))             # Render inject PORT อัตโนมัติ

# เขตเวลา UTC+7 สำหรับการแสดงผลและการบันทึกเวลาเริ่มต้น
TZ_BANGKOK  = timezone(timedelta(hours=7))

# ===========================
# APP SETUP
# ===========================
app = FastAPI(title="MT5 Monitor", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global connection pool (สร้างตอน startup)
pool: asyncpg.Pool = None


def _is_supabase(url: str) -> bool:
    return "supabase.co" in url or "supabase.com" in url


async def _create_pool() -> asyncpg.Pool:
    """
    สร้าง asyncpg connection pool รองรับ:
    - Supabase direct connection  (port 5432)
    - Supabase session pooler     (port 5432, PgBouncer session mode)
    - Supabase transaction pooler (port 6543, PgBouncer transaction mode)
    - Render / local PostgreSQL
    """
    kwargs: dict = dict(
        min_size=1,
        max_size=5,
        statement_cache_size=0,   # จำเป็นสำหรับ Supabase PgBouncer (transaction mode)
    )

    if _is_supabase(DATABASE_URL):
        # Supabase บังคับ SSL — สร้าง context ที่ไม่ verify cert (Supabase ใช้ self-managed CA)
        ssl_ctx = _ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode    = _ssl.CERT_NONE
        kwargs["ssl"] = ssl_ctx
        print("[DB] ตรวจพบ Supabase URL → เปิด SSL + statement_cache_size=0")

    return await asyncpg.create_pool(DATABASE_URL, **kwargs)

# ===========================
# DATABASE SETUP
# ===========================
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
            initial_balance DOUBLE PRECISION DEFAULT 10000,
            note            TEXT DEFAULT '',
            active          INTEGER DEFAULT 1,
            created_at      TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    # ตาราง snapshots (ข้อมูลที่ส่งมาทุกนาที)
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
            ts              TEXT NOT NULL,
            received_at     TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    # Migration: เพิ่ม column ถ้ายังไม่มี (ตรวจสอบผ่าน information_schema)
    migrations = [
        ("snapshots", "buy_orders",  "INTEGER DEFAULT 0"),
        ("snapshots", "sell_orders", "INTEGER DEFAULT 0"),
        ("snapshots", "buy_lots",    "DOUBLE PRECISION DEFAULT 0.0"),
        ("snapshots", "sell_lots",   "DOUBLE PRECISION DEFAULT 0.0"),
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

    # Index สำหรับ query เร็ว
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_snap_alias_ts ON snapshots(alias, ts DESC)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_snap_ts ON snapshots(ts DESC)")

    print("[DB] ฐานข้อมูล PostgreSQL พร้อมใช้งาน")


# ===========================
# PYDANTIC MODELS
# ===========================
class MT5DataPayload(BaseModel):
    secret:             str
    alias:              str
    account_number:     int
    broker:             str       = ""
    server:             str       = ""
    currency:           str       = "USD"
    leverage:           int       = 100
    balance:            float
    equity:             float
    margin:             float     = 0.0
    free_margin:        float     = 0.0
    margin_level:       float     = 0.0
    profit:             float     = 0.0
    credit:             float     = 0.0
    initial_balance:    float     = 10000.0
    drawdown_amount:    float     = 0.0
    drawdown_pct:       float     = 0.0
    equity_drawdown_pct: float    = 0.0
    open_orders:        int       = 0
    buy_orders:         int       = 0
    sell_orders:        int       = 0
    total_lots:         float     = 0.0
    buy_lots:           float     = 0.0
    sell_lots:          float     = 0.0
    timestamp:          str       = ""


class AccountConfig(BaseModel):
    alias:           str
    initial_balance: float = 10000.0
    note:            str   = ""


class AccountRename(BaseModel):
    display_name: str


# ===========================
# CACHE (latest data per account)
# ===========================
latest_cache: Dict[str, Dict] = {}

@app.on_event("startup")
async def startup_event():
    """สร้าง connection pool, init DB, โหลด cache"""
    global pool
    print(f"[DB] กำลังเชื่อมต่อ PostgreSQL...")
    pool = await _create_pool()

    async with pool.acquire() as conn:
        await init_db(conn)

    # โหลดข้อมูลล่าสุดจาก DB เข้า Cache
    try:
        async with pool.acquire() as conn:
            accounts = await conn.fetch("SELECT alias, display_name, active FROM accounts")

            for acc in accounts:
                alias = acc["alias"]
                snap = await conn.fetchrow(
                    "SELECT * FROM snapshots WHERE alias=$1 ORDER BY ts DESC LIMIT 1",
                    alias
                )
                if snap:
                    s = dict(snap)
                    latest_cache[alias] = {
                        "alias":           alias,
                        "display_name":    acc["display_name"] or alias,
                        "account_number":  s.get("account_number"),
                        "broker":          "",
                        "currency":        "USD",
                        "leverage":        100,
                        "balance":         s.get("balance"),
                        "equity":          s.get("equity"),
                        "margin":          s.get("margin"),
                        "free_margin":     s.get("free_margin"),
                        "margin_level":    s.get("margin_level"),
                        "profit":          s.get("profit"),
                        "initial_balance": s.get("initial_balance"),
                        "drawdown_amount": s.get("drawdown_amount"),
                        "drawdown_pct":    s.get("drawdown_pct"),
                        "equity_dd_pct":   s.get("equity_dd_pct"),
                        "open_orders":     s.get("open_orders"),
                        "buy_orders":      s.get("buy_orders", 0),
                        "sell_orders":     s.get("sell_orders", 0),
                        "total_lots":      s.get("total_lots"),
                        "buy_lots":        s.get("buy_lots", 0.0),
                        "sell_lots":       s.get("sell_lots", 0.0),
                        "timestamp":       s.get("ts"),
                        "received_at":     datetime.now(TZ_BANGKOK).strftime('%Y-%m-%dT%H:%M:%S'),
                        "active":          acc["active"],
                    }
        print(f"[DB] โหลดข้อมูลลง Cache สำเร็จ: {len(latest_cache)} accounts")
    except Exception as e:
        print(f"[DB] Error loading cache: {e}")


@app.on_event("shutdown")
async def shutdown_event():
    global pool
    if pool:
        await pool.close()


# ===========================
# API ENDPOINTS
# ===========================

@app.post("/api/data")
async def receive_data(payload: MT5DataPayload):
    """รับข้อมูลจาก MQL5 EA"""
    if payload.secret != SECRET_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

    ts = payload.timestamp or datetime.now(TZ_BANGKOK).strftime('%Y-%m-%dT%H:%M:%S')

    async with pool.acquire() as conn:
        async with conn.transaction():
            # Upsert account info (ไม่อัพเดท display_name)
            await conn.execute("""
                INSERT INTO accounts (alias, account_number, broker, server, currency, leverage, initial_balance)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (alias) DO UPDATE SET
                    account_number = EXCLUDED.account_number,
                    broker         = EXCLUDED.broker,
                    server         = EXCLUDED.server,
                    currency       = EXCLUDED.currency,
                    leverage       = EXCLUDED.leverage
            """,
                payload.alias, payload.account_number, payload.broker,
                payload.server, payload.currency, payload.leverage,
                payload.initial_balance
            )

            # Insert snapshot
            await conn.execute("""
                INSERT INTO snapshots
                    (alias, account_number, balance, equity, margin, free_margin, margin_level,
                     profit, credit, initial_balance, drawdown_amount, drawdown_pct, equity_dd_pct,
                     open_orders, buy_orders, sell_orders, total_lots, buy_lots, sell_lots, ts)
                VALUES
                    ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20)
            """,
                payload.alias, payload.account_number,
                payload.balance, payload.equity, payload.margin, payload.free_margin,
                payload.margin_level, payload.profit, payload.credit, payload.initial_balance,
                payload.drawdown_amount, payload.drawdown_pct, payload.equity_drawdown_pct,
                payload.open_orders, payload.buy_orders, payload.sell_orders, payload.total_lots,
                payload.buy_lots, payload.sell_lots, ts
            )

            # ลบข้อมูลเก่าเกิน MAX_HISTORY ต่อ account
            await conn.execute("""
                DELETE FROM snapshots
                WHERE alias = $1 AND id NOT IN (
                    SELECT id FROM snapshots WHERE alias = $1
                    ORDER BY id DESC LIMIT $2
                )
            """, payload.alias, MAX_HISTORY)

        # ดึง display_name และ active จาก DB (ในรายการเดิม)
        acc_row = await conn.fetchrow(
            "SELECT display_name, active FROM accounts WHERE alias=$1",
            payload.alias
        )

    display_name = (acc_row["display_name"] if acc_row and acc_row["display_name"] else payload.alias)
    active = acc_row["active"] if acc_row else 1

    latest_cache[payload.alias] = {
        "alias":           payload.alias,
        "display_name":    display_name,
        "account_number":  payload.account_number,
        "broker":          payload.broker,
        "currency":        payload.currency,
        "leverage":        payload.leverage,
        "balance":         payload.balance,
        "equity":          payload.equity,
        "margin":          payload.margin,
        "free_margin":     payload.free_margin,
        "margin_level":    payload.margin_level,
        "profit":          payload.profit,
        "initial_balance": payload.initial_balance,
        "drawdown_amount": payload.drawdown_amount,
        "drawdown_pct":    payload.drawdown_pct,
        "equity_dd_pct":   payload.equity_drawdown_pct,
        "open_orders":     payload.open_orders,
        "buy_orders":      payload.buy_orders,
        "sell_orders":     payload.sell_orders,
        "total_lots":      payload.total_lots,
        "buy_lots":        payload.buy_lots,
        "sell_lots":       payload.sell_lots,
        "timestamp":       ts,
        "received_at":     datetime.now(TZ_BANGKOK).strftime('%Y-%m-%dT%H:%M:%S'),
        "active":          active,
    }

    return {"status": "ok", "alias": payload.alias}


@app.get("/api/accounts")
async def get_accounts():
    """รายชื่อ accounts ทั้งหมด"""
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM accounts ORDER BY alias")
    return [dict(r) for r in rows]


@app.get("/api/balance")
async def get_balance():
    """ข้อมูล balance ล่าสุดของทุก account"""
    result = []
    for alias, data in latest_cache.items():
        result.append({
            "alias":        alias,
            "display_name": data.get("display_name", alias),
            "balance":      data.get("balance", 0),
            "equity":       data.get("equity", 0),
            "profit":       data.get("profit", 0),
        })
    return result


@app.get("/api/latest")
async def get_latest_all():
    """ข้อมูลล่าสุดของทุก account (realtime จาก cache)"""
    async with pool.acquire() as conn:
        acc_rows = await conn.fetch("SELECT alias, active, display_name FROM accounts")
    acc_map = {r["alias"]: dict(r) for r in acc_rows}

    result = []
    for alias, data in latest_cache.items():
        acc_info   = acc_map.get(alias, {})
        active     = acc_info.get("active", 1)
        display_name = acc_info.get("display_name", "") or alias
        entry = dict(data)
        entry["active"]       = active
        entry["display_name"] = display_name
        result.append(entry)
    return result


@app.get("/api/latest/{alias}")
async def get_latest_one(alias: str):
    """ข้อมูลล่าสุดของ account เดียว"""
    if alias in latest_cache:
        return latest_cache[alias]
    # Fallback จาก DB
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM snapshots WHERE alias=$1 ORDER BY ts DESC LIMIT 1",
            alias
        )
    if not row:
        raise HTTPException(status_code=404, detail="Account not found")
    return dict(row)


@app.get("/api/history/{alias}")
async def get_history(
    alias: str,
    start: Optional[str] = Query(None, description="เวลาเริ่ม (ISO format)"),
    end:   Optional[str] = Query(None, description="เวลาสิ้นสุด (ISO format)"),
    limit: int = Query(1440, ge=1, le=10000, description="จำนวน record"),
    field: str = Query("balance,equity,drawdown_pct,profit", description="fields ที่ต้องการ")
):
    """ข้อมูลย้อนหลังของ account"""
    if not end:
        end = datetime.now(TZ_BANGKOK).strftime('%Y-%m-%dT%H:%M:%S')
    if not start:
        start = (datetime.now(TZ_BANGKOK) - timedelta(hours=24)).strftime('%Y-%m-%dT%H:%M:%S')

    # เลือก fields ที่ปลอดภัย (ป้องกัน SQL injection)
    allowed = {"balance","equity","margin","free_margin","margin_level","profit",
               "drawdown_amount","drawdown_pct","equity_dd_pct","open_orders",
               "buy_orders","sell_orders","total_lots","buy_lots","sell_lots","ts"}
    fields = [f for f in field.split(",") if f.strip() in allowed]
    if not fields:
        fields = ["balance","equity","drawdown_pct","profit","ts"]
    if "ts" not in fields:
        fields.append("ts")

    cols = ", ".join(fields)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT {cols} FROM snapshots WHERE alias=$1 AND ts BETWEEN $2 AND $3 ORDER BY ts ASC LIMIT $4",
            alias, start, end, limit
        )

    return {
        "alias": alias,
        "start": start,
        "end":   end,
        "count": len(rows),
        "data":  [dict(r) for r in rows]
    }


@app.get("/api/summary")
async def get_summary():
    """สรุปภาพรวมทุก account"""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT alias, COUNT(*) as total_snapshots,
                   MIN(ts) as first_seen, MAX(ts) as last_seen
            FROM snapshots GROUP BY alias
        """)
    summary = [dict(r) for r in rows]
    for s in summary:
        if s["alias"] in latest_cache:
            s.update({
                "balance":      latest_cache[s["alias"]]["balance"],
                "equity":       latest_cache[s["alias"]]["equity"],
                "drawdown_pct": latest_cache[s["alias"]]["drawdown_pct"],
                "profit":       latest_cache[s["alias"]]["profit"],
            })
    return summary


@app.patch("/api/accounts/{alias}")
async def update_account(alias: str, config: AccountConfig):
    """อัพเดท config ของ account"""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE accounts SET initial_balance=$1, note=$2 WHERE alias=$3",
            config.initial_balance, config.note, alias
        )
    if alias in latest_cache:
        latest_cache[alias]["initial_balance"] = config.initial_balance
    return {"status": "updated", "alias": alias}


@app.put("/api/accounts/{alias}/rename")
async def rename_account(alias: str, body: AccountRename):
    """เปลี่ยนชื่อที่แสดงของ account"""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE accounts SET display_name=$1 WHERE alias=$2",
            body.display_name, alias
        )
    if alias in latest_cache:
        latest_cache[alias]["display_name"] = body.display_name
    return {"status": "renamed", "alias": alias, "display_name": body.display_name}


@app.put("/api/accounts/{alias}/toggle")
async def toggle_account(alias: str):
    """ซ่อน/แสดง account"""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT active FROM accounts WHERE alias=$1", alias)
        if not row:
            raise HTTPException(status_code=404, detail="Account not found")
        new_active = 0 if row["active"] else 1
        await conn.execute(
            "UPDATE accounts SET active=$1 WHERE alias=$2",
            new_active, alias
        )
    if alias in latest_cache:
        latest_cache[alias]["active"] = new_active
    return {"status": "ok", "alias": alias, "active": new_active}


@app.delete("/api/accounts/{alias}")
async def delete_account(alias: str):
    """ลบ account และ snapshots ทั้งหมด"""
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM snapshots WHERE alias=$1", alias)
            await conn.execute("DELETE FROM accounts WHERE alias=$1", alias)
    if alias in latest_cache:
        del latest_cache[alias]
    return {"status": "deleted", "alias": alias}


@app.get("/api/stats/{alias}")
async def get_stats(alias: str, days: int = Query(7, ge=1, le=90)):
    """สถิติสรุปของ account ในช่วง N วัน"""
    start = (datetime.now(TZ_BANGKOK) - timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%S')
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT
                COUNT(*)            as snapshots,
                AVG(balance)        as avg_balance,
                MAX(balance)        as max_balance,
                MIN(balance)        as min_balance,
                AVG(equity)         as avg_equity,
                MAX(equity)         as max_equity,
                MIN(equity)         as min_equity,
                MAX(drawdown_pct)   as max_drawdown_pct,
                AVG(drawdown_pct)   as avg_drawdown_pct,
                MIN(drawdown_pct)   as min_drawdown_pct,
                MAX(profit)         as max_profit,
                MIN(profit)         as min_profit,
                AVG(profit)         as avg_profit,
                MAX(open_orders)    as max_open_orders,
                MIN(open_orders)    as min_open_orders,
                AVG(margin_level)   as avg_margin_level,
                MAX(margin_level)   as max_margin_level,
                MIN(margin_level)   as min_margin_level,
                MAX(total_lots)     as max_total_lots,
                MIN(total_lots)     as min_total_lots,
                AVG(total_lots)     as avg_total_lots
            FROM snapshots WHERE alias=$1 AND ts >= $2
        """, alias, start)
    return dict(row) if row else {}


@app.get("/api/alltime/{alias}")
async def get_alltime_stats(alias: str):
    """สถิติ all-time ของ account ตั้งแต่เริ่มเก็บข้อมูล"""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT
                COUNT(*)            as snapshots,
                MIN(ts)             as first_seen,
                MAX(ts)             as last_seen,
                MAX(drawdown_pct)   as max_drawdown_pct,
                MIN(drawdown_pct)   as min_drawdown_pct,
                MAX(profit)         as max_profit,
                MIN(profit)         as min_profit,
                MAX(balance)        as max_balance,
                MIN(balance)        as min_balance,
                MIN(margin_level)   as min_margin_level,
                MAX(margin_level)   as max_margin_level,
                MAX(open_orders)    as max_open_orders,
                MAX(equity)         as max_equity,
                MIN(equity)         as min_equity
            FROM snapshots WHERE alias=$1
        """, alias)
    return dict(row) if row else {}


@app.get("/api/alltime")
async def get_alltime_all():
    """สถิติ all-time ของทุก account สำหรับแสดงบน overview"""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                alias,
                MAX(drawdown_pct)   as max_drawdown_pct,
                MAX(profit)         as max_profit,
                MIN(profit)         as min_profit,
                MIN(margin_level)   as min_margin_level
            FROM snapshots GROUP BY alias
        """)
    return [dict(r) for r in rows]


# ===========================
# DASHBOARD (Serve HTML)
# ===========================
@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Serve Dashboard"""
    try:
        with open("dashboard.html", "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    except FileNotFoundError:
        return HTMLResponse("<h1>Dashboard not found. Place dashboard.html next to server.py</h1>")


# ===========================
# MAIN
# ===========================
if __name__ == "__main__":
    import uvicorn
    print(f"""
╔══════════════════════════════════════════╗
║         MT5 Monitor Server               ║
║  http://localhost:{PORT}                    ║
║  Dashboard: http://localhost:{PORT}/        ║
║  DB: PostgreSQL                          ║
╚══════════════════════════════════════════╝
""")
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
