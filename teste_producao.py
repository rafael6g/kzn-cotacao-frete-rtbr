"""
Teste headless para rodar no terminal de producao (Docker).
Uso: python teste_producao.py
"""
import asyncio
import sys
import time

# Configura ProactorEventLoop no Windows
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from app.core.config import get_settings
from app.infrastructure.scrapers.qualp_scraper import QualPScraper
from app.domain.value_objects.parametros_rota import ParametrosRota

ROTAS = [
    ("TRES LAGOAS, MATO GROSSO DO SUL, BRASIL", "CASTANHAL, PARA, BRASIL"),
    ("TRES LAGOAS, MATO GROSSO DO SUL, BRASIL", "HORTOLANDIA, SAO PAULO, BRASIL"),
    ("TRES LAGOAS, MATO GROSSO DO SUL, BRASIL", "SAO PAULO, SAO PAULO, BRASIL"),
]

async def main():
    settings = get_settings()
    scraper = QualPScraper(
        usuario=settings.qualp_usuario,
        senha=settings.qualp_senha,
        headless=True,
    )

    print("=" * 60)
    print(f"  Teste producao — {len(ROTAS)} rotas")
    print(f"  qualp_usuario={settings.qualp_usuario}")
    print(f"  resultado_timeout={settings.playwright_resultado_timeout_ms}ms")
    print("=" * 60)

    print("\n[SESSAO] Iniciando Playwright...")
    t0 = time.monotonic()
    await scraper.iniciar_sessao()
    print(f"[SESSAO] OK  {time.monotonic()-t0:.1f}s\n")

    for i, (origem, destino) in enumerate(ROTAS, 1):
        params = ParametrosRota(
            origem=origem,
            destino=destino,
            veiculo=2,
            eixos=3,
            preco_combustivel=6.50,
            consumo_km_l=2.5,
            tipo_carga="todas",
            site="qualp",
        )
        print(f"[{i}/{len(ROTAS)}] {origem} → {destino}")
        t = time.monotonic()
        try:
            resultado = await scraper.consultar(params, delay_segundos=0)
            duracao = time.monotonic() - t
            print(f"  OK  {duracao:.1f}s  dist={resultado.distancia_km}km  pedagio={resultado.valor_pedagio}  total={resultado.valor_total}")
        except Exception as e:
            duracao = time.monotonic() - t
            print(f"  ERRO  {duracao:.1f}s  {type(e).__name__}: {e}")
        print()

    await scraper.encerrar_sessao()
    print("Concluido.")

asyncio.run(main())
