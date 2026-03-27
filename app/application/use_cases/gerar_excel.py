from pathlib import Path
from datetime import datetime
from app.domain.entities.lote import LoteCotacao
from app.domain.entities.cotacao import Cotacao
from app.core.logging_config import get_logger
from app.core.config import get_settings

logger = get_logger(__name__)
settings = get_settings()


class GerarExcelUseCase:
    def __init__(self, excel_service):
        self._excel = excel_service

    async def executar(
        self,
        lote: LoteCotacao,
        cotacoes: list[Cotacao],
        arquivo_entrada_path: str,
    ) -> str:
        """
        Gera o Excel de resultado mesclando dados originais + resultados.
        Retorna o caminho do arquivo gerado.
        Nome: cotacao_[NOME]_[YYYY-MM-DD]_[HH-MM].xlsx
        """
        nome_limpo = lote.nome.replace(" ", "_").upper()
        agora = datetime.now().strftime("%Y-%m-%d_%H-%M")
        nome_arquivo = f"cotacao_{nome_limpo}_{agora}.xlsx"

        output_dir = Path(settings.outputs_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / nome_arquivo

        logger.info(f"Gerando Excel: {nome_arquivo} ({len(cotacoes)} linhas)")

        await self._excel.gerar(
            arquivo_entrada=arquivo_entrada_path,
            cotacoes=cotacoes,
            output_path=str(output_path),
        )

        logger.info(f"Excel gerado com sucesso: {output_path}")
        return str(output_path)
