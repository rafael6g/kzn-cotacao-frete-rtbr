from app.application.interfaces.cotacao_repository import CotacaoRepository
from app.domain.value_objects.parametros_rota import ParametrosRota
from app.domain.value_objects.resultado_rota import ResultadoRota
from app.core.logging_config import get_logger

logger = get_logger(__name__)


class SalvarResultadoUseCase:
    def __init__(self, repo: CotacaoRepository):
        self._repo = repo

    async def executar(
        self,
        parametros: ParametrosRota,
        resultado: ResultadoRota,
        config_id: int,
        validade_horas: int,
    ) -> None:
        """Persiste o resultado no cache do Xano para reutilização futura."""
        chave = parametros.chave_cache()
        logger.info(
            f"Salvando cache — {parametros.origem} → {parametros.destino} "
            f"(válido por {validade_horas}h)"
        )
        await self._repo.salvar_cache(
            chave=chave,
            config_id=config_id,
            parametros=parametros,
            resultado=resultado,
            validade_horas=validade_horas,
        )
