from fastapi import APIRouter, HTTPException
from datetime import datetime
import database as db
from models import MT5DataPayload

router = APIRouter()

# คอลัมน์สถิติชุดใหม่จาก EA v2.0 (ถ้า EA เก่าส่งมาไม่ครบ จะเป็น NULL)
EXT_COLS = [
    "pl_today", "pl_week", "pl_total",
    "closed_pl_today", "closed_pl_week", "closed_pl_total",
    "vol_today", "vol_week", "vol_total",
    "dd_today", "dd_today_at", "dd_today_lots",
    "dd_week", "dd_week_at", "dd_week_lots",
    "dd_total", "dd_total_at", "dd_total_lots",
    "stats_start",
]
BASE_PLACEHOLDERS = 22   # จำนวนค่าพื้นฐานก่อนคอลัมน์เสริม (ts คือ $22)

@router.post("/api/data")
async def receive_data(payload: MT5DataPayload):
    """รับข้อมูลจาก MQL5 EA"""
    # trim เพื่อกันช่องว่าง/ขึ้นบรรทัดใหม่ที่ติดมาจากการ copy-paste ในช่อง input ของ MT5
    received = (payload.secret or "").strip()
    if received not in db.SECRET_KEYS:
        print(
            f"[AUTH] 401 alias={payload.alias} len={len(received)} "
            f"head={received[:4]!r} tail={received[-2:]!r} "
            f"(server keys len={[len(k) for k in db.SECRET_KEYS]})"
        )
        raise HTTPException(status_code=401, detail="Unauthorized")

    ts = payload.timestamp or datetime.now(db.TZ_BANGKOK).strftime('%Y-%m-%dT%H:%M:%S')
    ts = ts.replace('.', '-').replace(' ', 'T')

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            # ป้องกัน alias ซ้ำซ้อนสำหรับ account_number เดียวกัน
            existing_account = await conn.fetchrow(
                "SELECT alias FROM accounts WHERE account_number = $1", payload.account_number
            )
            if existing_account and existing_account["alias"] != payload.alias:
                payload.alias = existing_account["alias"]

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
            ext_cols  = ", ".join(EXT_COLS)
            ext_marks = ", ".join(f"${BASE_PLACEHOLDERS + i}" for i in range(1, len(EXT_COLS) + 1))
            ext_vals  = [getattr(payload, c) for c in EXT_COLS]

            await conn.execute(f"""
                INSERT INTO snapshots
                    (alias, account_number, balance, equity, margin, free_margin, margin_level,
                     profit, credit, initial_balance, drawdown_amount, drawdown_pct, equity_dd_pct,
                     open_orders, buy_orders, sell_orders, total_lots, buy_lots, sell_lots, withdrawal, net_deposit, ts,
                     {ext_cols})
                VALUES
                    ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,
                     {ext_marks})
            """,
                payload.alias, payload.account_number,
                payload.balance, payload.equity, payload.margin, payload.free_margin,
                payload.margin_level, payload.profit, payload.credit, payload.initial_balance,
                payload.drawdown_amount, payload.drawdown_pct, payload.equity_drawdown_pct,
                payload.open_orders, payload.buy_orders, payload.sell_orders, payload.total_lots,
                payload.buy_lots, payload.sell_lots, payload.withdrawal, payload.net_deposit, ts,
                *ext_vals
            )

            # ลบข้อมูลเก่าเกิน MAX_HISTORY ต่อ account
            await conn.execute("""
                DELETE FROM snapshots
                WHERE alias = $1 AND id NOT IN (
                    SELECT id FROM snapshots WHERE alias = $1
                    ORDER BY id DESC LIMIT $2
                )
            """, payload.alias, db.MAX_HISTORY)

        # ดึง display_name และ active จาก DB (ในรายการเดิม)
        acc_row = await conn.fetchrow(
            "SELECT display_name, active FROM accounts WHERE alias=$1",
            payload.alias
        )

    display_name = (acc_row["display_name"] if acc_row and acc_row["display_name"] else payload.alias)
    active = acc_row["active"] if acc_row else 1

    db.latest_cache[payload.alias] = {
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
        "withdrawal":      payload.withdrawal,
        "net_deposit":     payload.net_deposit,
        "timestamp":       ts,
        "received_at":     datetime.now(db.TZ_BANGKOK).strftime('%Y-%m-%dT%H:%M:%S'),
        "active":          active,
    }

    # เพิ่มสถิติชุดใหม่ (EA v2.0) เข้า cache เพื่อให้ /api/latest ตอบได้ทันที
    for c in EXT_COLS:
        db.latest_cache[payload.alias][c] = getattr(payload, c)

    return {"status": "ok", "alias": payload.alias}
