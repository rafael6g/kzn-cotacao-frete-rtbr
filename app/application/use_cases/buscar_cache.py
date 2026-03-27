from typing import Optional
from app.application.interfaces.cotacao_repository import CotacaoRepository
from app.domain.value_objects.parametros_rota import ParametrosRota
from app.domain.value_objects.resultado_rota import ResultadoRota
from app.core.logging_config import get_logger

logger = get_logger(__name__)


class BuscarCacheUseCase:
    def __init__(self, repo: CotacaoRepository):
        self._repo = repo

    async def executar(
        self, parametros: ParametrosRota, config_id: int
    ) -> Optional[ResultadoRota]:
        """
        Verifica se existe resultado em cache válido para esses parâmetros.
        Retorna ResultadoRota ou None se não houver cache / estiver expirado.
        """
        chave = parametros.chave_cache()
        logger.debug(f"Buscando cache — chave={chave[:12]}... origem={parametros.origem} destino={parametros.destino}")

        resultado = await self._repo.buscar_cache(chave, config_id)

        if resultado:
            logger.info(f"Cache HIT — {parametros.origem} → {parametros.destino}")
        else:
            logger.debug(f"Cache MISS — {parametros.origem} → {parametros.destino}")

        return resultado
