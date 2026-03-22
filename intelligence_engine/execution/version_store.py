import json
from datetime import datetime, timezone
from intelligence_engine import database
from intelligence_engine.execution.config_writer import (
    load_active_config, apply_patch, write_config
)

async def apply_suggestion(suggestion_id: int, applied_by: str) -> dict:
    # Load suggestion
    row = await database.fetchrow(
        "SELECT * FROM ie_suggestions WHERE id=$1", suggestion_id
    )
    if not row:
        return {'ok': False, 'error': 'Suggestion not found'}
    if row['status'] != 'pending':
        return {'ok': False, 'error': f"Suggestion is '{row['status']}', not pending"}

    patch = json.loads(row['config_patch'])
    current = load_active_config()
    new_config = apply_patch(patch, current)

    # Save to config_versions table
    await database.execute("""
        INSERT INTO config_versions (version, config, applied_by, suggestion_id, is_active)
        VALUES ($1, $2, $3, $4, TRUE)
        ON CONFLICT (version) DO NOTHING
    """, new_config['version'], json.dumps(new_config), applied_by, suggestion_id)

    # Deactivate all previous versions
    await database.execute("""
        UPDATE config_versions SET is_active=FALSE
        WHERE version != $1
    """, new_config['version'])

    # Mark suggestion as deployed
    await database.execute("""
        UPDATE ie_suggestions
        SET status='deployed', reviewed_at=$1, reviewed_by=$2
        WHERE id=$3
    """, datetime.now(timezone.utc), applied_by, suggestion_id)

    # Write to file
    success = write_config(new_config)
    if not success:
        return {'ok': False, 'error': 'Failed to write config file'}

    return {'ok': True, 'version': new_config['version']}

async def reject_suggestion(suggestion_id: int, reviewed_by: str) -> dict:
    await database.execute("""
        UPDATE ie_suggestions
        SET status='rejected', reviewed_at=$1, reviewed_by=$2
        WHERE id=$3
    """, datetime.now(timezone.utc), reviewed_by, suggestion_id)
    return {'ok': True}

async def rollback_to_version(target_version: int, reason: str, applied_by: str) -> dict:
    row = await database.fetchrow(
        "SELECT * FROM config_versions WHERE version=$1", target_version
    )
    if not row:
        return {'ok': False, 'error': f"Version {target_version} not found"}

    config = json.loads(row['config'])

    # Write old config back as active
    write_config(config)

    # Update DB active flag
    await database.execute("UPDATE config_versions SET is_active=FALSE")
    await database.execute(
        "UPDATE config_versions SET is_active=TRUE WHERE version=$1", target_version
    )

    # Log rollback
    await database.execute("""
        INSERT INTO config_versions
            (version, config, applied_by, is_active, rollback_reason)
        VALUES ($1, $2, $3, TRUE, $4)
        ON CONFLICT (version) DO UPDATE
        SET rollback_reason=$4, is_active=TRUE
    """, target_version, json.dumps(config), applied_by, reason)

    print(f"[VersionStore] Rolled back to v{target_version}. Reason: {reason}")
    return {'ok': True, 'rolled_back_to': target_version}

async def get_history() -> list:
    rows = await database.fetch("""
        SELECT version, applied_at, applied_by, is_active, rollback_reason
        FROM config_versions
        ORDER BY version DESC
        LIMIT 20
    """)
    return [dict(r) for r in rows]
