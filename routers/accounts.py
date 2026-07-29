from fastapi import APIRouter, HTTPException
import database as db
from models import AccountConfig, AccountRename

router = APIRouter()

@router.get("/api/accounts")
async def get_accounts():
    """รายชื่อ accounts ทั้งหมด"""
    async with db.pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM accounts ORDER BY alias")
    return [dict(r) for r in rows]

from datetime import datetime, timedelta

last_bals_update = None
cached_historical = {}

@router.get("/api/latest")
async def get_latest():
    """ข้อมูลล่าสุดของทุก account สำหรับ overview (Fast)"""
    result = []
    for alias, data in db.latest_cache.items():
        entry = dict(data)
        # ไม่คำนวณ realized เพื่อให้ response เร็วที่สุด frontend จะดึงแยกทีหลัง
        entry["realized_today"] = None
        entry["realized_week"] = None
        entry["realized_all"] = None
        result.append(entry)
    return result

@router.get("/api/stats/realized")
async def get_stats_realized():
    """คำนวณกำไร realized แบบ asynchronous"""
    global last_bals_update, cached_historical
    now = datetime.now(db.TZ_BANGKOK)
    
    if last_bals_update is None or (now - last_bals_update).total_seconds() > 300:
        async with db.pool.acquire() as conn:
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).strftime('%Y-%m-%dT%H:%M:%S')
            monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
            week_start = monday.strftime('%Y-%m-%dT%H:%M:%S')
            
            new_cache = {}
            for alias in db.latest_cache.keys():
                row_today = await conn.fetchrow("SELECT balance, withdrawal FROM snapshots WHERE alias=$1 AND ts < $2 ORDER BY ts DESC LIMIT 1", alias, today_start)
                row_week = await conn.fetchrow("SELECT balance, withdrawal FROM snapshots WHERE alias=$1 AND ts < $2 ORDER BY ts DESC LIMIT 1", alias, week_start)
                if not row_today:
                    row_today = await conn.fetchrow("SELECT balance, withdrawal FROM snapshots WHERE alias=$1 ORDER BY ts ASC LIMIT 1", alias)
                if not row_week:
                    row_week = await conn.fetchrow("SELECT balance, withdrawal FROM snapshots WHERE alias=$1 ORDER BY ts ASC LIMIT 1", alias)
                
                new_cache[alias] = {
                    "bt": row_today["balance"] if row_today else None,
                    "wt": row_today["withdrawal"] if row_today else None,
                    "bw": row_week["balance"] if row_week else None,
                    "ww": row_week["withdrawal"] if row_week else None,
                }
            cached_historical = new_cache
            last_bals_update = now
            
    result = {}
    for alias, data in db.latest_cache.items():
        hist = cached_historical.get(alias, {})
        initial_balance = data.get("initial_balance", 0)
        
        bt = hist.get("bt")
        wt = hist.get("wt")
        bw = hist.get("bw")
        ww = hist.get("ww")
        
        if bt is None: bt = initial_balance
        if wt is None: wt = 0.0
        if bw is None: bw = initial_balance
        if ww is None: ww = 0.0
        
        current_bal = data.get("balance", 0.0)
        current_withdrawal = data.get("withdrawal", 0.0)
        
        result[alias] = {
            "realized_today": (current_bal + current_withdrawal) - (bt + wt),
            "realized_week": (current_bal + current_withdrawal) - (bw + ww),
            "realized_all": (current_bal + current_withdrawal) - initial_balance
        }
    return result

@router.get("/api/latest/{alias}")
async def get_latest_one(alias: str):
    """ข้อมูลล่าสุดของ account เดียว"""
    if alias in db.latest_cache:
        return db.latest_cache[alias]
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM snapshots WHERE alias=$1 ORDER BY ts DESC LIMIT 1",
            alias
        )
    if not row:
        raise HTTPException(status_code=404, detail="Account not found")
    return dict(row)

@router.patch("/api/accounts/{alias}")
async def update_account(alias: str, config: AccountConfig):
    """อัพเดท config ของ account"""
    async with db.pool.acquire() as conn:
        await conn.execute(
            "UPDATE accounts SET initial_balance=$1, note=$2 WHERE alias=$3",
            config.initial_balance, config.note, alias
        )
    if alias in db.latest_cache:
        db.latest_cache[alias]["initial_balance"] = config.initial_balance
    return {"status": "updated", "alias": alias}

@router.put("/api/accounts/{alias}/rename")
async def rename_account(alias: str, body: AccountRename):
    """เปลี่ยนชื่อที่แสดงของ account"""
    async with db.pool.acquire() as conn:
        await conn.execute(
            "UPDATE accounts SET display_name=$1 WHERE alias=$2",
            body.display_name, alias
        )
    if alias in db.latest_cache:
        db.latest_cache[alias]["display_name"] = body.display_name
    return {"status": "renamed", "alias": alias}

@router.put("/api/accounts/{alias}/toggle")
async def toggle_account(alias: str):
    """สลับสถานะแสดง/ซ่อน account"""
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT active FROM accounts WHERE alias=$1", alias)
        if not row:
            raise HTTPException(status_code=404, detail="Account not found")
        new_active = 0 if row["active"] == 1 else 1
        await conn.execute(
            "UPDATE accounts SET active=$1 WHERE alias=$2",
            new_active, alias
        )
    if alias in db.latest_cache:
        db.latest_cache[alias]["active"] = new_active
    return {"status": "ok", "alias": alias, "active": new_active}

@router.delete("/api/accounts/{alias}")
async def delete_account(alias: str):
    """ลบ account และ snapshots ทั้งหมด"""
    async with db.pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM snapshots WHERE alias=$1", alias)
            await conn.execute("DELETE FROM accounts WHERE alias=$1", alias)
    if alias in db.latest_cache:
        del db.latest_cache[alias]
    return {"status": "deleted", "alias": alias}
