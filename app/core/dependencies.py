from functools import lru_cache
from app.core.config import Settings, get_settings
from app.infrastructure.repositories.xano_repository import XanoRepository
from app.infrastructure.excel.excel_service import ExcelService


@lru_cache
def get_xano_repository() -> XanoRepository:
    settings = get_settings()
    return XanoRepository(settings)


@lru_cache
def get_excel_service() -> ExcelService:
    settings = get_settings()
    return ExcelService(settings)
