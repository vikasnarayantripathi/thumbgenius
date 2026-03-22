from apscheduler.schedulers.asyncio import AsyncIOScheduler
from intelligence_engine.data.youtube_collector import fetch_all_niches
from intelligence_engine.brains.decision_engine import generate_suggestions
from intelligence_engine.maintenance.health_monitor import check as health_check

scheduler = AsyncIOScheduler()

async def daily_intelligence_job():
    print("[Cron] Starting daily intelligence job...")
    await fetch_all_niches()
    await generate_suggestions()
    print("[Cron] Daily intelligence job complete.")

async def hourly_health_job():
    print("[Cron] Running health check...")
    await health_check()

def start_scheduler():
    # Daily at 2am UTC
    scheduler.add_job(daily_intelligence_job, 'cron', hour=2, minute=0)
    # Every hour
    scheduler.add_job(hourly_health_job, 'interval', hours=1)
    scheduler.start()
    print("[Scheduler] Started. Daily job at 02:00 UTC, health check every hour.")
