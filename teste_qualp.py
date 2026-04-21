import asyncio
import logging
from app.infrastructure.scrapers.qualp_scraper import QualPScraper
from app.domain.value_objects.parametros_rota import ParametrosRota

# Mostra todos os logs DEBUG do scraper no terminal
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
# Silencia logs verbosos de bibliotecas externas
logging.getLogger("playwright").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)


ROTAS = [
    ("Londrina, Parana, Brasil", "Sao Paulo, Sao Paulo, Brasil"),
    ("Londrina, Parana, Brasil", "Sao Paulo, Sao Paulo, Brasil"),
    ("Londrina, Parana, Brasil", "Sao Paulo, Sao Paulo, Brasil"),
]

EIXOS_POR_ROTA = [5, 6, 2]


def _imprimir_resultado(resultado) -> None:
    print("  ─────────────────────────────────────────")
    print(f"  Tempo viagem  : {resultado.tempo_viagem!r}")
    print(f"  Distância km  : {resultado.distancia_km!r}")
    print(f"  Rota descrição: {resultado.rota_descricao!r}")
    print(f"  Pedágio       : {resultado.valor_pedagio!r}")
    print(f"  Combustível   : {resultado.valor_combustivel!r}")
    print(f"  Custo Total   : {resultado.valor_total!r}")
    print(f"  Consultado em : {resultado.consultado_em}")
    if resultado.fretes:
        print(f"  Fretes ANTT ({len(resultado.fretes)} tipos):")
        for tipo, valor in resultado.fretes.items():
            print(f"    {tipo:<30} {valor}")
    else:
        print("  Fretes ANTT   : NENHUM RETORNADO")
    print("  ─────────────────────────────────────────")


async def main():
    scraper = QualPScraper(
        usuario="ti@real94.com.br",
        senha="Real3636@@",
        headless=False,
        session_file=".qualp_session.json",
    )

    try:
        print("Iniciando sessao (browser vai abrir com imagens)...")
        await scraper.iniciar_sessao()

        for i, (origem, destino) in enumerate(ROTAS, 1):
            params = ParametrosRota(
                origem=origem,
                destino=destino,
                veiculo=2,
                eixos=EIXOS_POR_ROTA[i - 1],
                preco_combustivel=7.25,
                consumo_km_l=2.50,
            )

            print(f"\n[{i}/{len(ROTAS)}] {origem} → {destino}")
            print(f"  Parâmetros: veiculo={params.veiculo_label} | eixos={params.eixos} | "
                  f"preço_comb=R${params.preco_combustivel:.2f} | consumo={params.consumo_km_l:.1f}km/l")
            try:
                resultado = await scraper.consultar(params, delay_segundos=5)
                print("  OK — Resultado recebido:")
                _imprimir_resultado(resultado)
            except Exception as e:
                print(f"  ERRO: {type(e).__name__}: {e}")

    except Exception as e:
        print(f"ERRO GERAL: {type(e).__name__}: {e}")
    finally:
        await scraper.encerrar_sessao()
        print("\nSessao encerrada.")


asyncio.run(main())
