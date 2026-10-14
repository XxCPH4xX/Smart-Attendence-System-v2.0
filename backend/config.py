from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ATTENDANCE_", env_file=".env", extra="ignore")
    database_url: str = "sqlite:///data/attendance.db"
    biometric_key: str = ""
    timezone: str = "Asia/Dhaka"
    institution: str = "Attendance Office"
    api_url: str = "http://127.0.0.1:8000"
    dashboard_url: str = "http://127.0.0.1:8501"
    device: str = "cpu"
    asset_dir: Path = Path("assets")
    session_hours: int = 8
    max_upload_bytes: int = 8_000_000

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise ValueError("Unknown IANA timezone") from error
        return value

    @field_validator("device")
    @classmethod
    def valid_device(cls, value):
        if value not in {"cpu", "mps"}:
            raise ValueError("Device must be cpu or mps")
        return value


@lru_cache
def get_settings():
    return Settings()
