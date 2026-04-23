from functools import lru_cache

from fastapi import HTTPException, Request

from app.core.config import get_settings
from app.infrastructure.auth.kzn_auth import UsuarioAtual
from app.infrastructure.excel.excel_service import ExcelService
from app.infrastructure.repositories.xano_repository import XanoRepository


@lru_cache
def get_xano_repository() -> XanoRepository:
    settings = get_settings()
    return XanoRepository(settings)


@lru_cache
def get_excel_service() -> ExcelService:
    settings = get_settings()
    return ExcelService(settings)


async def get_usuario_atual(request: Request) -> UsuarioAtual:
    usuario = getattr(request.state, "usuario", None)
    if usuario is None:
        settings = get_settings()
        if not settings.kzn_auth_url:
            return UsuarioAtual(id=0, nome="Dev Local", email="dev@local", role="admin", empresa_id=1, empresa_nome="Dev")
        raise HTTPException(status_code=401, detail="Não autenticado")
    return usuario
