import asyncio
import time
from app.infrastructure.scrapers.qualp_scraper import QualPScraper

USUARIO = "ti@real94.com.br"
SENHA   = "Real3636@@"

_log: list[str] = []
_t0 = time.perf_counter()

def r(passo: str, status: str = "OK"):
    elapsed = time.perf_counter() - _t0
    linha = f"[{elapsed:5.1f}s] {passo} — {status}"
    _log.append(linha)
    print(linha, flush=True)

def lista():
    print("\n" + "="*50, flush=True)
    for l in _log:
        print(l)
    print("="*50, flush=True)

async def main():
    global _t0
    _t0 = time.perf_counter()
    scraper = QualPScraper(usuario=USUARIO, senha=SENHA, headless=False, session_file=".qualp_session.json")

    try:
        # [1+2] Abre e loga
        r("[1+2] Abrindo e logando", "")
        await scraper.iniciar_sessao()
        page = scraper._page
        r("[1+2] Logado")

        # [3] Aumenta eixos
        r("[3] Lendo eixos atual", "")
        atual = await page.evaluate(
            r"() => { const inp = Array.from(document.querySelectorAll('input')).find(i => /^\d+ eixos$/.test(i.value)); return inp ? inp.value : 'nao encontrado'; }"
        )
        r("[3] Eixos atual", atual)

        btn_mais = page.locator("div.q-field__append").first
        await btn_mais.click()
        await page.wait_for_timeout(500)

        novo = await page.evaluate(
            r"() => { const inp = Array.from(document.querySelectorAll('input')).find(i => /^\d+ eixos$/.test(i.value)); return inp ? inp.value : 'nao encontrado'; }"
        )
        r("[3] Eixos apos +1 clique", novo)

        lista()
        print(f"\nParado. Aguardando...", flush=True)
        await asyncio.sleep(99999)

    except Exception as e:
        r("ERRO", f"{type(e).__name__}: {e}")
        lista()
        await asyncio.sleep(99999)

asyncio.run(main())
