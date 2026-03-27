from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.core.logging_config import setup_logging, get_logger
from app.presentation.routes import cotacoes, historico

setup_logging()
logger = get_logger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────
    logger.info(f"Iniciando {settings.app_name} [{settings.app_env}]")
    Path(settings.uploads_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.outputs_dir).mkdir(parents=True, exist_ok=True)
    yield
    # ── Shutdown ─────────────────────────────────────────────────────
    logger.info("Encerrando aplicação.")


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if not settings.is_production else None,
)

# Static files
static_dir = Path("static")
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Routers
app.include_router(cotacoes.router)
app.include_router(historico.router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=settings.app_port,
        reload=not settings.is_production,
        workers=1,   # 1 worker — essencial para a fila SSE em memória funcionar
    )
