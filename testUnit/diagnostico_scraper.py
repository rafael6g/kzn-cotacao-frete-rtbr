"""
Script de diagnóstico — executa UMA consulta no rotasbrasil.com.br,
extrai campos fixos + todos os tipos de carga de frete e salva em
console, TXT, HTML e Excel.

Uso:
    .venv/Scripts/python diagnostico_scraper.py
"""

import asyncio
import os
import sys
from pathlib import Path

import pandas as pd
from playwright.async_api import async_playwright

# ── Parâmetros da consulta ────────────────────────────────────────────
ORIGEM     = "Londrina, Paraná, Brasil"
DESTINO    = "Curitiba, Paraná, Brasil"
VEICULO_ID = 2      # 1=carro 2=caminhão 3=ônibus 4=moto
EIXOS      = 6
COMBUSTIVEL = "7,25"
CONSUMO     = "2,50"

_DIR = Path(__file__).parent
OUTPUT_HTML  = _DIR / "diagnostico_resultado.html"
OUTPUT_TXT   = _DIR / "diagnostico_resultado.txt"
OUTPUT_EXCEL = _DIR / "diagnostico_resultado.xlsx"


# ── Digitação com delay fixo (50ms/char) — rápida e suficiente ───────

async def _digitar_humano(page, seletor: str, texto: str) -> None:
    await page.click(seletor)
    await page.keyboard.press("Control+a")
    await page.keyboard.press("Delete")
    await page.type(seletor, texto, delay=50)


# ── Autocomplete ──────────────────────────────────────────────────────

async def _clicar_primeiro_autocomplete(page, campo_sel: str) -> None:
    try:
        loc = page.locator(".ui-autocomplete .ui-menu-item").first
        await loc.wait_for(state="visible", timeout=4000)
        texto = await loc.inner_text()
        print(f"  Autocomplete: '{texto.strip()[:50]}'")
        await loc.click()
        try:
            await page.locator(".ui-autocomplete").wait_for(state="hidden", timeout=2000)
        except Exception:
            pass
        await page.wait_for_timeout(500)
    except Exception:
        print(f"  Autocomplete não apareceu — usando Tab")
        await page.press(campo_sel, "Tab")
        await page.wait_for_timeout(600)


# ── Extração de fretes por tipo de carga ─────────────────────────────

async def _extrair_fretes_por_tipo(page) -> dict:
    """
    Extrai todos os tipos de carga diretamente do #tabelaDeFrete0,
    que exibe todos os 12 tipos quando #selectCarga = "todas".
    Retorna dict: { "Tipo_Carga_<nome>": "R$ X.XXX,XX" }
    """
    fretes = await page.evaluate("""
        () => {
            const result = {};
            document.querySelectorAll('#tabelaDeFrete0 .valorFreteMin').forEach(row => {
                const nome = row.querySelector('.valorFreteMinDados.text-left')
                                ?.innerText?.trim().replace(/:\\s*$/, '').trim();
                const val  = row.querySelector('.valorFreteMinDados.text-right')
                                ?.innerText?.trim();
                if (nome && val) result[`Tipo_Carga_${nome}`] = val;
            });
            return result;
        }
    """)
    for nome, val in fretes.items():
        print(f"  {nome}: {val}")
    return fretes


# ── Main ──────────────────────────────────────────────────────────────

async def main():
    print("Iniciando Playwright...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=50)
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

        # ── Acesso ───────────────────────────────────────────────────
        print("Acessando rotasbrasil.com.br...")
        await page.goto("https://rotasbrasil.com.br", timeout=30000, wait_until="networkidle")
        print("Página carregada.")

        # ── Veículo ───────────────────────────────────────────────────
        print(f"Selecionando veículo {VEICULO_ID}...")
        try:
            await page.click(f".icon-veiculo[veiculoId='{VEICULO_ID}']", timeout=5000)
        except Exception:
            await page.evaluate(f"document.getElementById('veiculo').value = '{VEICULO_ID}'")
        await page.wait_for_timeout(1000)

        # ── Eixos ─────────────────────────────────────────────────────
        print(f"Selecionando eixos: {EIXOS}...")
        try:
            await page.wait_for_selector("#divMostrarEixo", timeout=5000, state="visible")
            await page.click("#divMostrarEixo")
            await page.wait_for_timeout(800)
            await page.click(f"div.eixoDiv[eixoid='{EIXOS}']")
        except Exception:
            await page.evaluate(f"document.getElementById('eixo').value = '{EIXOS}'")

        # ── Endereços ─────────────────────────────────────────────────
        print(f"Preenchendo origem: {ORIGEM}")
        await _digitar_humano(page, "#txtEnderecoPartida", ORIGEM)
        await _clicar_primeiro_autocomplete(page, "#txtEnderecoPartida")

        print(f"Preenchendo destino: {DESTINO}")
        await _digitar_humano(page, "#txtEnderecoChegada", DESTINO)
        await _clicar_primeiro_autocomplete(page, "#txtEnderecoChegada")

        # ── Combustível / Consumo ─────────────────────────────────────
        print(f"Combustível: {COMBUSTIVEL} | Consumo: {CONSUMO}")
        await _digitar_humano(page, "#precoCombustivel", COMBUSTIVEL)
        await asyncio.sleep(0.2)
        await _digitar_humano(page, "#consumo", CONSUMO)

        # ── Tipo de carga inicial ─────────────────────────────────────
        await page.select_option("#selectCarga", "todas")

        # ── Buscar ────────────────────────────────────────────────────
        print("Clicando em BUSCAR via JS...")
        await page.evaluate("document.getElementById('btnSubmit').click()")

        # ── Aguarda resultado ─────────────────────────────────────────
        print("Aguardando div.routeResult.active...")
        try:
            await page.wait_for_selector("div.routeResult.active", state="visible", timeout=30000)
            await page.wait_for_timeout(1500)
            print("Resultado carregado!")
        except Exception as e:
            print(f"  TIMEOUT: {e}")
            Path("diagnostico_pagina_completa.html").write_text(
                await page.content(), encoding="utf-8"
            )
            print("  Página completa salva em diagnostico_pagina_completa.html")
            await browser.close()
            return

        # ── Campos fixos ──────────────────────────────────────────────
        async def txt(sel: str) -> str:
            el = await page.query_selector(sel)
            return (await el.inner_text()).strip() if el else ""

        tempo_viagem   = await txt("div.color-primary-500")
        rota_descricao = await txt(".titulo")
        distancia_km   = await txt("div.distance")
        vl_pedagio_raw = await txt("span.vlPedagio")
        vl_combustivel = await txt("span.vlCombustivel")
        total_despesas = await txt("div.results b")

        valor_pedagio = (
            f"R$ {vl_pedagio_raw}" if vl_pedagio_raw and not vl_pedagio_raw.startswith("R$")
            else vl_pedagio_raw
        )
        combustivel = f"R$ {vl_combustivel} Comb." if vl_combustivel else ""

        # ── Fretes por tipo de carga ──────────────────────────────────
        print("\nExtraindo fretes por tipo de carga...")
        fretes = await _extrair_fretes_por_tipo(page)

        # ── Salva HTML / TXT do painel ────────────────────────────────
        OUTPUT_HTML.write_text(await page.inner_html("#painelResults"), encoding="utf-8")
        OUTPUT_TXT.write_text(await page.inner_text("#painelResults"), encoding="utf-8")

        # ── Exibe no console ──────────────────────────────────────────
        SEP = "=" * 60
        print(f"\n{SEP}")
        print(f"Seq:             1")
        print(f"Origem:          {ORIGEM}")
        print(f"Destino:         {DESTINO}")
        print(f"tempo_viagem:    {tempo_viagem}")
        print(f"rota_descricao:  {rota_descricao}")
        print(f"distancia_km:    {distancia_km}")
        print(f"valor_pedagio:   {valor_pedagio}")
        print(f"combustivel:     {combustivel}")
        print(f"total Despesas:  {total_despesas}")
        for nome, val in fretes.items():
            print(f"{nome}: {val}")
        print(f"{SEP}\n")

        # ── Gera Excel ────────────────────────────────────────────────
        row = {
            "Seq":            1,
            "Origem":         ORIGEM,
            "Destino":        DESTINO,
            "tempo_viagem":   tempo_viagem,
            "rota_descricao": rota_descricao,
            "distancia_km":   distancia_km,
            "valor_pedagio":  valor_pedagio,
            "combustivel":    combustivel,
            "total Despesas": total_despesas,
        }
        row.update(fretes)

        pd.DataFrame([row]).to_excel(OUTPUT_EXCEL, index=False)
        print(f"Arquivos salvos:")
        print(f"  {OUTPUT_EXCEL}")
        print(f"  {OUTPUT_HTML}")
        print(f"  {OUTPUT_TXT}")

        if sys.platform == "win32":
            os.startfile(str(OUTPUT_EXCEL.resolve()))

        await page.wait_for_timeout(2000)
        await browser.close()
        print("\nConcluído.")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main())
