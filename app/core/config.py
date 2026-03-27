from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # App
    app_name: str = "Sistema de Cotações"
    app_env: str = "development"
    app_port: int = 8000
    secret_key: str = "dev-secret-key"

    # Xano
    xano_base_url: str
    xano_api_group: str = "/api"
    xano_ep_config_site: str = "/configuracao_site"
    xano_ep_lote: str = "/lote_cotacao"
    xano_ep_cache: str = "/cache_consulta"
    xano_ep_item: str = "/item_cotacao"

    # Playwright
    playwright_headless: bool = True
    playwright_timeout_ms: int = 30000
    playwright_slow_mo_ms: int = 0

    # Processamento
    delay_padrao_segundos: int = 10
    max_retentativas: int = 2
    uploads_dir: str = "uploads"
    outputs_dir: str = "outputs"

    @property
    def xano_url(self) -> str:
        return f"{self.xano_base_url}{self.xano_api_group}"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
