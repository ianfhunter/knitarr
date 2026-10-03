from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KNITARR_", extra="ignore")

    data_dir: Path = Path("/data")
    db_path: Path = Path("/data/knitarr.db")
    library_dir: Path = Path("/data/library")
    ia_user_agent: str = "Knitarr/0.1 (self-hosted pattern library)"
    worker_interval_sec: int = 15
    ia_request_delay_sec: float = 1.0

    @property
    def samples_dir(self) -> Path:
        return Path("/app/samples")


settings = Settings()
