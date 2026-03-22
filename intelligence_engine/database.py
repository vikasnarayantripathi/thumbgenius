import asyncpg
from intelligence_engine.config import DATABASE_URL

_pool = None

async def get_pool():
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    return _pool

async def execute(query: str, *args):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.execute(query, *args)

async def fetch(query: str, *args):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(query, *args)

async def fetchrow(query: str, *args):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(query, *args)

async def setup_tables():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS yt_trends (
                id SERIAL PRIMARY KEY,
                niche VARCHAR(50),
                video_id VARCHAR(50),
                title TEXT,
                channel_id VARCHAR(100),
                view_count BIGINT,
                views_per_hour FLOAT,
                thumbnail_url TEXT,
                payload JSONB,
                fetched_at TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS user_events (
                id SERIAL PRIMARY KEY,
                user_id VARCHAR(100),
                event_type VARCHAR(50),
                niche VARCHAR(50),
                payload JSONB,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS ie_suggestions (
                id SERIAL PRIMARY KEY,
                title TEXT,
                description TEXT,
                reason TEXT,
                confidence INT,
                impact VARCHAR(10),
                risk VARCHAR(10),
                status VARCHAR(20) DEFAULT 'pending',
                config_patch JSONB,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                reviewed_at TIMESTAMPTZ,
                reviewed_by VARCHAR(100)
            );
            CREATE TABLE IF NOT EXISTS config_versions (
                id SERIAL PRIMARY KEY,
                version INT UNIQUE,
                config JSONB,
                applied_at TIMESTAMPTZ DEFAULT NOW(),
                applied_by VARCHAR(100),
                suggestion_id INT,
                is_active BOOLEAN DEFAULT FALSE,
                rollback_reason TEXT
            );
        """)
    print("[IE] Database tables ready.")
