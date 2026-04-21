from typing import Optional
from datetime import datetime, timezone, timedelta

import httpx

from app.application.interfaces.cotacao_repository import CotacaoRepository
from app.domain.entities.cotacao import Cotacao, StatusCotacao, FonteResultado
from app.domain.entities.lote import LoteCotacao, StatusLote
from app.domain.entities.configuracao_site import ConfiguracaoSite
from app.domain.value_objects.parametros_rota import ParametrosRota
from app.domain.value_objects.resultado_rota import ResultadoRota
from app.domain.exceptions import XanoApiError
from app.core.config import Settings
from app.core.logging_config import get_logger

logger = get_logger(__name__)


class XanoRepository(CotacaoRepository):
    """
    Implementação concreta que persiste dados via API REST do Xano.
    Todos os métodos são async usando httpx.AsyncClient.
    """

    def __init__(self, settings: Settings):
        self._base = settings.xano_url
        self._ep_config = settings.xano_ep_config_site
        self._ep_lote = settings.xano_ep_lote
        self._ep_cache = settings.xano_ep_cache
        self._ep_item = settings.xano_ep_item
        self._ep_historico = settings.xano_ep_historico
        self._client = httpx.AsyncClient(timeout=15.0)

    # ── helpers ──────────────────────────────────────────────────────

    async def _get(self, endpoint: str, params: dict = None) -> dict | list:
        url = f"{self._base}{endpoint}"
        r = await self._client.get(url, params=params)
        if r.status_code >= 400:
            raise XanoApiError(r.status_code, r.text)
        return r.json()

    async def _post(self, endpoint: str, body: dict) -> dict:
        url = f"{self._base}{endpoint}"
        r = await self._client.post(url, json=body)
        if r.status_code >= 400:
            raise XanoApiError(r.status_code, r.text)
        return r.json()

    async def _patch(self, endpoint: str, id_: int, body: dict) -> dict:
        url = f"{self._base}{endpoint}/{id_}"
        r = await self._client.patch(url, json=body)
        if r.status_code >= 400:
            raise XanoApiError(r.status_code, r.text)
        return r.json()

    # ── Configurações de site ────────────────────────────────────────

    async def listar_configuracoes(self) -> list[ConfiguracaoSite]:
        data = await self._get(self._ep_config)
        items = data if isinstance(data, list) else data.get("items", [])
        return [self._map_config(c) for c in items]

    async def buscar_configuracao(self, config_id: int) -> Optional[ConfiguracaoSite]:
        try:
            data = await self._get(f"{self._ep_config}/{config_id}")
            return self._map_config(data)
        except XanoApiError as e:
            if e.status_code == 404:
                return None
            raise

    def _map_config(self, d: dict) -> ConfiguracaoSite:
        return ConfiguracaoSite(
            id=d.get("id"),
            nome=d.get("nome", ""),
            descricao=d.get("descricao", ""),
            url_base=d.get("url_base", ""),
            validade_cache_horas=d.get("validade_cache_horas", 720),
            delay_padrao_segundos=d.get("delay_padrao_segundos", 15),
            campos_input=d.get("campos_input", {}),
            campos_resultado=d.get("campos_resultado", {}),
            ativo=d.get("ativo", True),
        )

    # ── Cache ─────────────────────────────────────────────────────────

    async def buscar_cache(
        self, chave: str, config_id: int
    ) -> Optional[ResultadoRota]:
        """
        Busca cache via GET /cache_consulta com filtro por chave_cache.
        O Xano suporta filtragem via query params nos endpoints padrão.
        Validação de expiração feita no cliente.
        """
        try:
            data = await self._get(
                self._ep_cache,
                params={"chave_cache": chave, "configuracao_site_id": config_id},
            )
            # Xano retorna lista — pega o primeiro registro válido
            items = data if isinstance(data, list) else data.get("items", [])

            agora_ms = datetime.now(timezone.utc).timestamp() * 1000  # Xano usa ms

            for item in items:
                if item.get("chave_cache") != chave:
                    continue
                # Verifica expiração (campo expira_em é timestamp em ms no Xano)
                expira_em = item.get("expira_em")
                if expira_em and expira_em < agora_ms:
                    logger.debug("Cache encontrado mas expirado, ignorando.")
                    continue
                resultado = ResultadoRota.from_dict(item.get("resultado", {}))
                # Cache inválido: scrape anterior falhou — valor_total vazio e nenhum frete com valor real
                fretes_com_valor = any(v for v in resultado.fretes.values() if v)
                if not resultado.valor_total and not fretes_com_valor:
                    logger.debug("Cache encontrado mas resultado vazio, ignorando.")
                    continue
                return resultado

            return None
        except XanoApiError as e:
            logger.warning(f"Erro ao buscar cache: {e}")
            return None

    async def salvar_cache(
        self,
        chave: str,
        config_id: int,
        parametros: ParametrosRota,
        resultado: ResultadoRota,
        validade_horas: int,
    ) -> None:
        # Xano armazena timestamptz como número em milissegundos
        expira_em = int(
            (datetime.now(timezone.utc) + timedelta(hours=validade_horas)).timestamp() * 1000
        )

        await self._post(self._ep_cache, {
            "configuracao_site_id": config_id,
            "chave_cache": chave,
            "parametros": parametros.to_dict(),
            "resultado": resultado.to_dict(),
            "expira_em": expira_em,
        })

    # ── Lote ──────────────────────────────────────────────────────────

    async def criar_lote(self, lote: LoteCotacao) -> LoteCotacao:
        data = await self._post(self._ep_lote, {
            "nome": lote.nome,
            "configuracao_site_id": lote.configuracao_site_id,
            "status": lote.status.value,
            "total_linhas": lote.total_linhas,
            "linhas_processadas": 0,
            "linhas_cache": 0,
            "linhas_consultadas": 0,
            "linhas_erro": 0,
            "delay_segundos": lote.delay_segundos,
            "arquivo_entrada": lote.arquivo_entrada,
        })
        lote.id = data["id"]
        return lote

    async def atualizar_lote(self, lote: LoteCotacao) -> None:
        await self._patch(self._ep_lote, lote.id, {
            "status": lote.status.value,
            "linhas_processadas": lote.linhas_processadas,
            "linhas_cache": lote.linhas_cache,
            "linhas_consultadas": lote.linhas_consultadas,
            "linhas_erro": lote.linhas_erro,
            "arquivo_saida": lote.arquivo_saida,
        })

    async def buscar_lote(self, lote_id: int) -> Optional[LoteCotacao]:
        try:
            data = await self._get(f"{self._ep_lote}/{lote_id}")
            return self._map_lote(data)
        except XanoApiError as e:
            if e.status_code == 404:
                return None
            raise

    async def listar_lotes(self, limite: int = 50) -> list[LoteCotacao]:
        data = await self._get(self._ep_lote, params={"per_page": limite})
        items = data if isinstance(data, list) else data.get("items", [])
        lotes = [self._map_lote(d) for d in items]
        return sorted(lotes, key=lambda l: l.created_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

    def _map_lote(self, d: dict) -> LoteCotacao:
        created_raw = d.get("created_at")
        created_at = None
        if created_raw:
            try:
                if isinstance(created_raw, (int, float)):
                    created_at = datetime.fromtimestamp(created_raw / 1000, tz=timezone.utc)
                else:
                    created_at = datetime.fromisoformat(str(created_raw).replace(" ", "T").rstrip("+0000") + "+00:00")
            except Exception:
                pass
        lote = LoteCotacao(
            id=d.get("id"),
            nome=d.get("nome", ""),
            configuracao_site_id=d.get("configuracao_site_id"),
            total_linhas=d.get("total_linhas", 0),
            delay_segundos=d.get("delay_segundos", 15),
            arquivo_entrada=d.get("arquivo_entrada", ""),
            arquivo_saida=d.get("arquivo_saida"),
            status=StatusLote(d.get("status", "aguardando")),
            linhas_processadas=d.get("linhas_processadas", 0),
            linhas_cache=d.get("linhas_cache", 0),
            linhas_consultadas=d.get("linhas_consultadas", 0),
            linhas_erro=d.get("linhas_erro", 0),
            created_at=created_at,
        )
        return lote

    # ── Histórico Excel ───────────────────────────────────────────────

    async def salvar_historico(self, lote_id: int, nome: str, dados: list) -> None:
        try:
            await self._post(self._ep_historico, {
                "lote_id": lote_id,
                "nome": nome,
                "dados": dados,
            })
        except Exception as e:
            logger.warning(f"Falha ao salvar historico_excel: {e}")

    async def buscar_historico(self, lote_id: int) -> Optional[list]:
        try:
            data = await self._get(f"{self._ep_historico}/{lote_id}")
            return data.get("dados")
        except XanoApiError as e:
            if e.status_code == 404:
                return None
            raise

    # ── Itens ─────────────────────────────────────────────────────────

    async def criar_item(self, cotacao: Cotacao) -> Cotacao:
        data = await self._post(self._ep_item, {
            "lote_id": cotacao.lote_id,
            "linha_numero": cotacao.linha_numero,
            "parametros": cotacao.parametros.to_dict(),
            "status": cotacao.status.value,
        })
        cotacao.id = data["id"]
        return cotacao

    async def atualizar_item(self, cotacao: Cotacao) -> None:
        if not cotacao.id:
            return
        body = {
            "status": cotacao.status.value,
            "fonte": cotacao.fonte.value if cotacao.fonte else None,
            "erro_mensagem": cotacao.erro_mensagem,
        }
        if cotacao.resultado:
            body["resultado"] = cotacao.resultado.to_dict()
        await self._patch(self._ep_item, cotacao.id, body)

    async def listar_itens_lote(self, lote_id: int) -> list[Cotacao]:
        data = await self._get(self._ep_item, params={"lote_id": lote_id})
        items = data if isinstance(data, list) else data.get("items", [])
        # Filtra client-side caso Xano não suporte o query param
        return [self._map_item(d) for d in items if d.get("lote_id") == lote_id]

    def _map_item(self, d: dict) -> Cotacao:
        params_dict = d.get("parametros", {})
        parametros = ParametrosRota(
            origem=params_dict.get("origem", ""),
            destino=params_dict.get("destino", ""),
            veiculo=params_dict.get("veiculo", 2),
            eixos=params_dict.get("eixos", 6),
            preco_combustivel=params_dict.get("preco_combustivel", 0),
            consumo_km_l=params_dict.get("consumo_km_l", 0),
            tipo_carga=params_dict.get("tipo_carga", "todas"),
            site=params_dict.get("site", ""),
            tabela_frete=params_dict.get("tabela_frete", "A"),
            retorno_vazio=params_dict.get("retorno_vazio", False),
            distancia_km=params_dict.get("distancia_km"),
        )
        resultado = None
        if d.get("resultado"):
            resultado = ResultadoRota.from_dict(d["resultado"])

        return Cotacao(
            id=d.get("id"),
            lote_id=d.get("lote_id"),
            linha_numero=d.get("linha_numero", 0),
            parametros=parametros,
            resultado=resultado,
            status=StatusCotacao(d.get("status", "aguardando")),
            fonte=FonteResultado(d["fonte"]) if d.get("fonte") else None,
            erro_mensagem=d.get("erro_mensagem"),
        )
