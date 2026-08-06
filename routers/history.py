from fastapi import APIRouter, Query
from datetime import datetime, timedelta
from typing import Optional
import database as db

router = APIRouter()

@router.get("/api/history/{alias}")
async def get_history(
    alias: str,
    start: Optional[str] = Query(None, description="เวลาเริ่ม (ISO format)"),
    end:   Optional[str] = Query(None, description="เวลาสิ้นสุด (ISO format)"),
    limit: int = Query(1440, ge=1, le=10000, description="จำนวน record"),
    field: str = Query("balance,equity,drawdown_pct,profit", description="fields ที่ต้องการ")
):
    """ข้อมูลย้อนหลังของ account"""
    if not end:
        end = datetime.now(db.TZ_BANGKOK).strftime('%Y-%m-%dT%H:%M:%S')
    if not start:
        start = (datetime.now(db.TZ_BANGKOK) - timedelta(hours=24)).strftime('%Y-%m-%dT%H:%M:%S')

    allowed = {"balance","equity","margin","free_margin","margin_level","profit",
               "drawdown_amount","drawdown_pct","equity_dd_pct","open_orders",
               "buy_orders","sell_orders","total_lots","buy_lots","sell_lots","ts","withdrawal"}
    fields = [f for f in field.split(",") if f.strip() in allowed]
    if not fields:
        fields = ["balance","equity","drawdown_pct","profit","ts"]
    if "ts" not in fields:
        fields.append("ts")

    cols = ", ".join(fields)

    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT {cols} FROM snapshots WHERE alias=$1 AND ts BETWEEN $2 AND $3 ORDER BY ts ASC LIMIT $4",
            alias, start, end, limit
        )
    return {"alias": alias, "count": len(rows), "data": [dict(r) for r in rows]}

@router.get("/api/history_all/{alias}")
async def get_history_all(
    alias: str,
    limit: int = Query(2000, ge=1, le=10000),
    field: str = Query("balance,equity,drawdown_pct,profit,open_orders,total_lots,ts")
):
    """ดึงข้อมูลทั้งหมดตั้งแต่ต้น (all-time chart)"""
    allowed = {"balance","equity","margin","free_margin","margin_level","profit",
               "drawdown_amount","drawdown_pct","equity_dd_pct","open_orders",
               "buy_orders","sell_orders","total_lots","buy_lots","sell_lots","ts","withdrawal"}
    fields = [f for f in field.split(",") if f.strip() in allowed]
    if not fields:
        fields = ["balance","equity","drawdown_pct","profit","ts"]
    if "ts" not in fields:
        fields.append("ts")
    cols = ", ".join(fields)
    
    async with db.pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM snapshots WHERE alias=$1", alias)
        step = max(1, total // limit)
        rows = await conn.fetch(
            f"""
            SELECT {cols} FROM (
                SELECT {cols}, ROW_NUMBER() OVER (ORDER BY ts ASC) AS rn
                FROM snapshots WHERE alias=$1
            ) sub WHERE rn % $2 = 1
            ORDER BY ts ASC LIMIT $3
            """,
            alias, step, limit
        )
    return {"alias": alias, "count": len(rows), "total": total, "data": [dict(r) for r in rows]}

@router.get("/api/stats/{alias}")
async def get_stats(alias: str, days: int = Query(7, ge=1, le=90)):
    """สถิติสรุปของ account ในช่วง N วัน"""
    start = (datetime.now(db.TZ_BANGKOK) - timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%S')
    async with db.pool.acquire() as conn:
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

@router.get("/api/alltime/{alias}")
async def get_alltime_stats(alias: str):
    """สถิติ all-time ของ account ตั้งแต่เริ่มเก็บข้อมูล"""
    async with db.pool.acquire() as conn:
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

last_alltime_update = None
cached_alltime_summary = []

@router.get("/api/alltime")
async def get_alltime_all():
    """สถิติ all-time ของทุก account สำหรับแสดงบน overview"""
    global last_alltime_update, cached_alltime_summary
    now = datetime.now(db.TZ_BANGKOK)

    if last_alltime_update is None or (now - last_alltime_update).total_seconds() > 300:
        async with db.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT
                    alias,
                    MAX(drawdown_pct)   as max_drawdown_pct,
                    MAX(profit)         as max_profit,
                    MIN(profit)         as min_profit,
                    MAX(balance)        as max_balance,
                    MIN(balance)        as min_balance,
                    MIN(margin_level)   as min_margin_level
                FROM snapshots GROUP BY alias
            """)
        summary = [dict(r) for r in rows]
        cached_alltime_summary = summary
        last_alltime_update = now
    else:
        summary = cached_alltime_summary

    result = []
    for s in summary:
        s_copy = dict(s)
        if s_copy["alias"] in db.latest_cache:
            s_copy.update({
                "balance":      db.latest_cache[s_copy["alias"]]["balance"],
                "equity":       db.latest_cache[s_copy["alias"]]["equity"],
                "drawdown_pct": db.latest_cache[s_copy["alias"]]["drawdown_pct"],
                "profit":       db.latest_cache[s_copy["alias"]]["profit"],
            })
        result.append(s_copy)
    return result

@router.get("/api/pnl/calendar/{alias}")
async def get_pnl_calendar(alias: str, year: int = Query(..., ge=2000, le=2100)):
    from datetime import date, timedelta
    
    async with db.pool.acquire() as conn:
        # 1. First snapshot of this account for baseline
        row_first = await conn.fetchrow(
            "SELECT balance, withdrawal, ts FROM snapshots WHERE alias=$1 ORDER BY ts ASC LIMIT 1",
            alias
        )
        if not row_first:
            return {"alias": alias, "year": year, "days": []}
            
        # 2. Last snapshot before the year
        row_prev = await conn.fetchrow(
            "SELECT balance, withdrawal, ts FROM snapshots WHERE alias=$1 AND ts < $2 ORDER BY ts DESC LIMIT 1",
            alias, f"{year}-01-01T00:00:00"
        )
        
        # 3. Last snapshot of each day in the year
        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (SUBSTRING(ts, 1, 10))
                SUBSTRING(ts, 1, 10) AS date_str,
                balance,
                withdrawal,
                ts
            FROM snapshots
            WHERE alias = $1 AND ts >= $2 AND ts <= $3
            ORDER BY SUBSTRING(ts, 1, 10) ASC, ts DESC
            """,
            alias, f"{year}-01-01T00:00:00", f"{year}-12-31T23:59:59"
        )
        
        # 4. Aggregates for each day (max DD and max lots)
        agg_rows = await conn.fetch(
            """
            SELECT 
                SUBSTRING(ts, 1, 10) AS date_str,
                MAX(drawdown_pct) as max_dd,
                MAX(total_lots) as max_lots
            FROM snapshots
            WHERE alias = $1 AND ts >= $2 AND ts <= $3
            GROUP BY SUBSTRING(ts, 1, 10)
            """,
            alias, f"{year}-01-01T00:00:00", f"{year}-12-31T23:59:59"
        )

    # Initialize baselines
    if row_prev:
        prev_bal = row_prev["balance"]
        prev_withdraw = row_prev["withdrawal"] or 0.0
    else:
        prev_bal = row_first["balance"]
        prev_withdraw = row_first["withdrawal"] or 0.0

    init_bal = prev_bal
    init_withdraw = prev_withdraw

    day_snapshots = {r["date_str"]: (r["balance"], r["withdrawal"] or 0.0) for r in rows}
    day_aggs = {r["date_str"]: (r["max_dd"] or 0.0, r["max_lots"] or 0.0) for r in agg_rows}
    
    first_date_str = row_first["ts"][:10]
    start_date = date(year, 1, 1)
    end_date = date(year, 12, 31)
    
    days_data = []
    curr = start_date
    while curr <= end_date:
        date_str = curr.strftime("%Y-%m-%d")
        
        if date_str < first_date_str:
            days_data.append({
                "date": date_str,
                "profit": 0.0,
                "balance": 0.0,
                "withdrawal": 0.0,
                "max_dd": 0.0,
                "max_lots": 0.0,
                "has_data": False
            })
        elif date_str in day_snapshots:
            bal, withdraw = day_snapshots[date_str]
            max_dd, max_lots = day_aggs.get(date_str, (0.0, 0.0))
            if prev_bal is not None:
                profit = (bal + withdraw) - (prev_bal + prev_withdraw)
            else:
                profit = 0.0
            prev_bal = bal
            prev_withdraw = withdraw
            days_data.append({
                "date": date_str,
                "profit": round(profit, 2),
                "balance": round(bal, 2),
                "withdrawal": round(withdraw, 2),
                "max_dd": round(max_dd, 2),
                "max_lots": round(max_lots, 2),
                "has_data": True
            })
        else:
            days_data.append({
                "date": date_str,
                "profit": 0.0,
                "balance": round(prev_bal, 2) if prev_bal is not None else 0.0,
                "withdrawal": round(prev_withdraw, 2),
                "max_dd": 0.0,
                "max_lots": 0.0,
                "has_data": False
            })
            
        curr += timedelta(days=1)
        
    return {
        "alias": alias,
        "year": year,
        "baseline_balance": round(init_bal, 2) if init_bal is not None else 0.0,
        "baseline_withdrawal": round(init_withdraw, 2),
        "days": days_data
    }

