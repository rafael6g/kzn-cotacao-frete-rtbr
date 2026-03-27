import asyncio
from datetime import datetime
from typing import Callable, Awaitable, Optional

from app.application.interfaces.cotacao_repository import CotacaoRepository
from app.application.interfaces.site_scraper import SiteScraper
from app.application.use_cases.buscar_cache import BuscarCacheUseCase
from app.application.use_cases.salvar_resultado import SalvarResultadoUseCase
from app.domain.entities.cotacao import Cotacao, StatusCotacao, FonteResultado
from app.domain.entities.lote import LoteCotacao, StatusLote
from app.domain.exceptions import (
    SiteIndisponivelError,
    ResultadoNaoEncontradoError,
    CaptchaDetectadoError,
    TimeoutConsultaError,
)
from app.core.logging_config import get_logger
from app.core.config import get_settings

logger = get_logger(__name__)
settings = get_settings()

# Tipo para a função de callback de progresso (SSE)
ProgressoCallback = Callable[[dict], Awaitable[None]]


class ProcessarLoteUseCase:
    def __init__(
        self,
        repo: CotacaoRepository,
        scraper: SiteScraper,
    ):
        self._repo = repo
        self._scraper = scraper
        self._buscar_cache = BuscarCacheUseCase(repo)
        self._salvar_resultado = SalvarResultadoUseCase(repo)

    async def executar(
        self,
        lote: LoteCotacao,
        cotacoes: list[Cotacao],
        config_id: int,
        validade_cache_horas: int,
        on_progresso: Optional[ProgressoCallback] = None,
    ) -> LoteCotacao:
        """
        Processa todas as cotações de um lote:
        1. Para cada item: verifica cache → consulta site se necessário
        2. Respeita delay configurado entre consultas ao site
        3. Notifica progresso via callback (SSE)
        4. Atualiza status do lote no Xano
        """
        lote.status = StatusLote.PROCESSANDO
        await self._repo.atualizar_lote(lote)

        await self._emitir(on_progresso, {
            "tipo": "inicio",
            "total": lote.total_linhas,
            "mensagem": f"Iniciando processamento de {lote.total_linhas} rotas...",
        })

        sessao_aberta = False

        try:
            for idx, cotacao in enumerate(cotacoes, start=1):
                logger.info(
                    f"[{idx}/{lote.total_linhas}] "
                    f"{cotacao.parametros.origem} → {cotacao.parametros.destino}"
                )

                # ── 1. Tenta cache ───────────────────────────────────
                resultado_cache = await self._buscar_cache.executar(
                    cotacao.parametros, config_id
                )

                if resultado_cache:
                    cotacao.resultado = resultado_cache
                    cotacao.status = StatusCotacao.CACHE
                    cotacao.fonte = FonteResultado.CACHE
                    lote.linhas_cache += 1

                    await self._emitir(on_progresso, {
                        "tipo": "item",
                        "linha": idx,
                        "total": lote.total_linhas,
                        "origem": cotacao.parametros.origem,
                        "destino": cotacao.parametros.destino,
                        "fonte": "cache",
                        "status": "ok",
                        "distancia": resultado_cache.distancia_km,
                        "pedagio": resultado_cache.valor_pedagio,
                        "total": resultado_cache.valor_total,
                        "mensagem": f"[CACHE] {cotacao.parametros.origem} → {cotacao.parametros.destino}",
                    })

                else:
                    # ── 3. Consulta o site ───────────────────────────
                    try:
                        # ── 2. Abre sessão do browser uma única vez ──
                        if not sessao_aberta:
                            logger.info("Iniciando sessão Playwright...")
                            await self._scraper.iniciar_sessao()
                            sessao_aberta = True

                        # O delay é passado ao scraper para ser aplicado APÓS o buscar
                        # e ANTES da extração: consulta → aguarda → salva → próxima
                        resultado = await self._scraper.consultar(
                            cotacao.parametros,
                            delay_segundos=lote.delay_segundos,
                        )

                        cotacao.resultado = resultado
                        cotacao.status = StatusCotacao.CONSULTADO
                        cotacao.fonte = FonteResultado.SITE
                        lote.linhas_consultadas += 1

                        # Salva no cache para reutilização futura
                        await self._salvar_resultado.executar(
                            cotacao.parametros, resultado, config_id, validade_cache_horas
                        )

                        await self._emitir(on_progresso, {
                            "tipo": "item",
                            "linha": idx,
                            "total": lote.total_linhas,
                            "origem": cotacao.parametros.origem,
                            "destino": cotacao.parametros.destino,
                            "fonte": "site",
                            "status": "ok",
                            "distancia": resultado.distancia_km,
                            "pedagio": resultado.valor_pedagio,
                            "total": resultado.valor_total,
                            "mensagem": f"[SITE] {cotacao.parametros.origem} → {cotacao.parametros.destino}",
                        })

                    except (
                        SiteIndisponivelError,
                        ResultadoNaoEncontradoError,
                        CaptchaDetectadoError,
                        TimeoutConsultaError,
                    ) as e:
                        cotacao.status = StatusCotacao.ERRO
                        cotacao.erro_mensagem = str(e)
                        lote.linhas_erro += 1
                        logger.error(f"Erro na linha {idx}: {e}")

                        await self._emitir(on_progresso, {
                            "tipo": "item",
                            "linha": idx,
                            "total": lote.total_linhas,
                            "origem": cotacao.parametros.origem,
                            "destino": cotacao.parametros.destino,
                            "fonte": "site",
                            "status": "erro",
                            "mensagem": f"[ERRO] {cotacao.parametros.origem} → {cotacao.parametros.destino}: {e}",
                        })

                    except Exception as e:
                        # Captura qualquer outro erro inesperado para não corromper o lote inteiro
                        tipo_exc = type(e).__name__
                        cotacao.status = StatusCotacao.ERRO
                        cotacao.erro_mensagem = f"{tipo_exc}: {e}"
                        lote.linhas_erro += 1
                        logger.exception(f"Erro inesperado na linha {idx} [{tipo_exc}]: {e}")

                        await self._emitir(on_progresso, {
                            "tipo": "item",
                            "linha": idx,
                            "total": lote.total_linhas,
                            "origem": cotacao.parametros.origem,
                            "destino": cotacao.parametros.destino,
                            "fonte": "site",
                            "status": "erro",
                            "mensagem": f"[{tipo_exc}] {cotacao.parametros.origem} → {cotacao.parametros.destino}: {e}",
                        })

                lote.linhas_processadas = idx

            # ── Fim do loop — persiste tudo no Xano em paralelo ─────
            lote.status = StatusLote.CONCLUIDO
            try:
                await asyncio.gather(
                    *[self._repo.atualizar_item(c) for c in cotacoes],
                    return_exceptions=True,
                )
            except Exception as e:
                logger.warning(f"Falha ao persistir itens no Xano: {e}")

        except Exception as e:
            logger.exception(f"Erro crítico no processamento do lote {lote.id}: {e}")
            lote.status = StatusLote.ERRO
            await self._emitir(on_progresso, {
                "tipo": "erro_critico",
                "mensagem": f"Erro crítico: {e}",
            })

        finally:
            if sessao_aberta:
                await self._scraper.encerrar_sessao()

        await self._repo.atualizar_lote(lote)

        await self._emitir(on_progresso, {
            "tipo": "fim",
            "status": lote.status,
            "total": lote.total_linhas,
            "cache": lote.linhas_cache,
            "consultadas": lote.linhas_consultadas,
            "erros": lote.linhas_erro,
            "mensagem": (
                f"Concluído! {lote.linhas_consultadas} consultadas no site, "
                f"{lote.linhas_cache} do cache, {lote.linhas_erro} erros."
            ),
        })

        return lote

    @staticmethod
    async def _emitir(callback: Optional[ProgressoCallback], evento: dict) -> None:
        if callback:
            try:
                await callback(evento)
            except Exception:
                pass  # nunca deixa o callback quebrar o processamento
