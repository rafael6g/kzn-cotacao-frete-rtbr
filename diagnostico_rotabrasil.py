"""
Diagnóstico passo a passo do RotasBrasilScraper.
Executa UMA rota e mede o tempo de cada etapa individualmente.

Uso:
    .venv/Scripts/python diagnostico_rotabrasil.py          # aleatório, 5 eixos, tabela A
    .venv/Scripts/python diagnostico_rotabrasil.py 9a       # 9 eixos, tabela A
    .venv/Scripts/python diagnostico_rotabrasil.py 6b       # 6 eixos, tabela B
"""

import asyncio
import time
import random
import sys
import re as _re

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

# ── Configuração ──────────────────────────────────────────────────────
VEICULO       = 2      # 1=Carro 2=Caminhão 3=Ônibus 4=Moto
EIXOS         = 5
CONSUMO       = 2.50
PRECO         = 7.25
TABELA_FRETE  = "A"   # "A" | "B" | "C" | "D"

URL_BASE = "https://rotasbrasil.com.br"

_CIDADES = [
    "Londrina, Parana, Brasil",
    "Curitiba, Parana, Brasil",
    "Maringa, Parana, Brasil",
    "Cascavel, Parana, Brasil",
    "Ponta Grossa, Parana, Brasil",
    "Sao Paulo, Sao Paulo, Brasil",
    "Campinas, Sao Paulo, Brasil",
    "Ribeirao Preto, Sao Paulo, Brasil",
    "Santos, Sao Paulo, Brasil",
    "Belo Horizonte, Minas Gerais, Brasil",
    "Uberlandia, Minas Gerais, Brasil",
    "Porto Alegre, Rio Grande do Sul, Brasil",
    "Caxias do Sul, Rio Grande do Sul, Brasil",
    "Florianopolis, Santa Catarina, Brasil",
    "Joinville, Santa Catarina, Brasil",
    "Goiania, Goias, Brasil",
    "Brasilia, Distrito Federal, Brasil",
    "Salvador, Bahia, Brasil",
    "Recife, Pernambuco, Brasil",
    "Fortaleza, Ceara, Brasil",
]

# Uso: python diagnostico_rotabrasil.py [Nletra]  ex: 5a  9b  2c
_par = random.sample(_CIDADES, 2)
ORIGEM, DESTINO = _par[0], _par[1]

if len(sys.argv) >= 2:
    _m = _re.match(r"(\d+)([abcdABCD])", sys.argv[1])
    if _m:
        EIXOS        = int(_m.group(1))
        TABELA_FRETE = _m.group(2).upper()
    else:
        EIXOS = int(sys.argv[1])

# ── Seletores ─────────────────────────────────────────────────────────
SEL_ORIGEM      = "#txtEnderecoPartida"
SEL_DESTINO     = "#txtEnderecoChegada"
SEL_COMBUSTIVEL = "#precoCombustivel"
SEL_CONSUMO     = "#consumo"
SEL_SELECT_CARGA   = "#selectCarga"
SEL_SELECT_TABELA  = "#selectTabela"
SEL_BTN_EIXO    = "#divMostrarEixo"
SEL_RESULTADO   = "div.routeResult.active"
SEL_CAPTCHA     = "#recaptchaV2"

_VEICULO_CLASSES = {1: "carro", 2: "caminhao", 3: "onibus", 4: "moto"}

# ── Helpers ───────────────────────────────────────────────────────────
_step = 0

def passo(descricao: str):
    global _step
    _step += 1
    print(f"[{_step:02d}] {descricao:<45}", end="", flush=True)
    return time.perf_counter()

def ok(t0: float, extra: str = ""):
    elapsed = time.perf_counter() - t0
    sufixo = f"  ({extra})" if extra else ""
    print(f"OK  {elapsed:.1f}s{sufixo}")

def falhou(t0: float, erro: str):
    elapsed = time.perf_counter() - t0
    print(f"ERRO  {elapsed:.1f}s  ->  {erro}")


# ── Diagnóstico ───────────────────────────────────────────────────────

async def main():
    global _step
    _step = 0
    print("=" * 60)
    print(f"  RotasBrasil Diagnostico")
    print(f"  {ORIGEM}  ->  {DESTINO}")
    print(f"  veiculo={VEICULO} | eixos={EIXOS} | consumo={CONSUMO} | preco={PRECO} | tabela={TABELA_FRETE}")
    print("=" * 60)

    # [01] Browser
    t = passo("Abre browser (Chromium)...")
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=False, slow_mo=0, args=[
        "--no-sandbox", "--disable-setuid-sandbox",
        "--disable-blink-features=AutomationControlled",
    ])
    ok(t)

    # [02] Contexto
    t = passo("Cria contexto...")
    context = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1366, "height": 768},
        locale="pt-BR",
    )
    page = await context.new_page()
    ok(t)

    # [03] Navega
    t = passo("Navega para rotasbrasil.com.br...")
    try:
        await page.goto(URL_BASE, wait_until="networkidle", timeout=30000)
        ok(t, page.url)
    except Exception as e:
        falhou(t, str(e))
        await browser.close()
        return

    # [04] Seleciona veículo
    t = passo(f"Seleciona veiculo (id={VEICULO})...")
    try:
        classe = _VEICULO_CLASSES.get(VEICULO, "caminhao")
        await page.click(f"div.icon-veiculo.{classe}", timeout=3000)
        ok(t, f"clicou .{classe}")
    except Exception:
        await page.evaluate(f"document.getElementById('veiculo').value = '{VEICULO}'")
        ok(t, "via JS fallback")

    # [05] Seleciona eixos
    t = passo(f"Seleciona eixos ({EIXOS})...")
    try:
        await page.wait_for_selector(SEL_BTN_EIXO, state="visible", timeout=3000)
        await page.click(SEL_BTN_EIXO)
        sel_eixo = f"div.eixoDiv[eixoid='{EIXOS}']"
        await page.wait_for_selector(sel_eixo, state="visible", timeout=3000)
        await page.click(sel_eixo)
        ok(t, f"painel visual")
    except Exception:
        await page.evaluate(f"""
            var el = document.getElementById('eixo');
            if (el) {{ el.value = '{EIXOS}'; el.dispatchEvent(new Event('change', {{bubbles: true}})); }}
        """)
        ok(t, "via JS fallback")

    # [06] Preenche combustível
    t = passo(f"Preenche combustivel ({PRECO})...")
    try:
        preco_str = f"{PRECO:.2f}".replace(".", ",")
        await page.fill(SEL_COMBUSTIVEL, preco_str)
        ok(t, f"valor='{await page.input_value(SEL_COMBUSTIVEL)}'")
    except Exception as e:
        falhou(t, str(e))

    # [07] Preenche consumo
    t = passo(f"Preenche consumo ({CONSUMO} km/l)...")
    try:
        consumo_str = f"{CONSUMO:.2f}".replace(".", ",")
        await page.fill(SEL_CONSUMO, consumo_str)
        ok(t, f"valor='{await page.input_value(SEL_CONSUMO)}'")
    except Exception as e:
        falhou(t, str(e))

    # [08] Seleciona tabela frete
    t = passo(f"Seleciona tabela frete ({TABELA_FRETE})...")
    try:
        await page.select_option(SEL_SELECT_TABELA, label=f"Tabela {TABELA_FRETE}")
        ok(t, f"Tabela {TABELA_FRETE}")
    except Exception as e:
        falhou(t, str(e))

    # [09] Seleciona carga = todas
    t = passo("Seleciona carga (todas)...")
    try:
        await page.select_option(SEL_SELECT_CARGA, "todas")
        ok(t)
    except Exception as e:
        falhou(t, str(e))

    # [10] Digita origem
    t = passo(f"Digita origem ({ORIGEM.split(',')[0]})...")
    try:
        await page.fill(SEL_ORIGEM, "")
        await page.type(SEL_ORIGEM, ORIGEM, delay=random.randint(10, 25))
        await page.wait_for_timeout(1000)
        ok(t)
    except Exception as e:
        falhou(t, str(e))

    # [11] Seleciona sugestão origem
    t = passo("Seleciona sugestao origem...")
    try:
        loc = page.locator(".ui-autocomplete .ui-menu-item").first
        await loc.wait_for(state="visible", timeout=1000)
        sugestao = (await loc.inner_text()).strip()
        await loc.click()
        await page.locator(".ui-autocomplete").wait_for(state="hidden", timeout=2000)
        ok(t, sugestao[:40])
    except Exception:
        await page.press(SEL_ORIGEM, "Tab")
        ok(t, "fallback Tab")

    # [12] Digita destino
    t = passo(f"Digita destino ({DESTINO.split(',')[0]})...")
    try:
        await page.fill(SEL_DESTINO, "")
        await page.type(SEL_DESTINO, DESTINO, delay=random.randint(10, 25))
        await page.wait_for_timeout(1000)
        ok(t)
    except Exception as e:
        falhou(t, str(e))

    # [13] Seleciona sugestão destino
    t = passo("Seleciona sugestao destino...")
    try:
        loc = page.locator(".ui-autocomplete .ui-menu-item").first
        await loc.wait_for(state="visible", timeout=1000)
        sugestao = (await loc.inner_text()).strip()
        await loc.click()
        await page.locator(".ui-autocomplete").wait_for(state="hidden", timeout=2000)
        ok(t, sugestao[:40])
    except Exception:
        await page.press(SEL_DESTINO, "Tab")
        ok(t, "fallback Tab")

    # [14] Verifica captcha
    t = passo("Verifica captcha...")
    try:
        display = await page.evaluate("document.getElementById('recaptchaV2')?.style?.display")
        if display and display != "none":
            falhou(t, "reCAPTCHA v2 ATIVO — intervenção manual necessária")
        else:
            ok(t, "sem captcha")
    except Exception as e:
        falhou(t, str(e))

    # [15] Clica BUSCAR
    t = passo("Clica BUSCAR (via JS)...")
    try:
        tem_anterior = await page.query_selector(SEL_RESULTADO) is not None
        await page.evaluate("document.getElementById('btnSubmit').click()")
        if tem_anterior:
            try:
                await page.wait_for_selector(SEL_RESULTADO, state="hidden", timeout=5000)
            except Exception:
                pass
        ok(t, "anterior removido" if tem_anterior else "primeira consulta")
    except Exception as e:
        falhou(t, str(e))

    # [16] Aguarda resultado
    t = passo("Aguarda resultado (div.routeResult.active)...")
    try:
        await page.wait_for_selector(SEL_RESULTADO, state="visible", timeout=30000)
        ok(t)
    except Exception as e:
        falhou(t, str(e))

    # [17] Extrai dados
    t = passo("Extrai dados do resultado...")
    try:
        async def _txt(sel):
            try:
                el = await page.query_selector(sel)
                return (await el.inner_text()).strip() if el else ""
            except Exception:
                return ""

        duracao    = await _txt("div.color-primary-500")
        distancia  = await _txt("div.distance")
        pedagio    = await _txt("span.vlPedagio")
        combustivel= await _txt("span.vlCombustivel")
        total      = await _txt("div.results b")
        rota       = await _txt(".titulo")

        fretes = await page.evaluate("""
            () => {
                const r = {};
                document.querySelectorAll('#tabelaDeFrete0 .valorFreteMin').forEach(row => {
                    const nome = row.querySelector('.valorFreteMinDados.text-left')?.innerText?.trim().replace(/:\\s*$/, '').trim();
                    const val  = row.querySelector('.valorFreteMinDados.text-right')?.innerText?.trim();
                    if (nome && val) r[nome] = val;
                });
                return r;
            }
        """)

        ok(t)
        print()
        print("  --- Resultado -----------------------------------")
        print(f"  Duracao    : {duracao}")
        print(f"  Distancia  : {distancia}")
        print(f"  Rota       : {rota[:60] if rota else ''}")
        print(f"  Pedagio    : {pedagio}")
        print(f"  Combustivel: {combustivel}")
        print(f"  Custo Total: {total}")
        if fretes:
            print("  --- Tabela Frete ANTT ---------------------------")
            for carga, valor in fretes.items():
                import re as _re2
                num = _re2.sub(r"[^\d,]", "", valor).replace(",", ".")
                valor_fmt = "0" if (not num or float(num) == 0) else valor
                print(f"  {carga:<30} {valor_fmt}")
        print("  -------------------------------------------------")
    except Exception as e:
        falhou(t, str(e))

    print()
    input("Pressione ENTER para fechar o browser...")
    await context.close()
    await browser.close()
    await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
