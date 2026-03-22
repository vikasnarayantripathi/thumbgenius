import json
import os
import shutil
from datetime import datetime, timezone
from intelligence_engine.config import ACTIVE_CONFIG_PATH, CONFIG_HISTORY_PATH

def load_active_config() -> dict:
    with open(ACTIVE_CONFIG_PATH, 'r') as f:
        return json.load(f)

def _deep_merge(base: dict, patch: dict) -> dict:
    result = base.copy()
    for key, value in patch.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result

def write_config(new_config: dict) -> bool:
    try:
        # Backup current first
        current_version = new_config.get('version', 1)
        backup_path = os.path.join(CONFIG_HISTORY_PATH, f"v{current_version}.json")
        shutil.copy2(ACTIVE_CONFIG_PATH, backup_path)

        # Write new active config
        with open(ACTIVE_CONFIG_PATH, 'w') as f:
            json.dump(new_config, f, indent=2)

        print(f"[ConfigWriter] Written v{current_version} to active config.")
        return True
    except Exception as e:
        print(f"[ConfigWriter] Error writing config: {e}")
        return False

def apply_patch(patch: dict, current_config: dict) -> dict:
    merged = _deep_merge(current_config, patch)
    merged['version'] = current_config.get('version', 1) + 1
    merged['updated_at'] = datetime.now(timezone.utc).isoformat()
    return merged
