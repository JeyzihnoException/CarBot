import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    return int(value)


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")

    llm_provider: str = os.getenv("LLM_PROVIDER", "gemini")
    llm_system_prompt: str = os.getenv("LLM_SYSTEM_PROMPT", "")
    llm_proxy_url: str = os.getenv("LLM_PROXY_URL", "")

    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")

    browser_data_dir: str = os.getenv("BROWSER_DATA_DIR", "./browser_data")
    browser_persistent_context: bool = _bool_env("BROWSER_PERSISTENT_CONTEXT", False)
    car_cache_path: str = os.getenv("CAR_CACHE_PATH", "./data/car_cache.json")
    headless: bool = _bool_env("HEADLESS", True)
    slow_mo_ms: int = _int_env("SLOW_MO_MS", 0)
    default_timeout_ms: int = _int_env("DEFAULT_TIMEOUT_MS", 15_000)

    default_top_n: int = _int_env("DEFAULT_TOP_N", 5)
    max_top_n: int = _int_env("MAX_TOP_N", 20)
    max_ads_to_scan: int = _int_env("MAX_ADS_TO_SCAN", 30)

    log_level: str = os.getenv("LOG_LEVEL", "INFO")


settings = Settings()
