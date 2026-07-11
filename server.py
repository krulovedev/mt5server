"""
MT5 Monitor Server
==================
FastAPI + SQLite server สำหรับรับข้อมูลจาก MT5 หลาย Account
รองรับ Windows, ใช้ทรัพยากรน้อย

Requirements:
    pip install fastapi uvicorn aiosqlite pydantic

Run:
    python server.py
    หรือ uvicorn server:app --host 0.0.0.0 --port 8000
"""
from flask import jsonify
import requests
import asyncio
import json
import os
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

import aiosqlite
from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# ===========================
# CONFIG
# ===========================
DB_PATH     = "mt5_monitor.db"
SECRET_KEY  = "mysecretkey"          # ต้องตรงกับ MQL5
MAX_HISTORY = 100_000                # เก็บ record สูงสุดต่อ account
HOST        = "0.0.0.0"
PORT        = 8000

# ===========================
# APP SETUP
# ===========================
app = FastAPI(title="MT5 Monitor", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===========================
# DATABASE SETUP
# ===========================
def init_db():
    """สร้างตารางถ้ายังไม่มี"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # ตาราง accounts config
    c.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            alias           TEXT PRIMARY KEY,
            display_name    TEXT DEFAULT '',
            account_number  INTEGER,
            broker          TEXT,
            server          TEXT,
            currency        TEXT,
            leverage        INTEGER,
            initial_balance REAL DEFAULT 10000,
            note            TEXT DEFAULT '',
            active          INTEGER DEFAULT 1,
            created_at      TEXT DEFAULT (datetime('now'))
        )
    """)

    # ตาราง snapshots (ข้อมูลที่ส่งมาทุกนาที)
    c.execute("""
        CREATE TABLE IF NOT EXISTS snapshots (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            alias           TEXT NOT NULL,
            account_number  INTEGER,
            balance         REAL,
            equity          REAL,
            margin          REAL,
            free_margin     REAL,
            margin_level    REAL,
            profit          REAL,
            credit          REAL,
            initial_balance REAL,
            drawdown_amount REAL,
            drawdown_pct    REAL,
            equity_dd_pct   REAL,
            open_orders     INTEGER,
            buy_orders      INTEGER DEFAULT 0,
            sell_orders     INTEGER DEFAULT 0,
            total_lots      REAL,
            ts              TEXT NOT NULL,
            received_at     TEXT DEFAULT (datetime('now'))
        )
    """)

    # Migration: เพิ่ม column ถ้ายังไม่มี
    try:
        c.execute("ALTER TABLE snapshots ADD COLUMN buy_orders INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE snapshots ADD COLUMN sell_orders INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE snapshots ADD COLUMN buy_lots REAL DEFAULT 0.0")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE snapshots ADD COLUMN sell_lots REAL DEFAULT 0.0")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE accounts ADD COLUMN display_name TEXT DEFAULT ''")
    except Exception:
        pass

    # Index สำหรับ query เร็ว
    c.execute("CREATE INDEX IF NOT EXISTS idx_snap_alias_ts ON snapshots(alias, ts DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_snap_ts ON snapshots(ts DESC)")

    conn.commit()
    conn.close()
    print(f"[DB] ฐานข้อมูลพร้อมใช้งาน: {DB_PATH}")


init_db()


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
    """โหลดข้อมูลล่าสุดจาก DB เข้า Cache ตอนเปิด Server"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            # ดึง account ทั้งหมด
            async with db.execute("SELECT alias, display_name, active FROM accounts") as cur:
                accounts = await cur.fetchall()
            
            for acc in accounts:
                alias = acc["alias"]
                # ดึง snapshot ล่าสุดของแต่ละ account
                async with db.execute("SELECT * FROM snapshots WHERE alias=? ORDER BY ts DESC LIMIT 1", (alias,)) as cur:
                    snap = await cur.fetchone()
                
                if snap:
                    latest_cache[alias] = {
                        "alias": alias,
                        "display_name": acc["display_name"] or alias,
                        "account_number": snap["account_number"],
                        "broker": "", # อาจจะไม่มีใน snapshot
                        "currency": "USD",
                        "leverage": 100,
                        "balance": snap["balance"],
                        "equity": snap["equity"],
                        "margin": snap["margin"],
                        "free_margin": snap["free_margin"],
                        "margin_level": snap["margin_level"],
                        "profit": snap["profit"],
                        "initial_balance": snap["initial_balance"],
                        "drawdown_amount": snap["drawdown_amount"],
                        "drawdown_pct": snap["drawdown_pct"],
                        "equity_dd_pct": snap["equity_dd_pct"],
                        "open_orders": snap["open_orders"],
                        "buy_orders": snap["buy_orders"],
                        "sell_orders": snap["sell_orders"],
                        "total_lots": snap["total_lots"],
                        "buy_lots": snap.keys().__contains__("buy_lots") and snap["buy_lots"] or 0.0,
                        "sell_lots": snap.keys().__contains__("sell_lots") and snap["sell_lots"] or 0.0,
                        "timestamp": snap["ts"],
                        "received_at": datetime.now().isoformat(),
                        "active": acc["active"],
                    }
        print(f"[DB] โหลดข้อมูลลง Cache สำเร็จ: {len(latest_cache)} accounts")
    except Exception as e:
        print(f"[DB] Error loading cache: {e}")



# ===========================
# API ENDPOINTS
# ===========================

@app.post("/api/data")
async def receive_data(payload: MT5DataPayload):
    """รับข้อมูลจาก MQL5 EA"""
    # ตรวจ Secret Key
    if payload.secret != SECRET_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

    ts = payload.timestamp or datetime.utcnow().isoformat()

    # บันทึกลง DB
    async with aiosqlite.connect(DB_PATH) as db:
        # Upsert account info (ไม่อัพเดท display_name)
        await db.execute("""
            INSERT INTO accounts (alias, account_number, broker, server, currency, leverage, initial_balance)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(alias) DO UPDATE SET
                account_number = excluded.account_number,
                broker = excluded.broker,
                server = excluded.server,
                currency = excluded.currency,
                leverage = excluded.leverage
        """, (
            payload.alias, payload.account_number, payload.broker,
            payload.server, payload.currency, payload.leverage,
            payload.initial_balance
        ))

        # Insert snapshot
        await db.execute("""
            INSERT INTO snapshots
            (alias, account_number, balance, equity, margin, free_margin, margin_level,
             profit, credit, initial_balance, drawdown_amount, drawdown_pct, equity_dd_pct,
             open_orders, buy_orders, sell_orders, total_lots, buy_lots, sell_lots, ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            payload.alias, payload.account_number,
            payload.balance, payload.equity, payload.margin, payload.free_margin,
            payload.margin_level, payload.profit, payload.credit, payload.initial_balance,
            payload.drawdown_amount, payload.drawdown_pct, payload.equity_drawdown_pct,
            payload.open_orders, payload.buy_orders, payload.sell_orders, payload.total_lots,
            payload.buy_lots, payload.sell_lots, ts
        ))

        # ลบข้อมูลเก่าเกิน MAX_HISTORY ต่อ account (ประหยัด disk)
        await db.execute("""
            DELETE FROM snapshots WHERE alias = ? AND id NOT IN (
                SELECT id FROM snapshots WHERE alias = ? ORDER BY id DESC LIMIT ?
            )
        """, (payload.alias, payload.alias, MAX_HISTORY))

        await db.commit()

    # อัพเดท Cache
    # ดึง display_name จาก DB
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT display_name, active FROM accounts WHERE alias=?", (payload.alias,)) as cur:
            acc_row = await cur.fetchone()
    display_name = (acc_row["display_name"] if acc_row and acc_row["display_name"] else payload.alias)
    active = acc_row["active"] if acc_row else 1

    latest_cache[payload.alias] = {
        "alias": payload.alias,
        "display_name": display_name,
        "account_number": payload.account_number,
        "broker": payload.broker,
        "currency": payload.currency,
        "leverage": payload.leverage,
        "balance": payload.balance,
        "equity": payload.equity,
        "margin": payload.margin,
        "free_margin": payload.free_margin,
        "margin_level": payload.margin_level,
        "profit": payload.profit,
        "initial_balance": payload.initial_balance,
        "drawdown_amount": payload.drawdown_amount,
        "drawdown_pct": payload.drawdown_pct,
        "equity_dd_pct": payload.equity_drawdown_pct,
        "open_orders": payload.open_orders,
        "buy_orders": payload.buy_orders,
        "sell_orders": payload.sell_orders,
        "total_lots": payload.total_lots,
        "buy_lots": payload.buy_lots,
        "sell_lots": payload.sell_lots,
        "timestamp": ts,
        "received_at": datetime.now().isoformat(),
        "active": active,
    }

    return {"status": "ok", "alias": payload.alias}


@app.get("/api/accounts")
async def get_accounts():
    """รายชื่อ accounts ทั้งหมด"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM accounts ORDER BY alias"
        ) as cursor:
            rows = await cursor.fetchall()
    return [dict(r) for r in rows]


@app.get("/api/balance")
async def get_accounts():
    API_URL = "http://127.0.0.1:5000/api/latest"

    response = requests.get(API_URL)

    data = response.json()

    return data

@app.get("/api/latest")
async def get_latest_all():
    """ข้อมูลล่าสุดของทุก account (realtime จาก cache) - เฉพาะ active"""
    result = []
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT alias, active, display_name FROM accounts") as cur:
            acc_rows = await cur.fetchall()
    acc_map = {r["alias"]: dict(r) for r in acc_rows}

    for alias, data in latest_cache.items():
        acc_info = acc_map.get(alias, {})
        active = acc_info.get("active", 1)
        display_name = acc_info.get("display_name", "") or alias
        entry = dict(data)
        entry["active"] = active
        entry["display_name"] = display_name
        result.append(entry)
    return result


@app.get("/api/latest/{alias}")
async def get_latest_one(alias: str):
    """ข้อมูลล่าสุดของ account เดียว"""
    if alias in latest_cache:
        return latest_cache[alias]
    # Fallback จาก DB
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM snapshots WHERE alias=? ORDER BY ts DESC LIMIT 1",
            (alias,)
        ) as cursor:
            row = await cursor.fetchone()
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
    # Default: 24 ชั่วโมงล่าสุด
    if not end:
        end = datetime.utcnow().isoformat()
    if not start:
        start = (datetime.utcnow() - timedelta(hours=24)).isoformat()

    # เลือก fields ที่ปลอดภัย
    allowed = {"balance","equity","margin","free_margin","margin_level","profit",
               "drawdown_amount","drawdown_pct","equity_dd_pct","open_orders",
               "buy_orders","sell_orders","total_lots","buy_lots","sell_lots","ts"}
    fields = [f for f in field.split(",") if f.strip() in allowed]
    if not fields:
        fields = ["balance","equity","drawdown_pct","profit","ts"]
    if "ts" not in fields:
        fields.append("ts")

    cols = ", ".join(fields)

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            f"SELECT {cols} FROM snapshots WHERE alias=? AND ts BETWEEN ? AND ? ORDER BY ts ASC LIMIT ?",
            (alias, start, end, limit)
        ) as cursor:
            rows = await cursor.fetchall()

    return {
        "alias": alias,
        "start": start,
        "end": end,
        "count": len(rows),
        "data": [dict(r) for r in rows]
    }


@app.get("/api/summary")
async def get_summary():
    """สรุปภาพรวมทุก account"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT alias, COUNT(*) as total_snapshots,
                   MIN(ts) as first_seen, MAX(ts) as last_seen
            FROM snapshots GROUP BY alias
        """) as cursor:
            rows = await cursor.fetchall()
    summary = [dict(r) for r in rows]
    # เพิ่มข้อมูล latest จาก cache
    for s in summary:
        if s["alias"] in latest_cache:
            s.update({
                "balance": latest_cache[s["alias"]]["balance"],
                "equity":  latest_cache[s["alias"]]["equity"],
                "drawdown_pct": latest_cache[s["alias"]]["drawdown_pct"],
                "profit": latest_cache[s["alias"]]["profit"],
            })
    return summary


@app.patch("/api/accounts/{alias}")
async def update_account(alias: str, config: AccountConfig):
    """อัพเดท config ของ account"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE accounts SET initial_balance=?, note=? WHERE alias=?",
            (config.initial_balance, config.note, alias)
        )
        await db.commit()
    if alias in latest_cache:
        latest_cache[alias]["initial_balance"] = config.initial_balance
    return {"status": "updated", "alias": alias}


@app.put("/api/accounts/{alias}/rename")
async def rename_account(alias: str, body: AccountRename):
    """เปลี่ยนชื่อที่แสดงของ account"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE accounts SET display_name=? WHERE alias=?",
            (body.display_name, alias)
        )
        await db.commit()
    if alias in latest_cache:
        latest_cache[alias]["display_name"] = body.display_name
    return {"status": "renamed", "alias": alias, "display_name": body.display_name}


@app.put("/api/accounts/{alias}/toggle")
async def toggle_account(alias: str):
    """ซ่อน/แสดง account"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT active FROM accounts WHERE alias=?", (alias,)) as cur:
            row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Account not found")
        new_active = 0 if row["active"] else 1
        await db.execute("UPDATE accounts SET active=? WHERE alias=?", (new_active, alias))
        await db.commit()
    if alias in latest_cache:
        latest_cache[alias]["active"] = new_active
    return {"status": "ok", "alias": alias, "active": new_active}


@app.delete("/api/accounts/{alias}")
async def delete_account(alias: str):
    """ลบ account และ snapshots ทั้งหมด"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM snapshots WHERE alias=?", (alias,))
        await db.execute("DELETE FROM accounts WHERE alias=?", (alias,))
        await db.commit()
    if alias in latest_cache:
        del latest_cache[alias]
    return {"status": "deleted", "alias": alias}


@app.get("/api/stats/{alias}")
async def get_stats(alias: str, days: int = Query(7, ge=1, le=90)):
    """สถิติสรุปของ account ในช่วง N วัน"""
    start = (datetime.utcnow() - timedelta(days=days)).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT
                COUNT(*) as snapshots,
                AVG(balance) as avg_balance,
                MAX(balance) as max_balance,
                MIN(balance) as min_balance,
                AVG(equity) as avg_equity,
                MAX(equity) as max_equity,
                MIN(equity) as min_equity,
                MAX(drawdown_pct) as max_drawdown_pct,
                AVG(drawdown_pct) as avg_drawdown_pct,
                MIN(drawdown_pct) as min_drawdown_pct,
                MAX(profit) as max_profit,
                MIN(profit) as min_profit,
                AVG(profit) as avg_profit,
                MAX(open_orders) as max_open_orders,
                MIN(open_orders) as min_open_orders,
                AVG(margin_level) as avg_margin_level,
                MAX(margin_level) as max_margin_level,
                MIN(margin_level) as min_margin_level,
                MAX(total_lots) as max_total_lots,
                MIN(total_lots) as min_total_lots,
                AVG(total_lots) as avg_total_lots
            FROM snapshots WHERE alias=? AND ts >= ?
        """, (alias, start)) as cursor:
            row = await cursor.fetchone()
    return dict(row) if row else {}


@app.get("/api/alltime/{alias}")
async def get_alltime_stats(alias: str):
    """สถิติ all-time ของ account ตั้งแต่เริ่มเก็บข้อมูล"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT
                COUNT(*) as snapshots,
                MIN(ts) as first_seen,
                MAX(ts) as last_seen,
                MAX(drawdown_pct) as max_drawdown_pct,
                MIN(drawdown_pct) as min_drawdown_pct,
                MAX(profit) as max_profit,
                MIN(profit) as min_profit,
                MAX(balance) as max_balance,
                MIN(balance) as min_balance,
                MIN(margin_level) as min_margin_level,
                MAX(margin_level) as max_margin_level,
                MAX(open_orders) as max_open_orders,
                MAX(equity) as max_equity,
                MIN(equity) as min_equity
            FROM snapshots WHERE alias=?
        """, (alias,)) as cursor:
            row = await cursor.fetchone()
    return dict(row) if row else {}


@app.get("/api/alltime")
async def get_alltime_all():
    """สถิติ all-time ของทุก account สำหรับแสดงบน overview"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT
                alias,
                MAX(drawdown_pct) as max_drawdown_pct,
                MAX(profit) as max_profit,
                MIN(profit) as min_profit,
                MIN(margin_level) as min_margin_level
            FROM snapshots GROUP BY alias
        """) as cursor:
            rows = await cursor.fetchall()
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
╚══════════════════════════════════════════╝
""")
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
