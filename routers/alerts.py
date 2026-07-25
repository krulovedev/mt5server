from fastapi import APIRouter, HTTPException
from datetime import datetime
import httpx
import asyncio
import database as db
from models import AlertSettingsPayload, AccountAlertPayload

router = APIRouter()

async def send_telegram(message: str, bot_token: str, chat_id: str) -> bool:
    if not bot_token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=5.0)
            return resp.status_code == 200
    except Exception as e:
        print(f"[Telegram Error] {e}")
        return False

@router.get("/api/alerts/settings")
async def get_alerts_settings():
    """ดู alert settings"""
    try:
        async with db.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM alert_settings ORDER BY id LIMIT 1")
    except:
        row = None
    settings = dict(row) if row else {}
    
    async with db.pool.acquire() as conn:
        acc_rows = await conn.fetch("SELECT alias, enabled FROM account_alert_settings")
    acc_settings = {r["alias"]: bool(r["enabled"]) for r in acc_rows}
    
    result = dict(settings)
    result["has_token"] = bool(result.get("bot_token", ""))
    result["account_settings"] = acc_settings
    return result

@router.post("/api/alerts/settings")
async def update_alerts_settings(payload: AlertSettingsPayload):
    """อัพเดท global alert settings"""
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id, bot_token, chat_id FROM alert_settings ORDER BY id LIMIT 1")
        if row:
            bot_token = payload.bot_token if payload.bot_token else row["bot_token"]
            chat_id = payload.chat_id if payload.chat_id else row["chat_id"]
            await conn.execute(
                "UPDATE alert_settings SET global_enabled=$1, bot_token=$2, chat_id=$3, updated_at=NOW() WHERE id=$4",
                payload.global_enabled, bot_token, chat_id, row["id"]
            )
        else:
            await conn.execute(
                "INSERT INTO alert_settings (global_enabled, bot_token, chat_id) VALUES ($1, $2, $3)",
                payload.global_enabled, payload.bot_token, payload.chat_id
            )
    return {"status": "ok"}

@router.post("/api/alerts/account")
async def update_account_alert(payload: AccountAlertPayload):
    """เปิด/ปิดการแจ้งเตือนของ account"""
    async with db.pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO account_alert_settings (alias, enabled, updated_at)
            VALUES ($1, $2, NOW())
            ON CONFLICT (alias) DO UPDATE SET enabled=$2, updated_at=NOW()
            """,
            payload.alias, payload.enabled
        )
    return {"status": "ok", "alias": payload.alias, "enabled": payload.enabled}

@router.post("/api/alerts/test")
async def test_alert():
    """ทดสอบส่ง Telegram"""
    try:
        async with db.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM alert_settings ORDER BY id LIMIT 1")
    except:
        row = None
    settings = dict(row) if row else {}
    bot_token = settings.get("bot_token", "") or db.TELEGRAM_BOT_TOKEN
    chat_id   = settings.get("chat_id", "")   or db.TELEGRAM_CHAT_ID
    
    now = datetime.now(db.TZ_BANGKOK)
    msg = (
        f"🔔 <b>MT5 Monitor — Test Alert</b>\n"
        f"การแจ้งเตือนทำงานปกติ ✅\n"
        f"เวลา: {now.strftime('%Y-%m-%d %H:%M:%S')} UTC+7"
    )
    ok = await send_telegram(msg, bot_token, chat_id)
    if ok:
        return {"status": "ok", "message": "ส่งข้อความทดสอบสำเร็จ"}
    raise HTTPException(status_code=500, detail="ไม่สามารถส่ง Telegram ได้ ตรวจสอบ Bot Token และ Chat ID")

@router.get("/api/alerts/status")
async def get_alert_status():
    """ดูสถานะการแจ้งเตือนปัจจุบันของทุก account"""
    now = datetime.now(db.TZ_BANGKOK)
    result = []
    for alias, state in db.alert_state.items():
        data = db.latest_cache.get(alias, {})
        received_str = data.get("received_at", "")
        if received_str:
            try:
                rt = datetime.strptime(received_str, '%Y-%m-%dT%H:%M:%S')
                rt = db.TZ_BANGKOK.localize(rt)
                elapsed = (now - rt).total_seconds() / 60
            except:
                elapsed = 0
        else:
            elapsed = 0
            
        result.append({
            "alias": alias,
            "display_name": data.get("display_name", alias),
            "alert_count": state.get("alert_count", 0),
            "is_offline": state.get("alert_count", 0) > 0,
            "elapsed_minutes": int(elapsed)
        })
    return result
