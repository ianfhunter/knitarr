from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KNITARR_", extra="ignore")

    data_dir: Path = Path("/data")
    db_path: Path = Path("/data/knitarr.db")
    library_dir: Path = Path("/data/library")
    ia_user_agent: str = (
        "Knitarr/0.1 (self-hosted pattern library; +https://github.com/knitarr/knitarr)"
    )
    ia_request_delay_sec: float = 1.0
    europeana_api_key: str = "apidemo"
    si_api_key: str = ""
    pixabay_api_key: str = ""
    dmc_algolia_app_id: str = ""
    dmc_algolia_search_key: str = ""
    dmc_algolia_index: str = ""
    convert_max_width: int = 120
    convert_max_colors: int = 24

    @property
    def samples_dir(self) -> Path:
        return Path("/app/samples")


settings = Settings()
