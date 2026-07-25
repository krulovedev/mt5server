from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import asyncio
from datetime import datetime
import os

import database as db
from routers import data, accounts, history, alerts

# ===========================
# FASTAPI APP
# ===========================
app = FastAPI(title="MT5 Monitor API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers
app.include_router(data.router)
app.include_router(accounts.router)
app.include_router(history.router)
app.include_router(alerts.router)

# Mount Static Files (สำหรับ frontend ที่แยกไฟล์)
# หากคุณใช้ frontend แบบ single page หรือ folder static สามารถตั้งค่าแบบนี้:
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/tabs", StaticFiles(directory="tabs"), name="tabs")

# ===========================
# BACKGROUND TASKS
# ===========================
async def alert_monitor_loop():
    """ตรวจสอบว่ามีการส่งข้อมูลมาภายในเวลาที่กำหนดหรือไม่"""
    while True:
        await asyncio.sleep(60)
        try:
            async with db.pool.acquire() as conn:
                row = await conn.fetchrow("SELECT global_enabled, bot_token, chat_id FROM alert_settings ORDER BY id LIMIT 1")
            
            if not row or not row["global_enabled"]:
                continue
            
            bot_token = row["bot_token"] or db.TELEGRAM_BOT_TOKEN
            chat_id   = row["chat_id"] or db.TELEGRAM_CHAT_ID
            if not bot_token or not chat_id:
                continue

            async with db.pool.acquire() as conn:
                acc_rows = await conn.fetch("SELECT alias, enabled FROM account_alert_settings")
            acc_settings = {r["alias"]: bool(r["enabled"]) for r in acc_rows}

            now = datetime.now(db.TZ_BANGKOK)
            for alias, data_dict in db.latest_cache.items():
                if acc_settings.get(alias, True) is False:
                    continue

                display_name = data_dict.get("display_name", alias)
                received_str = data_dict.get("received_at", "")
                if not received_str:
                    continue
                
                try:
                    rt = datetime.strptime(received_str, '%Y-%m-%dT%H:%M:%S')
                    rt = db.TZ_BANGKOK.localize(rt)
                    elapsed_minutes = (now - rt).total_seconds() / 60
                except:
                    continue
                
                if alias not in db.alert_state:
                    db.alert_state[alias] = {"alert_count": 0, "last_alert_time": None}
                
                state = db.alert_state[alias]
                
                if elapsed_minutes >= 5:
                    count = state["alert_count"]
                    last_alert = state["last_alert_time"]
                    
                    should_alert = False
                    if count < 3:
                        should_alert = True
                    else:
                        if last_alert:
                            mins_since_last = (now - last_alert).total_seconds() / 60
                            if mins_since_last >= 60:
                                should_alert = True
                                
                    if should_alert:
                        msg = (
                            f"⚠️ <b>การเชื่อมต่อขาดหาย</b>\n"
                            f"บัญชี: <b>{display_name}</b>\n"
                            f"ขาดการติดต่อนาน: {int(elapsed_minutes)} นาที\n"
                            f"อัปเดตล่าสุด: {received_str}"
                        )
                        ok = await alerts.send_telegram(msg, bot_token, chat_id)
                        if ok:
                            state["alert_count"] += 1
                            state["last_alert_time"] = now
                else:
                    if state["alert_count"] > 0:
                        msg = (
                            f"✅ <b>การเชื่อมต่อกลับมาปกติ</b>\n"
                            f"บัญชี: <b>{display_name}</b>\n"
                            f"รับข้อมูลล่าสุด: {received_str}"
                        )
                        await alerts.send_telegram(msg, bot_token, chat_id)
                    state["alert_count"] = 0
                    state["last_alert_time"] = None
        except Exception as e:
            print(f"[Alert Loop Error] {e}")

# ===========================
# LIFESPAN (Startup / Shutdown)
# ===========================
@app.on_event("startup")
async def startup():
    await db.get_db_pool()
    asyncio.create_task(alert_monitor_loop())
    print("[System] API Server กำลังทำงาน...")

@app.on_event("shutdown")
async def shutdown():
    await db.close_db_pool()

# ===========================
# FRONTEND ROUTE
# ===========================
@app.get("/")
def serve_index():
    return FileResponse("index.html")

if __name__ == "__main__":
    import uvicorn
    # ตั้งค่ารันได้โดยตรง (ถ้าไม่ได้ใช้ uvicorn command)
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
