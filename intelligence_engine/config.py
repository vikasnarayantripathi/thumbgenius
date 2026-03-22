import os

DATABASE_URL = os.environ.get("DATABASE_URL", "")
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
ADMIN_USERNAME = os.environ.get("IE_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("IE_ADMIN_PASSWORD", "changeme123")
JWT_SECRET = os.environ.get("IE_JWT_SECRET", "supersecretkey")

ACTIVE_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "active_config.json")
CONFIG_HISTORY_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "config_history")

TRACKED_NICHES = ["gaming", "finance", "tech", "fitness", "cooking", "education", "travel", "business"]
