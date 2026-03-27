"""
Test_Mapping
Valida o mapeamento de campos do ResultadoRota:
- Sem prefixo resultado_ nos campos
- valor_total é o campo correto (não valor_frete único)
- fretes é um dict com chaves Tipo_Carga_*
"""
import pytest
from app.domain.value_objects.resultado_rota import ResultadoRota


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

RESULTADO_MOCK = ResultadoRota(
    tempo_viagem="5 h 20 min",
    distancia_km="386,2 km",
    rota_descricao="via Rodovia Celso Garcia Cid, Rodovia do Café Governador Ney Braga.",
    valor_pedagio="R$ 207,00",
    valor_combustivel="R$ 1.119,91",
    valor_total="R$ 1.326,91",
    fretes=FRETES_MOCK,
    consultado_em="2026-03-27T10:00:00+00:00",
)


def test_resultado_nao_tem_prefixo_resultado():
    """
    Os campos do ResultadoRota não devem ter prefixo 'resultado_'.
    O prefixo era da versão anterior e foi removido.
    """
    d = RESULTADO_MOCK.to_dict()
    campos_com_prefixo = [k for k in d if k.startswith("resultado_")]

    result = "SUCESSO" if not campos_com_prefixo else "FALHA"
    motivo = (
        "Nenhum campo com prefixo resultado_"
        if not campos_com_prefixo
        else f"Campos com prefixo encontrados: {campos_com_prefixo}"
    )
    print(f"\n[{result}] - Módulo: Mapping - Motivo: {motivo}")
    assert not campos_com_prefixo, motivo


def test_campo_valor_total_existe():
    """
    O campo valor_total deve existir e conter o custo total (pedágio + combustível).
    Este campo substitui o antigo valor_frete único.
    """
    assert RESULTADO_MOCK.valor_total == "R$ 1.326,91"
    result = "SUCESSO"
    motivo = f"valor_total = {RESULTADO_MOCK.valor_total}"
    print(f"\n[{result}] - Módulo: Mapping - Motivo: {motivo}")


def test_campo_valor_frete_nao_existe_mais():
    """
    O campo valor_frete (singular) não deve mais existir no ResultadoRota.
    Foi substituído pelo dict 'fretes' com os 12 tipos.
    """
    d = RESULTADO_MOCK.to_dict()
    tem_valor_frete = "valor_frete" in d

    result = "SUCESSO" if not tem_valor_frete else "FALHA"
    motivo = (
        "Campo valor_frete (singular) corretamente removido — usa-se 'fretes' (dict)"
        if not tem_valor_frete
        else "ATENÇÃO: campo valor_frete ainda existe — deve ser substituído por fretes{}"
    )
    print(f"\n[{result}] - Módulo: Mapping - Motivo: {motivo}")
    assert not tem_valor_frete, motivo


def test_fretes_contem_12_tipos():
    """
    O dict fretes deve conter os 12 tipos de carga com chaves Tipo_Carga_*.
    """
    fretes = RESULTADO_MOCK.fretes
    assert len(fretes) == 12, f"Esperado 12 tipos, encontrado {len(fretes)}: {list(fretes.keys())}"

    for chave in fretes:
        assert chave.startswith("Tipo_Carga_"), f"Chave sem prefixo Tipo_Carga_: {chave}"

    result = "SUCESSO"
    motivo = f"12 tipos de carga com prefixo Tipo_Carga_ correto"
    print(f"\n[{result}] - Módulo: Mapping - Motivo: {motivo}")


def test_serialization_roundtrip():
    """
    to_dict() + from_dict() deve reproduzir o objeto original sem perda de dados.
    """
    d = RESULTADO_MOCK.to_dict()
    reconstruido = ResultadoRota.from_dict(d)

    assert reconstruido.fretes == RESULTADO_MOCK.fretes
    assert reconstruido.valor_total == RESULTADO_MOCK.valor_total
    assert reconstruido.tempo_viagem == RESULTADO_MOCK.tempo_viagem

    result = "SUCESSO"
    motivo = "to_dict() → from_dict() reproduz o objeto sem perda"
    print(f"\n[{result}] - Módulo: Mapping - Motivo: {motivo}")


def test_from_dict_compativel_com_cache_antigo():
    """
    from_dict() com dados antigos (sem campo 'fretes') deve retornar fretes={}.
    Garante compatibilidade com entradas de cache salvas antes da refatoração.
    """
    dados_antigos = {
        "tempo_viagem": "5 h 20 min",
        "distancia_km": "386,2 km",
        "rota_descricao": "via Rodovia...",
        "valor_pedagio": "R$ 207,00",
        "valor_combustivel": "R$ 1.119,91",
        "valor_total": "R$ 1.326,91",
        "valor_frete": "R$ 3.511,62",   # campo da versão antiga
        # sem "fretes" key
    }
    resultado = ResultadoRota.from_dict(dados_antigos)
    assert resultado.fretes == {}, f"Cache antigo deve retornar fretes={{}}, retornou: {resultado.fretes}"

    result = "SUCESSO"
    motivo = "Cache antigo (sem 'fretes') desserializado como fretes={} sem erro"
    print(f"\n[{result}] - Módulo: Mapping - Motivo: {motivo}")
