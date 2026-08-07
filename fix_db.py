import asyncio
import asyncpg
import database

async def fix():
    pool = await asyncpg.create_pool(database.DATABASE_URL)
    async with pool.acquire() as conn:
        # Get the latest non-zero net_deposit and withdrawal for each alias
        aliases = await conn.fetch("SELECT DISTINCT alias FROM snapshots")
        for rec in aliases:
            alias = rec["alias"]
            # Find first non-zero net_deposit
            d_row = await conn.fetchrow("SELECT net_deposit FROM snapshots WHERE alias=$1 AND net_deposit > 0 ORDER BY ts ASC LIMIT 1", alias)
            if d_row:
                d_val = d_row["net_deposit"]
                await conn.execute("UPDATE snapshots SET net_deposit = $1 WHERE alias=$2 AND (net_deposit = 0 OR net_deposit IS NULL)", d_val, alias)
            
            # Find first non-zero withdrawal
            w_row = await conn.fetchrow("SELECT withdrawal FROM snapshots WHERE alias=$1 AND withdrawal > 0 ORDER BY ts ASC LIMIT 1", alias)
            if w_row:
                w_val = w_row["withdrawal"]
                await conn.execute("UPDATE snapshots SET withdrawal = $1 WHERE alias=$2 AND (withdrawal = 0 OR withdrawal IS NULL)", w_val, alias)
        
        print("Fixed database!")
    await pool.close()

asyncio.run(fix())
