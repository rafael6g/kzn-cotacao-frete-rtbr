"""
Rotas principais:
  GET  /               → página de upload
  GET  /modelo         → download do Excel modelo de exemplo
  POST /cotacoes       → processa lote (inicia background task)
  GET  /cotacoes/{id}/progresso  → SSE stream de progresso em tempo real
  GET  /cotacoes/{id}/download   → download do Excel gerado
"""

import asyncio
import json
from pathlib import Path
from typing import Optional

from fastapi import (
    APIRouter,
    Request,
    UploadFile,
    File,
    Form,
    BackgroundTasks,
    Depends,
    HTTPException,
)
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse
from fastapi.templating import Jinja2Templates

from app.core.config import get_settings, BASE_DIR
from app.core.dependencies import get_xano_repository, get_excel_service
from app.infrastructure.repositories.xano_repository import XanoRepository
from app.core.logging_config import get_logger
from app.domain.entities.cotacao import Cotacao, StatusCotacao
from app.domain.entities.lote import LoteCotacao, StatusLote
from app.domain.value_objects.parametros_rota import ParametrosRota
from app.domain.exceptions import ExcelInvalidoError
from app.application.use_cases.processar_lote import ProcessarLoteUseCase
from app.application.use_cases.gerar_excel import GerarExcelUseCase
from app.application.interfaces.site_scraper import SiteScraper
from app.domain.entities.configuracao_site import ConfiguracaoSite
from app.infrastructure.scrapers.rotasbrasil_scraper import RotasBrasilScraper
from app.infrastructure.scrapers.qualp_scraper import QualPScraper

logger = get_logger(__name__)
settings = get_settings()
router = APIRouter()
templates = Jinja2Templates(directory="app/presentation/templates")


def _criar_scraper(url_base: str, headless: bool) -> SiteScraper:
    """Seleciona o scraper correto pelo url_base da ConfiguracaoSite."""
    if "qualp.com.br" in url_base:
        return QualPScraper(
            usuario=settings.qualp_usuario,
            senha=settings.qualp_senha,
            headless=headless,
            session_file=".qualp_session.json",
        )
    return RotasBrasilScraper(headless=headless)

# ── Fila SSE por lote: lote_id → asyncio.Queue ───────────────────────
_filas_progresso: dict[int, asyncio.Queue] = {}


def _obter_fila(lote_id: int) -> asyncio.Queue:
    if lote_id not in _filas_progresso:
        _filas_progresso[lote_id] = asyncio.Queue(maxsize=500)
    return _filas_progresso[lote_id]


def _remover_fila(lote_id: int) -> None:
    _filas_progresso.pop(lote_id, None)


# ── Download do modelo de exemplo ────────────────────────────────────

_CIDADES_BRASIL = [
    ("Londrina", "Parana"), ("Maringa", "Parana"), ("Cascavel", "Parana"),
    ("Ponta Grossa", "Parana"), ("Foz do Iguacu", "Parana"), ("Curitiba", "Parana"),
    ("Guarapuava", "Parana"), ("Toledo", "Parana"), ("Apucarana", "Parana"),
    ("Sao Paulo", "Sao Paulo"), ("Campinas", "Sao Paulo"), ("Santos", "Sao Paulo"),
    ("Ribeirao Preto", "Sao Paulo"), ("Sao Jose dos Campos", "Sao Paulo"),
    ("Sorocaba", "Sao Paulo"), ("Bauru", "Sao Paulo"), ("Marilia", "Sao Paulo"),
    ("Belo Horizonte", "Minas Gerais"), ("Uberlandia", "Minas Gerais"),
    ("Juiz de Fora", "Minas Gerais"), ("Montes Claros", "Minas Gerais"),
    ("Campo Grande", "Mato Grosso do Sul"), ("Dourados", "Mato Grosso do Sul"),
    ("Tres Lagoas", "Mato Grosso do Sul"), ("Cuiaba", "Mato Grosso"),
    ("Porto Alegre", "Rio Grande do Sul"), ("Caxias do Sul", "Rio Grande do Sul"),
    ("Pelotas", "Rio Grande do Sul"), ("Santa Maria", "Rio Grande do Sul"),
    ("Florianopolis", "Santa Catarina"), ("Joinville", "Santa Catarina"),
    ("Blumenau", "Santa Catarina"), ("Chapeco", "Santa Catarina"),
    ("Goiania", "Goias"), ("Anapolis", "Goias"), ("Rio Verde", "Goias"),
    ("Salvador", "Bahia"), ("Feira de Santana", "Bahia"),
    ("Fortaleza", "Ceara"), ("Recife", "Pernambuco"), ("Manaus", "Amazonas"),
]

@router.get("/modelo")
async def download_modelo():
    import random
    import io
    import openpyxl

    cidades = random.sample(_CIDADES_BRASIL, min(10, len(_CIDADES_BRASIL)))
    random.shuffle(cidades)
    origens  = cidades[:5]
    destinos = cidades[5:]

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Cotações"
    ws.append(["origem", "destino"])
    for i in range(5):
        o = f"{origens[i][0]}, {origens[i][1]}, Brasil"
        d = f"{destinos[i][0]}, {destinos[i][1]}, Brasil"
        ws.append([o, d])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=modelo_cotacao.xlsx"},
    )


# ── Página inicial ────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    repo = get_xano_repository()
    configs = await repo.listar_configuracoes()
    return templates.TemplateResponse("index.html", {
        "request": request,
        "configs": configs,
        "delay_padrao": settings.delay_padrao_segundos,
        "is_production": settings.is_production,
    })


# ── Upload e início do processamento ─────────────────────────────────

@router.post("/cotacoes", response_class=HTMLResponse)
async def criar_cotacao(
    request: Request,
    background_tasks: BackgroundTasks,
    arquivo: UploadFile = File(...),
    nome_cotacao: str = Form(...),
    config_id: int = Form(...),
    delay_segundos: int = Form(default=10),
    eixos: int = Form(default=6),
    preco_combustivel: float = Form(...),
    consumo_km_l: float = Form(...),
    veiculo: int = Form(default=2),
    modo_visivel: bool = Form(default=False),
    tabela_frete: str = Form(default="A"),
):
    repo = get_xano_repository()
    excel_svc = get_excel_service()

    # Salva arquivo de upload
    upload_dir = Path(settings.uploads_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    arquivo_path = upload_dir / arquivo.filename
    conteudo = await arquivo.read()
    arquivo_path.write_bytes(conteudo)

    # Lê linhas do Excel
    try:
        linhas = excel_svc.ler_arquivo(str(arquivo_path))
    except ExcelInvalidoError as e:
        return templates.TemplateResponse("partials/erro.html", {
            "request": request,
            "mensagem": str(e),
        }, status_code=400)

    if not linhas:
        return templates.TemplateResponse("partials/erro.html", {
            "request": request,
            "mensagem": "Arquivo vazio ou sem linhas válidas.",
        }, status_code=400)

    # Busca config do site
    config = await repo.buscar_configuracao(config_id)
    if not config:
        raise HTTPException(404, "Configuração de site não encontrada.")

    # Cria o lote no Xano
    lote = LoteCotacao(
        nome=nome_cotacao,
        configuracao_site_id=config_id,
        total_linhas=len(linhas),
        delay_segundos=delay_segundos,
        arquivo_entrada=arquivo.filename,
    )
    lote = await repo.criar_lote(lote)

    # Deriva identificador do scraper a partir da URL do site
    site_id = "qualp" if "qualp.com.br" in config.url_base else "rotasbrasil"

    # Monta lista de Cotacao a partir das linhas do Excel
    itens_para_criar: list[Cotacao] = []
    for i, linha in enumerate(linhas, start=1):
        params = ParametrosRota(
            origem=str(linha.get("origem", "")).strip(),
            destino=str(linha.get("destino", "")).strip(),
            veiculo=int(linha.get("veiculo", veiculo)),
            eixos=int(linha.get("eixos", eixos)),
            preco_combustivel=float(
                str(linha.get("preco_combustivel", preco_combustivel))
                .replace(",", ".")
            ),
            consumo_km_l=float(
                str(linha.get("consumo_km_l", consumo_km_l))
                .replace(",", ".")
            ),
            site=site_id,
            tabela_frete=str(linha.get("tabela_frete", tabela_frete)).strip().upper() or tabela_frete,
        )
        itens_para_criar.append(Cotacao(lote_id=lote.id, linha_numero=i, parametros=params))

    # Cria todos os itens em paralelo — reduz N chamadas sequenciais ao Xano para 1 round
    cotacoes: list[Cotacao] = list(
        await asyncio.gather(*[repo.criar_item(c) for c in itens_para_criar])
    )

    # Inicia processamento em background
    background_tasks.add_task(
        _executar_processamento,
        lote=lote,
        cotacoes=cotacoes,
        config_id=config_id,
        validade_cache_horas=config.validade_cache_horas,
        arquivo_path=str(arquivo_path),
        site_url_base=config.url_base,
        headless=True if settings.playwright_headless else not modo_visivel,
    )

    # Retorna fragmento HTMX com o painel de progresso
    return templates.TemplateResponse("partials/progresso_painel.html", {
        "request": request,
        "lote": lote,
        "total": len(cotacoes),
    })


async def _executar_processamento(
    lote: LoteCotacao,
    cotacoes: list[Cotacao],
    config_id: int,
    validade_cache_horas: int,
    arquivo_path: str,
    site_url_base: str = "",
    headless: bool = True,
) -> None:
    """
    Delega o processamento para uma thread separada via run_in_executor.

    Motivo: uvicorn no Windows usa SelectorEventLoop, que não suporta criação de
    subprocessos (necessário para o Playwright lançar o Chromium).
    asyncio.run() dentro da thread cria automaticamente um ProactorEventLoop no Windows,
    que resolve o NotImplementedError.

    Comunicação SSE: eventos são enfileirados via asyncio.run_coroutine_threadsafe
    de volta para a fila no loop principal.
    """
    fila = _obter_fila(lote.id)
    main_loop = asyncio.get_running_loop()

    def _rodar_em_thread() -> None:
        """Executa dentro de uma thread com ProactorEventLoop próprio."""

        async def _async_main() -> None:
            # Cria repositório próprio para este loop (httpx.AsyncClient não é compartilhável)
            repo = XanoRepository(settings)
            excel_svc = get_excel_service()

            def _enfileirar(evento: dict) -> None:
                """Envia evento para a fila do loop principal de forma thread-safe."""
                asyncio.run_coroutine_threadsafe(fila.put(evento), main_loop)

            async def on_progresso(evento: dict) -> None:
                _enfileirar(evento)

            scraper = _criar_scraper(site_url_base, headless)
            use_case = ProcessarLoteUseCase(repo, scraper)

            try:
                lote_result = await use_case.executar(
                    lote=lote,
                    cotacoes=cotacoes,
                    config_id=config_id,
                    validade_cache_horas=validade_cache_horas,
                    on_progresso=on_progresso,
                )

                gerar_excel = GerarExcelUseCase(excel_svc)
                arquivo_saida = await gerar_excel.executar(
                    lote_result, cotacoes, arquivo_path,
                    validade_cache_horas=validade_cache_horas,
                )
                lote_result.arquivo_saida = Path(arquivo_saida).name
                await repo.atualizar_lote(lote_result)

                # Salva snapshot no Xano para download futuro (após redeploy)
                dados_historico = [
                    {
                        "linha_numero": c.linha_numero,
                        "parametros": c.parametros.to_dict(),
                        "resultado": c.resultado.to_dict() if c.resultado else None,
                        "status": c.status.value,
                        "fonte": c.fonte.value if c.fonte else None,
                        "erro_mensagem": c.erro_mensagem,
                    }
                    for c in cotacoes
                ]
                await repo.salvar_historico(lote_result.id, lote_result.nome, dados_historico)

                # Remove upload após processamento concluído
                try:
                    Path(arquivo_path).unlink(missing_ok=True)
                except Exception:
                    pass

                _enfileirar({
                    "tipo": "download_pronto",
                    "lote_id": lote_result.id,
                    "arquivo": lote_result.arquivo_saida,
                    "mensagem": "Arquivo Excel pronto para download!",
                })

            except Exception as e:
                logger.exception(f"Erro no background task do lote {lote.id}: {e}")
                _enfileirar({"tipo": "erro_critico", "mensagem": str(e)})
            finally:
                # Agenda remoção da fila no loop principal após 30s
                main_loop.call_later(30, lambda: _remover_fila(lote.id))

        asyncio.run(_async_main())  # Cria ProactorEventLoop no Windows

    await asyncio.get_running_loop().run_in_executor(None, _rodar_em_thread)


# ── SSE — Progresso em tempo real ────────────────────────────────────

@router.get("/cotacoes/{lote_id}/progresso")
async def stream_progresso(lote_id: int):
    """
    Server-Sent Events (SSE) — o frontend conecta aqui via EventSource
    e recebe eventos de progresso em tempo real.
    """
    fila = _obter_fila(lote_id)

    async def gerar_eventos():
        yield f"data: {json.dumps({'tipo': 'conectado', 'lote_id': lote_id})}\n\n"
        while True:
            try:
                evento = await asyncio.wait_for(fila.get(), timeout=30.0)
                yield f"data: {json.dumps(evento, ensure_ascii=False)}\n\n"
                # Encerra stream quando processamento terminar
                if evento.get("tipo") in ("erro_critico", "download_pronto"):
                    break
            except asyncio.TimeoutError:
                # Keep-alive para não fechar a conexão
                yield ": keep-alive\n\n"

    return StreamingResponse(
        gerar_eventos(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # essencial para Nginx não bufferizar o SSE
        },
    )


# ── Download do Excel gerado ─────────────────────────────────────────

@router.get("/cotacoes/{lote_id}/download")
async def download_excel(lote_id: int):
    repo = get_xano_repository()
    lote = await repo.buscar_lote(lote_id)

    if not lote or not lote.arquivo_saida:
        raise HTTPException(404, "Arquivo não encontrado.")

    caminho = Path(settings.outputs_dir) / lote.arquivo_saida

    if not caminho.exists():
        from app.application.use_cases.gerar_excel import GerarExcelUseCase

        # 1. Tenta snapshot do historico_excel
        # 2. Fallback: reconstrói dos item_cotacao no Xano (funciona para todos os lotes)
        cotacoes_regen = await repo.listar_itens_lote(lote_id)
        if not cotacoes_regen:
            raise HTTPException(404, "Sem dados para regenerar o arquivo.")

        excel_svc = get_excel_service()
        gerar = GerarExcelUseCase(excel_svc)
        arquivo_saida = await gerar.executar(lote, cotacoes_regen, "", validade_cache_horas=0)
        caminho = Path(arquivo_saida)

    return FileResponse(
        path=str(caminho),
        filename=lote.arquivo_saida,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


