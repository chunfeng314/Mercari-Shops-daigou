from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_path: Path = Path(os.getenv("DATABASE_PATH", "data/coal_store.sqlite3"))
    browser_channel: str = os.getenv("BROWSER_CHANNEL", "chrome" if os.name == "nt" else "")
    browser_headless: bool = os.getenv("BROWSER_HEADLESS", "false").lower() == "true"
    browser_timeout_ms: int = int(os.getenv("BROWSER_TIMEOUT_MS", "45000"))
    browser_profile_root: Path = Path(os.getenv("BROWSER_PROFILE_DIR", "data/browser_profiles"))
    browser_proxy: str = os.getenv("BROWSER_PROXY", "")
    china_browser_proxy: str = os.getenv("CHINA_BROWSER_PROXY", "")
    japan_browser_proxy: str = os.getenv("JAPAN_BROWSER_PROXY", "")
    image_review_enabled: bool = os.getenv("IMAGE_REVIEW_ENABLED", "false").strip().lower() == "true"
    dashscope_api_key: str = os.getenv("DASHSCOPE_API_KEY", "")
    dashscope_proxy: str = os.getenv("DASHSCOPE_PROXY", "")
    qwen_vl_base_url: str = os.getenv("QWEN_VL_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    qwen_vl_model: str = os.getenv("QWEN_VL_MODEL", "qwen3.7-plus")
    qwen_vl_timeout_seconds: int = int(os.getenv("QWEN_VL_TIMEOUT_SECONDS", "45"))


settings = Settings()
