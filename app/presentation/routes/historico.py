from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.core.dependencies import get_xano_repository
from app.core.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="app/presentation/templates")


@router.get("/historico", response_class=HTMLResponse)
async def historico(request: Request):
    repo = get_xano_repository()
    lotes = await repo.listar_lotes(limite=50)
    return templates.TemplateResponse("historico.html", {
        "request": request,
        "lotes": lotes,
    })


@router.get("/historico/tabela", response_class=HTMLResponse)
async def historico_tabela(request: Request):
    """Fragmento HTMX — retorna apenas a tabela para polling/refresh."""
    repo = get_xano_repository()
    lotes = await repo.listar_lotes(limite=50)
    return templates.TemplateResponse("partials/historico_tabela.html", {
        "request": request,
        "lotes": lotes,
    })
