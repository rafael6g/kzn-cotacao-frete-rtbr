from abc import ABC, abstractmethod
from app.domain.value_objects.parametros_rota import ParametrosRota
from app.domain.value_objects.resultado_rota import ResultadoRota


class SiteScraper(ABC):

    @abstractmethod
    async def iniciar_sessao(self) -> None:
        """Abre o browser e navega até a página inicial. Chamado uma vez por lote."""
        ...

    @abstractmethod
    async def encerrar_sessao(self) -> None:
        """Fecha o browser. Chamado ao final do lote."""
        ...

    @abstractmethod
    async def consultar(self, parametros: ParametrosRota, delay_segundos: int = 0) -> ResultadoRota:
        """
        Executa uma consulta no site. Após clicar em Buscar e o resultado aparecer,
        aguarda delay_segundos antes de extrair os dados (evita bot detection).
        """
        ...

    @abstractmethod
    async def esta_ativo(self) -> bool:
        """Verifica se a sessão do browser ainda está aberta e funcional."""
        ...
