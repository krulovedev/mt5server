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

@router.get("/api/latest")
async def get_latest():
    """ข้อมูลล่าสุดของทุก account สำหรับ overview"""
    async with db.pool.acquire() as conn:
        acc_rows = await conn.fetch("SELECT alias, active, display_name, initial_balance FROM accounts")
        acc_map = {r["alias"]: dict(r) for r in acc_rows}

        now = datetime.now(db.TZ_BANGKOK)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).strftime('%Y-%m-%dT%H:%M:%S')
        monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = monday.strftime('%Y-%m-%dT%H:%M:%S')

        bals_map = {}
        for alias in db.latest_cache.keys():
            row_today = await conn.fetchrow("SELECT balance FROM snapshots WHERE alias=$1 AND ts < $2 ORDER BY ts DESC LIMIT 1", alias, today_start)
            row_week = await conn.fetchrow("SELECT balance FROM snapshots WHERE alias=$1 AND ts < $2 ORDER BY ts DESC LIMIT 1", alias, week_start)
            if not row_today:
                row_today = await conn.fetchrow("SELECT balance FROM snapshots WHERE alias=$1 ORDER BY ts ASC LIMIT 1", alias)
            if not row_week:
                row_week = await conn.fetchrow("SELECT balance FROM snapshots WHERE alias=$1 ORDER BY ts ASC LIMIT 1", alias)
            bals_map[alias] = (row_today["balance"] if row_today else None, row_week["balance"] if row_week else None)

    result = []
    for alias, data in db.latest_cache.items():
        acc_info   = acc_map.get(alias, {})
        active     = acc_info.get("active", 1)
        display_name = acc_info.get("display_name", "") or alias
        initial_balance = acc_info.get("initial_balance", data.get("initial_balance", 0))

        bt, bw = bals_map.get(alias, (None, None))
        bal_today = bt if bt is not None else initial_balance
        bal_week = bw if bw is not None else initial_balance
        
        current_bal = data.get("balance", 0)
        
        entry = dict(data)
        entry["active"]       = active
        entry["display_name"] = display_name
        entry["realized_today"] = current_bal - bal_today
        entry["realized_week"] = current_bal - bal_week
        entry["realized_all"] = current_bal - initial_balance
        result.append(entry)
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
