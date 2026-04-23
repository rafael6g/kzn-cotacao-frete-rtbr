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
    xano_ep_historico: str = "/historico_excel"
    xano_ep_cache_distancias: str = "/cache_distancias"

    # Playwright
    playwright_headless: bool = True
    playwright_timeout_ms: int = 30000
    playwright_resultado_timeout_ms: int = 90000
    playwright_slow_mo_ms: int = 0

    # QualP — conta compartilhada
    qualp_usuario: str = ""
    qualp_senha: str = ""
    # QualP — conta exclusiva do sistema (slot estável, session separada)
    qualp_usuario_padrao: str = ""
    qualp_senha_padrao: str = ""

    # Processamento
    delay_padrao_segundos: int = 10
    min_ciclo_segundos: float = 5.0
    max_retentativas: int = 2
    uploads_dir: str = "uploads"
    outputs_dir: str = "outputs"

    # Kryzon Auth — integração SSO
    kzn_auth_url: str = ""
    portal_url: str = "https://auth.kryzon.com"

    # Módulo — metadados para kzn-manifest.json
    modulo_codigo: str = "cotacao-frete"
    modulo_nome: str = "Cotação de Frete"
    modulo_menu_nome: str = "Cotação de Frete"
    modulo_url_base: str = ""
    modulo_url_api: str = ""
    modulo_versao: str = "1.0.0"

    @property
    def xano_url(self) -> str:
        return f"{self.xano_base_url}{self.xano_api_group}"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
