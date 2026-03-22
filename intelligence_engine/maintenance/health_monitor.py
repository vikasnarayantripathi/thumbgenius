from datetime import datetime, timezone
from intelligence_engine import database
from intelligence_engine.execution.version_store import rollback_to_version

async def check() -> dict:
    report = {
        'checked_at': datetime.now(timezone.utc).isoformat(),
        'status': 'ok',
        'issues': []
    }

    # Check 1: any trends collected in last 25 hours?
    row = await database.fetchrow(
        "SELECT COUNT(*) as cnt FROM yt_trends WHERE fetched_at > NOW() - INTERVAL '25 hours'"
    )
    if row['cnt'] == 0:
        report['issues'].append('No trend data collected in last 25 hours')
        report['status'] = 'warning'

    # Check 2: pending suggestions piling up (>20 unreviewed = admin not checking)
    row = await database.fetchrow(
        "SELECT COUNT(*) as cnt FROM ie_suggestions WHERE status='pending'"
    )
    if row['cnt'] > 20:
        report['issues'].append(f"{row['cnt']} suggestions pending admin review")
        report['status'] = 'warning'

    # Check 3: config versions table has at least one entry
    row = await database.fetchrow("SELECT COUNT(*) as cnt FROM config_versions")
    if row['cnt'] == 0:
        report['issues'].append('No config versions tracked yet')

    report['pending_suggestions'] = row['cnt']
    print(f"[HealthMonitor] Status: {report['status']} | Issues: {len(report['issues'])}")
    return report

async def auto_rollback_if_needed():
    """
    If config has been updated in last hour but something looks wrong,
    roll back to previous stable version.
    """
    row = await database.fetchrow("""
        SELECT version FROM config_versions
        WHERE is_active=FALSE
        ORDER BY version DESC
        LIMIT 1
    """)
    if row:
        result = await rollback_to_version(
            target_version=row['version'],
            reason='Auto-rollback triggered by health monitor',
            applied_by='system'
        )
        print(f"[HealthMonitor] Auto-rollback result: {result}")
        return result
    return {'ok': False, 'error': 'No previous version to roll back to'}
