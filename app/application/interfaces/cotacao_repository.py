from abc import ABC, abstractmethod
from typing import Optional
from app.domain.entities.cotacao import Cotacao
from app.domain.entities.lote import LoteCotacao
from app.domain.entities.configuracao_site import ConfiguracaoSite
from app.domain.value_objects.parametros_rota import ParametrosRota
from app.domain.value_objects.resultado_rota import ResultadoRota


class CotacaoRepository(ABC):

    # ── Configuração de site ──────────────────────────────────────────
    @abstractmethod
    async def listar_configuracoes(self) -> list[ConfiguracaoSite]: ...

    @abstractmethod
    async def buscar_configuracao(self, config_id: int) -> Optional[ConfiguracaoSite]: ...

    # ── Cache de consultas ────────────────────────────────────────────
    @abstractmethod
    async def buscar_cache(
        self, chave: str, config_id: int
    ) -> Optional[ResultadoRota]:
        """Retorna ResultadoRota se existir cache válido (não expirado), ou None."""
        ...

    @abstractmethod
    async def salvar_cache(
        self,
        chave: str,
        config_id: int,
        parametros: ParametrosRota,
        resultado: ResultadoRota,
        validade_horas: int,
    ) -> None: ...

    # ── Lote ──────────────────────────────────────────────────────────
    @abstractmethod
    async def criar_lote(self, lote: LoteCotacao) -> LoteCotacao: ...

    @abstractmethod
    async def atualizar_lote(self, lote: LoteCotacao) -> None: ...

    @abstractmethod
    async def buscar_lote(self, lote_id: int) -> Optional[LoteCotacao]: ...

    @abstractmethod
    async def listar_lotes(self, limite: int = 50) -> list[LoteCotacao]: ...

    # ── Itens do lote ─────────────────────────────────────────────────
    @abstractmethod
    async def criar_item(self, cotacao: Cotacao) -> Cotacao: ...

    @abstractmethod
    async def atualizar_item(self, cotacao: Cotacao) -> None: ...

    @abstractmethod
    async def listar_itens_lote(self, lote_id: int) -> list[Cotacao]: ...
