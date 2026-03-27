"""
Script de diagnóstico — executa UMA consulta no rotasbrasil.com.br
e salva o HTML do #painelDetalhes para identificar os seletores reais.

Uso:
    python diagnostico_scraper.py
"""

import asyncio
import sys
import random
from pathlib import Path
from playwright.async_api import async_playwright


async def _digitar_humano(page, seletor: str, texto: str) -> None:
    await page.click(seletor)
    await page.keyboard.press("Control+a")
    await page.keyboard.press("Delete")
    await asyncio.sleep(0.15)
    for char in texto:
        await page.keyboard.type(char)
        if char in (",", "."):
            delay = random.uniform(0.25, 0.45)
        elif char == " ":
            delay = random.uniform(0.18, 0.32)
        else:
            delay = random.uniform(0.10, 0.22)
        if random.random() < 0.15:
            delay += random.uniform(0.20, 0.50)
        await asyncio.sleep(delay)

ORIGEM  = "Londrina, Paraná, Brasil"
DESTINO = "Curitiba, Paraná, Brasil"
VEICULO_ID = 2      # caminhão
EIXOS = 6
COMBUSTIVEL = "7,25"
CONSUMO = "2,50"

OUTPUT_HTML = Path("diagnostico_resultado.html")
OUTPUT_TXT  = Path("diagnostico_resultado.txt")


async def _clicar_primeiro_autocomplete(page, campo_sel: str) -> None:
    """
    Aguarda o painel jQuery UI autocomplete ficar visível e clica no 1º item VISÍVEL.
    Usa page.locator() com filtro :visible para evitar clicar em itens de listas antigas.
    """
    sel_item = ".ui-autocomplete .ui-menu-item:visible, .ui-menu-item:visible"
    try:
        # Aguarda pelo menos um item visível
        loc = page.locator(".ui-autocomplete .ui-menu-item").first
        await loc.wait_for(state="visible", timeout=4000)
        texto = await loc.inner_text()
        print(f"  Clicando em: '{texto.strip()[:50]}'")
        await loc.click()
        # Aguarda lista fechar antes do próximo campo
        try:
            await page.locator(".ui-autocomplete").wait_for(state="hidden", timeout=2000)
        except Exception:
            pass
        await page.wait_for_timeout(500)
    except Exception as e:
        print(f"  Autocomplete não apareceu ({e}) — usando Tab")
        await page.press(campo_sel, "Tab")
        await page.wait_for_timeout(600)


async def main():
    print("Iniciando Playwright...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=200)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="pt-BR",
        )
        page = await context.new_page()

        print("Acessando rotasbrasil.com.br...")
        await page.goto("https://rotasbrasil.com.br", timeout=30000, wait_until="networkidle")
        print("Página carregada.")

        # 1. Seleciona veículo (caminhão = veiculoId="2")
        print(f"Selecionando veículo {VEICULO_ID}...")
        try:
            await page.click(f".icon-veiculo[veiculoId='{VEICULO_ID}']", timeout=5000)
            print("  Veículo clicado OK")
        except Exception as e:
            print(f"  Clique no veículo falhou: {e} — setando via JS")
            await page.evaluate(f"document.getElementById('veiculo').value = '{VEICULO_ID}'")

        await page.wait_for_timeout(1000)

        # 1b. Eixos — clica #divMostrarEixo depois div.eixoDiv[eixoid='6']
        print(f"Selecionando eixos: {EIXOS}...")
        try:
            await page.wait_for_selector("#divMostrarEixo", timeout=5000, state="visible")
            await page.click("#divMostrarEixo")
            await page.wait_for_timeout(800)
            await page.click(f"div.eixoDiv[eixoid='{EIXOS}']")
            print(f"  Eixos {EIXOS} selecionados OK")
        except Exception as e:
            print(f"  Painel eixos não disponível: {e} — setando via JS")
            await page.evaluate(f"document.getElementById('eixo').value = '{EIXOS}'")

        # 2. Preenche origem
        print(f"Preenchendo origem: {ORIGEM}")
        await _digitar_humano(page, "#txtEnderecoPartida", ORIGEM)
        await _clicar_primeiro_autocomplete(page, "#txtEnderecoPartida")

        # 3. Preenche destino
        print(f"Preenchendo destino: {DESTINO}")
        await _digitar_humano(page, "#txtEnderecoChegada", DESTINO)
        await _clicar_primeiro_autocomplete(page, "#txtEnderecoChegada")

        # 4. Combustível
        print(f"Combustível: {COMBUSTIVEL} | Consumo: {CONSUMO}")
        await _digitar_humano(page, "#precoCombustivel", COMBUSTIVEL)
        await asyncio.sleep(random.uniform(0.3, 0.6))
        await _digitar_humano(page, "#consumo", CONSUMO)

        # 6. Clica em BUSCAR
        print("Clicando em BUSCAR...")
        await page.click("#btnSubmit")

        # 5b. Tipo de carga
        print("Selecionando tipo de carga: Carga Geral (353)...")
        try:
            await page.select_option("#selectCarga", "353")
            print("  Tipo de carga OK")
        except Exception as e:
            print(f"  selectCarga não encontrado: {e}")

        # 6. Clica em BUSCAR via JS (clique direto falha no site)
        print("Clicando em BUSCAR via JS...")
        await page.evaluate("document.getElementById('btnSubmit').click()")

        # 7. Aguarda div.routeResult.active
        print("Aguardando div.routeResult.active...")
        try:
            await page.wait_for_selector("div.routeResult.active", state="visible", timeout=30000)
            await page.wait_for_timeout(2000)
            print("Resultado carregado!")
        except Exception as e:
            print(f"  TIMEOUT: {e}")
            html_full = await page.content()
            Path("diagnostico_pagina_completa.html").write_text(html_full, encoding="utf-8")
            print("  Página completa salva em diagnostico_pagina_completa.html")
            await browser.close()
            return

        # 8. Salva HTML do painel
        html_painel = await page.inner_html("#painelResults")
        texto_painel = await page.inner_text("#painelResults")

        OUTPUT_HTML.write_text(html_painel, encoding="utf-8")
        OUTPUT_TXT.write_text(texto_painel, encoding="utf-8")

        print(f"\n{'='*60}")
        print(f"HTML salvo em: {OUTPUT_HTML}")
        print(f"Texto salvo em: {OUTPUT_TXT}")
        print(f"\nTEXTO DO PAINEL (primeiros 800 chars):")
        print(texto_painel[:800])
        print(f"{'='*60}\n")

        # Verifica campos específicos
        print("\nCAMPOS ESPECÍFICOS:")
        campos_teste = [
            ("div.routeResult.active",                       "painel ativo"),
            ("div.color-primary-500",                        "tempo"),
            ("div.distance",                                 "distância"),
            ("span.vlPedagio",                               "valor pedágio"),
            ("span.vlCombustivel",                           "valor combustível"),
            ("div.results b",                                "total"),
            ("div.valorFreteMin .valorFreteMinDados.text-right", "frete ANTT"),
            ("#countPedagiosRota0",                          "qtd pedágios"),
        ]
        for sel, nome in campos_teste:
            try:
                el = await page.query_selector(sel)
                val = (await el.inner_text()).strip() if el else "NÃO ENCONTRADO"
            except Exception:
                val = "ERRO"
            print(f"  {nome}: {val}  [{sel}]")

        # Snapshot de elementos com ID/classe em #painelResults
        snapshot = await page.evaluate("""
            () => {
                const painel = document.getElementById('painelResults');
                if (!painel) return 'painelResults não encontrado';
                const els = painel.querySelectorAll('[class], [id]');
                return Array.from(els).slice(0, 80).map(el =>
                    el.id
                        ? `#${el.id} → ${el.innerText?.trim().substring(0,80)}`
                        : `.${[...el.classList].join('.')} → ${el.innerText?.trim().substring(0,80)}`
                ).join('\\n');
            }
        """)
        print("ELEMENTOS COM ID/CLASS dentro de #painelDetalhes:")
        print(snapshot)

        await page.wait_for_timeout(3000)
        await browser.close()
        print("\nConcluído.")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main())
