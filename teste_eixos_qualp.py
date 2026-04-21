"""
Teste isolado: abre QualP visível e altera eixos.
Estrutura real do campo (inspecionada via F12):
  q-field__control
    q-field__prepend > i.cursor-pointer > SVG  ← DIMINUIR (seta para baixo)
    q-field__control-container > input[value="N eixos"]
    q-field__append  > i.cursor-pointer > SVG  ← AUMENTAR (seta para cima)

Uso:
    .venv/Scripts/python teste_eixos_qualp.py 4
    .venv/Scripts/python teste_eixos_qualp.py 9
"""

import asyncio
import sys
import random

from playwright.async_api import async_playwright

URL = "https://qualp.com.br/#/"


def _j(base: int) -> int:
    return random.randint(int(base * 0.75), int(base * 1.25))


async def ler_eixos(page) -> int | None:
    return await page.evaluate(r"""
        () => {
            for (const inp of document.querySelectorAll('input')) {
                const m = inp.value.match(/^(\d+)\s*eixos?$/i);
                if (m) return parseInt(m[1]);
            }
            return null;
        }
    """)


async def main(eixos_desejados: int):
    print(f"\n{'='*50}")
    print(f"  TESTE EIXOS QUALP — alvo: {eixos_desejados} eixos")
    print(f"{'='*50}\n")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False, slow_mo=150)
        page = await (await browser.new_context(
            viewport={"width": 1280, "height": 800}, locale="pt-BR"
        )).new_page()

        print(">> Abrindo QualP...")
        await page.goto(URL, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2000)

        # Fecha popup de alerta
        try:
            if await page.locator("text=Embarcador e Transportador").first.is_visible(timeout=3000):
                await page.locator("button:near(:text('Embarcador'))").first.click()
                print(">> Popup fechado.")
                await page.wait_for_timeout(1000)
        except Exception:
            pass

        # ── 1. Lê eixos inicial ──────────────────────────────────────
        inicial = await ler_eixos(page)
        print(f"\n>> Eixos ao abrir: {inicial}")

        if inicial is None:
            print("!! Campo eixos não encontrado. Encerrando.")
            await page.wait_for_timeout(5000)
            await browser.close()
            return

        # ── 2. Calcula e clica via JS (input.value é propriedade DOM, não atributo HTML)
        diferenca = eixos_desejados - inicial
        print(f">> Diferença: {diferenca:+d}  →  {'↑' if diferenca > 0 else '↓'} {abs(diferenca)} clique(s)")

        if diferenca == 0:
            print(">> Já está correto!")
        else:
            aumentar = diferenca > 0
            for i in range(abs(diferenca)):
                clicou = await page.evaluate("""
                    (aumentar) => {
                        for (const inp of document.querySelectorAll('input')) {
                            if (/eixos?/i.test(inp.value)) {
                                const ctrl = inp.closest('.q-field__control');
                                if (!ctrl) return false;
                                const sel = aumentar ? '.q-field__append' : '.q-field__prepend';
                                const icon = ctrl.querySelector(sel + ' i.cursor-pointer');
                                if (icon) { icon.click(); return true; }
                                return false;
                            }
                        }
                        return false;
                    }
                """, aumentar)
                await page.wait_for_timeout(_j(300))
                lido = await ler_eixos(page)
                print(f"   clique {i+1}: clicou={clicou} eixos agora = {lido}")

        # ── 4. Resultado final ───────────────────────────────────────
        final = await ler_eixos(page)
        print(f"\n>> Eixos final: {final}")
        if final == eixos_desejados:
            print(">> SUCESSO!")
        else:
            print(f"!! FALHA: esperado {eixos_desejados}, obtido {final}")

        print("\n>> Browser aberto por 20s para inspeção...")
        await page.wait_for_timeout(20000)
        await browser.close()


if __name__ == "__main__":
    eixos = int(sys.argv[1]) if len(sys.argv) > 1 else 9
    asyncio.run(main(eixos))
