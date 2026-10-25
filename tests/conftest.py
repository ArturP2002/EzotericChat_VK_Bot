import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("LLM_STUB", "true")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
# Не поднимаем реальный Long Poll к ВК во время pytest.
os.environ["VK_TOKEN"] = ""
os.environ.setdefault("VK_EVENT_MODE", "longpoll")

from app.config import get_settings  # noqa: E402

get_settings.cache_clear()
