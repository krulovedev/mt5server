from fastapi import APIRouter, HTTPException
from datetime import datetime
import database as db
from models import MT5DataPayload

router = APIRouter()

@router.post("/api/data")
async def receive_data(payload: MT5DataPayload):
    """รับข้อมูลจาก MQL5 EA"""
    if payload.secret != db.SECRET_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

    ts = payload.timestamp or datetime.now(db.TZ_BANGKOK).strftime('%Y-%m-%dT%H:%M:%S')
    ts = ts.replace('.', '-').replace(' ', 'T')

    async with db.pool.acquire() as conn:
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
        "timestamp":       ts,
        "received_at":     datetime.now(db.TZ_BANGKOK).strftime('%Y-%m-%dT%H:%M:%S'),
        "active":          active,
    }

    return {"status": "ok", "alias": payload.alias}
