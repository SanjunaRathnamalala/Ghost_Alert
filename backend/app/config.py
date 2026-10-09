"""Settings, read from the .env file (decision 5.7 / 7.5: no secrets in code)."""
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


class SettingsError(RuntimeError):
    pass


def _get(name, default=None, required=True):
    value = os.getenv(name, default)
    if required and (value is None or value == "" or value == "CHANGE_ME"):
        raise SettingsError(f"Setting {name} is missing in .env")
    return value


@dataclass(frozen=True)
class Settings:
    pg_url: str
    influx_url: str
    influx_token: str
    influx_org: str
    influx_bucket: str
    gateway_api_key: str
    cors_origins: list = field(default_factory=list)
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    dashboard_url: str = "http://localhost:5173"
    safety_round_s: int = 300
    telemetry_store: str = "influx"   # "memory" = fallback without InfluxDB (data lost on restart)


def load_settings() -> Settings:
    key = _get("GATEWAY_API_KEY")
    if len(key) < 16:
        raise SettingsError("GATEWAY_API_KEY must be at least 16 characters")
    store_kind = _get("TELEMETRY_STORE", "influx", required=False).lower()
    if store_kind not in ("influx", "memory"):
        raise SettingsError("TELEMETRY_STORE must be influx or memory")
    need_influx = store_kind == "influx"
    return Settings(
        pg_url=_get("PG_URL"),
        influx_url=_get("INFLUX_URL", "http://localhost:8086"),
        influx_token=_get("INFLUX_TOKEN", "", required=need_influx),
        influx_org=_get("INFLUX_ORG", "", required=need_influx),
        influx_bucket=_get("INFLUX_BUCKET", "", required=need_influx),
        gateway_api_key=key,
        cors_origins=[o.strip() for o in _get("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()],
        telegram_bot_token=_get("TELEGRAM_BOT_TOKEN", "", required=False),
        telegram_chat_id=_get("TELEGRAM_CHAT_ID", "", required=False),
        dashboard_url=_get("DASHBOARD_URL", "http://localhost:5173", required=False),
        safety_round_s=int(_get("SAFETY_ROUND_S", "300", required=False)),
        telemetry_store=store_kind,
    )
