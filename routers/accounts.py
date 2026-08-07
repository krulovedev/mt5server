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

@router.get("/api/realized-profits")
async def get_stats_realized():
    """คำนวณกำไร realized โดยใช้ snapshot แรกสุดในฐานข้อมูลเป็น baseline (ไม่นับก่อนเริ่มบันทึก)"""
    global last_bals_update, cached_historical
    now = datetime.now(db.TZ_BANGKOK)
    
    if last_bals_update is None or (now - last_bals_update).total_seconds() > 300:
        async with db.pool.acquire() as conn:
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).strftime('%Y-%m-%dT%H:%M:%S')
            monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
            week_start = monday.strftime('%Y-%m-%dT%H:%M:%S')
            
            new_cache = {}
            for alias in db.latest_cache.keys():
                current_w = db.latest_cache[alias].get("withdrawal", 0.0) or 0.0
                current_d = db.latest_cache[alias].get("net_deposit", 0.0) or 0.0
                
                # Snapshot แรกสุดในฐานข้อมูล = baseline สำหรับ balance
                row_first = await conn.fetchrow(
                    "SELECT balance, withdrawal, net_deposit FROM snapshots WHERE alias=$1 ORDER BY ts ASC LIMIT 1",
                    alias
                )
                
                # หา withdrawal baseline ที่แท้จริง:
                # หา withdrawal/deposit baseline ที่แท้จริง
                wf_value = row_first["withdrawal"] if row_first else None
                df_value = row_first["net_deposit"] if row_first else None
                
                if row_first and (wf_value is None or wf_value == 0) and current_w > 0:
                    row_first_real_w = await conn.fetchrow(
                        "SELECT withdrawal FROM snapshots WHERE alias=$1 AND withdrawal > 0 ORDER BY ts ASC LIMIT 1",
                        alias
                    )
                    if row_first_real_w:
                        wf_value = row_first_real_w["withdrawal"]
                        
                if row_first and (df_value is None or df_value == 0) and current_d > 0:
                    row_first_real_d = await conn.fetchrow(
                        "SELECT net_deposit FROM snapshots WHERE alias=$1 AND net_deposit > 0 ORDER BY ts ASC LIMIT 1",
                        alias
                    )
                    if row_first_real_d:
                        df_value = row_first_real_d["net_deposit"]
                
                # Snapshot ก่อนต้นวัน
                row_today = await conn.fetchrow(
                    "SELECT balance, withdrawal, net_deposit FROM snapshots WHERE alias=$1 AND ts < $2 ORDER BY ts DESC LIMIT 1",
                    alias, today_start
                )
                # Snapshot ก่อนต้นสัปดาห์
                row_week = await conn.fetchrow(
                    "SELECT balance, withdrawal, net_deposit FROM snapshots WHERE alias=$1 AND ts < $2 ORDER BY ts DESC LIMIT 1",
                    alias, week_start
                )
                # fallback ไปใช้ first snapshot ถ้าไม่มีก่อนต้นวัน/อาทิตย์
                if not row_today:
                    row_today = row_first
                if not row_week:
                    row_week = row_first
                
                # สำหรับ today/week withdrawal baseline ก็ต้องแก้เช่นกัน
                wt_value = row_today["withdrawal"] if row_today else None
                ww_value = row_week["withdrawal"]  if row_week else None
                dt_value = row_today["net_deposit"] if row_today else None
                dw_value = row_week["net_deposit"]  if row_week else None
                
                # ถ้า baseline เป็น 0 (จากค่าเริ่มต้นก่อนเริ่มเก็บข้อมูล) ให้ใช้ค่าจริงแรกสุดแทน
                if wt_value is not None and wt_value == 0 and current_w > 0 and wf_value:
                    wt_value = wf_value
                if ww_value is not None and ww_value == 0 and current_w > 0 and wf_value:
                    ww_value = wf_value
                
                if dt_value is not None and dt_value == 0 and current_d > 0 and df_value:
                    dt_value = df_value
                if dw_value is not None and dw_value == 0 and current_d > 0 and df_value:
                    dw_value = df_value
                
                new_cache[alias] = {
                    "bf": row_first["balance"]    if row_first else None,
                    "wf": wf_value,
                    "df": df_value or 0.0,
                    "bt": row_today["balance"]    if row_today else None,
                    "wt": wt_value,
                    "dt": dt_value or 0.0,
                    "bw": row_week["balance"]     if row_week else None,
                    "ww": ww_value,
                    "dw": dw_value or 0.0,
                }
            cached_historical = new_cache
            last_bals_update = now
            
    result = {}
    for alias, data in db.latest_cache.items():
        hist = cached_historical.get(alias, {})
        
        current_bal        = data.get("balance", 0.0)
        current_withdrawal = data.get("withdrawal", 0.0)
        current_deposit    = data.get("net_deposit", 0.0)
        
        # Baseline = snapshot แรกสุด
        bf = hist.get("bf")
        wf = hist.get("wf")
        df = hist.get("df", 0.0)
        if bf is None:
            result[alias] = {"realized_today": None, "realized_week": None, "realized_all": None}
            continue
        wf = wf or 0.0
        
        # Today/Week baselines (fallback = first snapshot)
        bt = hist.get("bt") if hist.get("bt") is not None else bf
        wt = hist.get("wt") if hist.get("wt") is not None else wf
        dt = hist.get("dt", 0.0)
        bw = hist.get("bw") if hist.get("bw") is not None else bf
        ww = hist.get("ww") if hist.get("ww") is not None else wf
        dw = hist.get("dw", 0.0)
        
        # สูตร: (balance + withdrawal - net_deposit) - (prev_balance + prev_withdrawal - prev_deposit)
        # ตัดยอดฝากเงิน (deposit) ออกจากกำไร เพื่อให้ได้กำไรที่แท้จริง
        result[alias] = {
            "realized_today":  (current_bal + current_withdrawal - current_deposit) - (bt + wt - dt),
            "realized_week":   (current_bal + current_withdrawal - current_deposit) - (bw + ww - dw),
            "realized_all":    (current_bal + current_withdrawal - current_deposit) - (bf + wf - df),
            "net_withdrawal":  current_withdrawal - wf,    # ถอนหลังจากเริ่มบันทึกเท่านั้น
            "net_deposit_since": current_deposit - df,     # ฝากหลังจากเริ่มบันทึกเท่านั้น
            "baseline_withdrawal": wf,  # ยอดถอนสะสม ณ snapshot แรก (ก่อนเริ่มบันทึก)
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
