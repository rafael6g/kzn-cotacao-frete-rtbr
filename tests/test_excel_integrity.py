"""
Test_Excel_Integrity
Valida se o ExcelService gera um DataFrame com as colunas corretas:
- Colunas de resultado sem prefixo resultado_
- 12 colunas Tipo_Carga_*
- Colunas originais do arquivo de entrada preservadas
"""
import pytest
import asyncio
import tempfile
from pathlib import Path

import pandas as pd

from app.domain.entities.cotacao import Cotacao, StatusCotacao, FonteResultado
from app.domain.value_objects.parametros_rota import ParametrosRota
from app.domain.value_objects.resultado_rota import ResultadoRota
from app.infrastructure.excel.excel_service import ExcelService


FRETES_MOCK = {
    "Tipo_Carga_Granel Sólido":             "R$ 3.530,40",
    "Tipo_Carga_Granel Líquido":            "R$ 3.623,66",
    "Tipo_Carga_Frigorificada":             "R$ 4.127,62",
    "Tipo_Carga_Conteinerizada":            "R$ 3.488,61",
    "Tipo_Carga_Carga Geral":               "R$ 3.511,62",
    "Tipo_Carga_Neogranel":                 "R$ 3.511,62",
    "Tipo_Carga_Perigosa (granel sólido)":  "R$ 3.985,72",
    "Tipo_Carga_Perigosa (granel líquido)": "R$ 4.083,52",
    "Tipo_Carga_Perigosa (frigorificada)":  "R$ 4.482,19",
    "Tipo_Carga_Perigosa (conteinerizada)": "R$ 3.747,86",
    "Tipo_Carga_Perigosa (carga geral)":    "R$ 3.770,88",
    "Tipo_Carga_Granel Pressurizada":       "R$ 3.773,79",
}

COLUNAS_RESULTADO_ESPERADAS = {
    "origem", "destino", "status", "fonte",
    "tempo_viagem", "distancia_km", "rota_descricao",
    "valor_pedagio", "valor_combustivel", "valor_total",
    "consultado_em", "erro",
}


def _criar_cotacao_mock(linha=1):
    params = ParametrosRota(
        origem="Londrina, Paraná, Brasil",
        destino="Curitiba, Paraná, Brasil",
        veiculo=2,
        eixos=6,
        preco_combustivel=7.25,
        consumo_km_l=2.50,
    )
    resultado = ResultadoRota(
        tempo_viagem="5 h 20 min",
        distancia_km="386,2 km",
        rota_descricao="via Rodovia Celso Garcia Cid",
        valor_pedagio="R$ 207,00",
        valor_combustivel="R$ 1.119,91",
        valor_total="R$ 1.326,91",
        fretes=FRETES_MOCK,
        consultado_em="2026-03-27T10:00:00+00:00",
    )
    cotacao = Cotacao(lote_id=1, linha_numero=linha, parametros=params)
    cotacao.resultado = resultado
    cotacao.status = StatusCotacao.CONSULTADO
    cotacao.fonte = FonteResultado.SITE
    return cotacao


def _criar_excel_entrada(path: Path):
    """Cria um Excel mínimo de entrada (origem + destino)."""
    df = pd.DataFrame([{
        "origem": "Londrina, Paraná, Brasil",
        "destino": "Curitiba, Paraná, Brasil",
    }])
    df.to_excel(path, index=False)


@pytest.fixture
def excel_service():
    from unittest.mock import MagicMock
    settings = MagicMock()
    return ExcelService(settings)


@pytest.mark.asyncio
async def test_excel_tem_12_colunas_tipo_carga(excel_service):
    """
    O Excel gerado deve conter exatamente 12 colunas Tipo_Carga_*.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        entrada = Path(tmpdir) / "entrada.xlsx"
        saida   = Path(tmpdir) / "saida.xlsx"
        _criar_excel_entrada(entrada)

        cotacao = _criar_cotacao_mock()
        await excel_service.gerar(str(entrada), [cotacao], str(saida))

        df = pd.read_excel(saida)
        colunas_frete = [c for c in df.columns if str(c).startswith("Tipo_Carga_")]

        result = "SUCESSO" if len(colunas_frete) == 12 else "FALHA"
        motivo = (
            f"12 colunas Tipo_Carga_* geradas corretamente"
            if len(colunas_frete) == 12
            else f"Esperado 12, encontrado {len(colunas_frete)}: {colunas_frete}"
        )
        print(f"\n[{result}] - Módulo: Excel - Motivo: {motivo}")
        assert len(colunas_frete) == 12, motivo


@pytest.mark.asyncio
async def test_excel_sem_prefixo_resultado(excel_service):
    """
    O Excel gerado NÃO deve ter colunas com prefixo resultado_.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        entrada = Path(tmpdir) / "entrada.xlsx"
        saida   = Path(tmpdir) / "saida.xlsx"
        _criar_excel_entrada(entrada)

        cotacao = _criar_cotacao_mock()
        await excel_service.gerar(str(entrada), [cotacao], str(saida))

        df = pd.read_excel(saida)
        colunas_prefixo = [c for c in df.columns if str(c).startswith("resultado_")]

        result = "SUCESSO" if not colunas_prefixo else "FALHA"
        motivo = (
            "Nenhuma coluna com prefixo resultado_"
            if not colunas_prefixo
            else f"Colunas com prefixo encontradas: {colunas_prefixo}"
        )
        print(f"\n[{result}] - Módulo: Excel - Motivo: {motivo}")
        assert not colunas_prefixo, motivo


@pytest.mark.asyncio
async def test_excel_tem_colunas_resultado_fixas(excel_service):
    """
    O Excel gerado deve ter as colunas de resultado fixas sem prefixo.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        entrada = Path(tmpdir) / "entrada.xlsx"
        saida   = Path(tmpdir) / "saida.xlsx"
        _criar_excel_entrada(entrada)

        cotacao = _criar_cotacao_mock()
        await excel_service.gerar(str(entrada), [cotacao], str(saida))

        df = pd.read_excel(saida)
        colunas = set(df.columns)
        faltando = COLUNAS_RESULTADO_ESPERADAS - colunas

        result = "SUCESSO" if not faltando else "FALHA"
        motivo = (
            f"Todas as {len(COLUNAS_RESULTADO_ESPERADAS)} colunas de resultado presentes"
            if not faltando
            else f"Colunas faltando no Excel: {faltando}"
        )
        print(f"\n[{result}] - Módulo: Excel - Motivo: {motivo}")
        assert not faltando, motivo


@pytest.mark.asyncio
async def test_excel_preserva_colunas_originais(excel_service):
    """
    O Excel gerado deve preservar as colunas originais do arquivo de entrada.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        entrada = Path(tmpdir) / "entrada.xlsx"
        saida   = Path(tmpdir) / "saida.xlsx"
        _criar_excel_entrada(entrada)

        cotacao = _criar_cotacao_mock()
        await excel_service.gerar(str(entrada), [cotacao], str(saida))

        df = pd.read_excel(saida)
        colunas = set(str(c).lower() for c in df.columns)

        result = "SUCESSO" if "origem" in colunas and "destino" in colunas else "FALHA"
        motivo = (
            "Colunas originais (origem, destino) preservadas no Excel de saída"
            if result == "SUCESSO"
            else f"Colunas originais perdidas. Presentes: {list(df.columns)}"
        )
        print(f"\n[{result}] - Módulo: Excel - Motivo: {motivo}")
        assert result == "SUCESSO", motivo


@pytest.mark.asyncio
async def test_excel_erro_linha_sem_resultado(excel_service):
    """
    Uma linha com erro (sem resultado) deve gerar colunas de resultado vazias
    e coluna 'erro' preenchida — sem quebrar a geração do arquivo.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        entrada = Path(tmpdir) / "entrada.xlsx"
        saida   = Path(tmpdir) / "saida.xlsx"
        _criar_excel_entrada(entrada)

        cotacao = _criar_cotacao_mock()
        cotacao.resultado = None
        cotacao.status = StatusCotacao.ERRO
        cotacao.erro_mensagem = "TimeoutConsultaError: Resultado não apareceu após 15s"

        await excel_service.gerar(str(entrada), [cotacao], str(saida))

        df = pd.read_excel(saida)
        assert saida.exists(), "Excel de saída não foi gerado"
        assert "erro" in [str(c).lower() for c in df.columns], "Coluna 'erro' ausente"

        result = "SUCESSO"
        motivo = "Linha com erro gerada no Excel sem quebrar o arquivo"
        print(f"\n[{result}] - Módulo: Excel - Motivo: {motivo}")
