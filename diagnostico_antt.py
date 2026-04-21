"""
Diagnóstico visual da Calculadora ANTT (calculadorafrete.antt.gov.br).
Abre o browser, busca a distância no RotasBrasil e preenche a calculadora ANTT.

Uso:
    .venv/Scripts/python diagnostico_antt.py              # eixos=5 tabela=A aleatório
    .venv/Scripts/python diagnostico_antt.py 2b           # 2 eixos, tabela B
    .venv/Scripts/python diagnostico_antt.py 6c           # 6 eixos, tabela C
    .venv/Scripts/python diagnostico_antt.py 5ar          # 5 eixos, tabela A, retorno vazio
    .venv/Scripts/python diagnostico_antt.py 6b "Londrina, Parana" "Sao Paulo, Sao Paulo"
"""

import asyncio
import time
import re
import sys
import random

from playwright.async_api import async_playwright

# ── Configuração ──────────────────────────────────────────────────────
EIXOS        = 5
TABELA_FRETE = "A"   # "A" | "B" | "C" | "D"
RETORNO_VAZIO = False

URL_ROTASBRASIL = "https://rotasbrasil.com.br"
URL_ANTT        = "https://calculadorafrete.antt.gov.br/"

_CIDADES = [
    "Londrina, Parana, Brasil",
    "Curitiba, Parana, Brasil",
    "Maringa, Parana, Brasil",
    "Sao Paulo, Sao Paulo, Brasil",
    "Campinas, Sao Paulo, Brasil",
    "Belo Horizonte, Minas Gerais, Brasil",
    "Porto Alegre, Rio Grande do Sul, Brasil",
    "Goiania, Goias, Brasil",
    "Brasilia, Distrito Federal, Brasil",
    "Salvador, Bahia, Brasil",
    "Recife, Pernambuco, Brasil",
]

_par = random.sample(_CIDADES, 2)
ORIGEM, DESTINO = _par[0], _par[1]

if len(sys.argv) >= 2:
    _m = re.match(r"(\d+)([abcdABCD])(r?)", sys.argv[1], re.IGNORECASE)
    if _m:
        EIXOS         = int(_m.group(1))
        TABELA_FRETE  = _m.group(2).upper()
        RETORNO_VAZIO = _m.group(3).lower() == "r"
    else:
        try:
            EIXOS = int(sys.argv[1])
        except ValueError:
            pass

if len(sys.argv) >= 4:
    ORIGEM  = sys.argv[2]
    DESTINO = sys.argv[3]

# Eixos válidos na ANTT: 2,3,4,5,6,7,9 (sem 8)
_EIXOS_VALIDOS = [2, 3, 4, 5, 6, 7, 9]
EIXOS_ANTT = max((e for e in _EIXOS_VALIDOS if e <= EIXOS), default=2)

# Tabela → (É composição veicular?, Alto desempenho?)
_TABELA_ANTT = {
    "A": (True,  False),
    "B": (False, False),
    "C": (True,  True),
    "D": (False, True),
}

# ── Helpers ───────────────────────────────────────────────────────────
_step = 0

def passo(descricao: str):
    global _step
    _step += 1
    print(f"[{_step:02d}] {descricao:<48}", end="", flush=True)
    return time.perf_counter()

def ok(t0: float, extra: str = ""):
    elapsed = time.perf_counter() - t0
    sufixo = f"  ({extra})" if extra else ""
    print(f"OK  {elapsed:.1f}s{sufixo}")

def falhou(t0: float, erro: str):
    elapsed = time.perf_counter() - t0
    print(f"ERRO  {elapsed:.1f}s  ->  {erro}")


async def main():
    global _step
    _step = 0
    composicao, alto_desempenho = _TABELA_ANTT.get(TABELA_FRETE.upper(), (True, False))

    print("=" * 62)
    print(f"  ANTT Calculadora Frete — Diagnóstico Visual")
    print(f"  {ORIGEM.split(',')[0]}  ->  {DESTINO.split(',')[0]}")
    print(f"  eixos={EIXOS}→{EIXOS_ANTT} | tabela={TABELA_FRETE} | retorno_vazio={RETORNO_VAZIO}")
    print(f"  composicao={composicao} | alto_desempenho={alto_desempenho}")
    print("=" * 62)

    # [01] Abre browser
    t = passo("Abre browser (Chromium)...")
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=False, slow_mo=0, args=[
        "--no-sandbox", "--disable-setuid-sandbox",
        "--disable-blink-features=AutomationControlled",
    ])
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

    # ── ETAPA 1: RotasBrasil → buscar distância ───────────────────────

    # [02] Navega para RotasBrasil
    t = passo("Navega para RotasBrasil...")
    try:
        await page.goto(URL_ROTASBRASIL, wait_until="networkidle", timeout=30000)
        ok(t, page.url)
    except Exception as e:
        falhou(t, str(e))
        await browser.close(); await pw.stop(); return

    # [03] Digita origem
    t = passo(f"Digita origem ({ORIGEM.split(',')[0]})...")
    try:
        await page.fill("#txtEnderecoPartida", "")
        await page.type("#txtEnderecoPartida", ORIGEM, delay=random.randint(10, 25))
        await page.wait_for_timeout(1200)
        ok(t)
    except Exception as e:
        falhou(t, str(e))

    # [04] Seleciona sugestão origem
    t = passo("Seleciona sugestao origem...")
    try:
        loc = page.locator(".ui-autocomplete .ui-menu-item").first
        await loc.wait_for(state="visible", timeout=3000)
        sugestao = (await loc.inner_text()).strip()
        await loc.click()
        await page.locator(".ui-autocomplete").wait_for(state="hidden", timeout=2000)
        ok(t, sugestao[:40])
    except Exception:
        await page.press("#txtEnderecoPartida", "Tab")
        ok(t, "fallback Tab")

    # [05] Digita destino
    t = passo(f"Digita destino ({DESTINO.split(',')[0]})...")
    try:
        await page.fill("#txtEnderecoChegada", "")
        await page.type("#txtEnderecoChegada", DESTINO, delay=random.randint(10, 25))
        await page.wait_for_timeout(1200)
        ok(t)
    except Exception as e:
        falhou(t, str(e))

    # [06] Seleciona sugestão destino
    t = passo("Seleciona sugestao destino...")
    try:
        loc = page.locator(".ui-autocomplete .ui-menu-item").first
        await loc.wait_for(state="visible", timeout=3000)
        sugestao = (await loc.inner_text()).strip()
        await loc.click()
        await page.locator(".ui-autocomplete").wait_for(state="hidden", timeout=2000)
        ok(t, sugestao[:40])
    except Exception:
        await page.press("#txtEnderecoChegada", "Tab")
        ok(t, "fallback Tab")

    # [07] Clica BUSCAR (só queremos a distância)
    t = passo("Clica BUSCAR (apenas para obter distancia)...")
    try:
        await page.evaluate("document.getElementById('btnSubmit').click()")
        ok(t)
    except Exception as e:
        falhou(t, str(e))

    # [08] Aguarda resultado e extrai distância
    t = passo("Aguarda resultado e extrai distancia...")
    distancia_str = ""
    distancia_int = 0
    try:
        await page.wait_for_selector("div.routeResult.active", state="visible", timeout=30000)
        el = await page.query_selector("div.distance")
        distancia_str = (await el.inner_text()).strip() if el else ""
        # "3.076,6 km" → 3076
        num = re.sub(r"[^\d,]", "", distancia_str.split(",")[0].replace(".", ""))
        distancia_int = int(num) if num else 0
        ok(t, f"{distancia_str} → {distancia_int} km")
    except Exception as e:
        falhou(t, str(e))

    if not distancia_int:
        print("  AVISO: distância não encontrada, usando 500 km como fallback")
        distancia_int = 500

    # ── ETAPA 2: ANTT → preencher e calcular ─────────────────────────

    # [09] Navega para ANTT
    t = passo("Navega para calculadora ANTT...")
    try:
        await page.goto(URL_ANTT, wait_until="networkidle", timeout=30000)
        ok(t, page.url)
    except Exception as e:
        falhou(t, str(e))
        await browser.close(); await pw.stop(); return

    # [10] Preenche distância
    t = passo(f"Preenche distancia ({distancia_int} km)...")
    try:
        # Tenta por id primeiro, depois por placeholder/label
        sel_dist = await page.query_selector("#Filtro_Distancia, input[name='Filtro.Distancia']")
        if not sel_dist:
            sel_dist = await page.query_selector("input[placeholder*='istancia'], input[placeholder*='km']")
        if sel_dist:
            await sel_dist.click(click_count=3)
            await sel_dist.type(str(distancia_int), delay=80)
            ok(t, f"valor={await sel_dist.input_value()}")
        else:
            falhou(t, "campo distância não encontrado")
    except Exception as e:
        falhou(t, str(e))

    # [11] Seleciona número de eixos
    t = passo(f"Seleciona eixos ({EIXOS_ANTT})...")
    try:
        sel_eixo = await page.query_selector(
            f"#Filtro_NumeroEixos, select[name='Filtro.NumeroEixos']"
        )
        if sel_eixo:
            await page.select_option(
                "#Filtro_NumeroEixos, select[name='Filtro.NumeroEixos']",
                str(EIXOS_ANTT)
            )
            ok(t, f"eixos={EIXOS_ANTT}")
        else:
            # Tenta encontrar via label "Número de Eixos" ou similar
            await page.evaluate(f"""
                const sel = document.querySelector('select[name*="Eixos"], select[id*="Eixo"]');
                if (sel) {{
                    sel.value = '{EIXOS_ANTT}';
                    sel.dispatchEvent(new Event('change', {{bubbles: true}}));
                }}
            """)
            ok(t, "via JS fallback")
    except Exception as e:
        falhou(t, str(e))

    # [12] Seleciona tipo de carga (Carga Geral = ID 5)
    t = passo("Seleciona tipo de carga (Carga Geral)...")
    try:
        await page.select_option(
            "#Filtro_IdTipoCarga, select[name='Filtro.IdTipoCarga']",
            "5"
        )
        ok(t, "Carga Geral (id=5)")
    except Exception as e:
        falhou(t, str(e))

    # Helper: clica no Bootstrap Toggle div pai para marcar/desmarcar
    # O site usa data-toggle="toggle" (Bootstrap Toggle plugin):
    # div.toggle.off = desmarcado, div.toggle (sem .off) = marcado
    # Clicar no label nativo NÃO funciona — precisa clicar no div.toggle pai
    async def _set_toggle(chk_id: str, desejado: bool) -> str:
        return await page.evaluate(f"""
            () => {{
                const chk = document.getElementById('{chk_id}');
                if (!chk) return 'nao_encontrado';
                const toggleDiv = chk.closest('.toggle[data-toggle="toggle"]');
                if (!toggleDiv) return 'toggle_nao_encontrado';
                const atual = !toggleDiv.classList.contains('off');
                if (atual !== {str(desejado).lower()}) toggleDiv.click();
                const final = !toggleDiv.classList.contains('off');
                return (final ? 'Sim' : 'Não') + ' (off=' + toggleDiv.classList.contains('off') + ')';
            }}
        """)

    # [13] Composição Veicular
    t = passo(f"Composicao veicular = {composicao}...")
    try:
        ok(t, await _set_toggle("Filtro_CargaLotacao", composicao))
    except Exception as e:
        falhou(t, str(e))

    # [14] Alto Desempenho
    t = passo(f"Alto desempenho = {alto_desempenho}...")
    try:
        ok(t, await _set_toggle("Filtro_AltoDesempenho", alto_desempenho))
    except Exception as e:
        falhou(t, str(e))

    # [15] Retorno Vazio
    t = passo(f"Retorno vazio = {RETORNO_VAZIO}...")
    try:
        ok(t, await _set_toggle("Filtro_RetornoVazio", RETORNO_VAZIO))
    except Exception as e:
        falhou(t, str(e))

    # [16] Clica CALCULAR
    t = passo("Clica CALCULAR (submit)...")
    try:
        btn = await page.query_selector(
            "input[type='submit'], button[type='submit'], input[value*='alcular'], button:has-text('Calcular')"
        )
        if btn:
            await btn.click()
            ok(t)
        else:
            await page.evaluate("document.querySelector('form').submit()")
            ok(t, "via JS submit")
    except Exception as e:
        falhou(t, str(e))

    # [17] Aguarda resultado
    t = passo("Aguarda resultado ANTT...")
    try:
        # Aguarda elemento com valor do frete aparecer
        await page.wait_for_selector(
            ".valorFrete, [class*='valorFrete'], #resultado, [id*='resultado'], "
            ".result, [class*='result']",
            state="visible", timeout=15000
        )
        ok(t)
    except Exception as e:
        falhou(t, f"{e} — resultado pode já estar visível")

    # [18] Extrai resultado
    t = passo("Extrai resultado da página...")
    try:
        html = await page.content()

        def _span_apos(rotulo: str) -> str:
            idx = html.find(rotulo)
            if idx == -1:
                return ""
            m = re.search(r"<span[^>]*>(.*?)</span>", html[idx:], re.DOTALL)
            return re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else ""

        def _valor_total() -> str:
            m = re.search(r'class="[^"]*valorFrete[^"]*"[^>]*>(.*?)</', html, re.DOTALL)
            if m:
                return re.sub(r"<[^>]+>", "", m.group(1)).strip()
            m = re.search(r"R\$\s*[\d.,]+", html)
            return m.group(0).strip() if m else ""

        tabela_nome   = _span_apos("Operação de Transporte")
        ccd           = _span_apos("Coeficiente de custo de deslocamento (CCD)")
        cc            = _span_apos("Coeficiente de custo de carga e descarga (CC)")
        valor_ida     = _span_apos("Valor de ida")
        valor_retorno = _span_apos("Valor do retorno vazio")
        valor_total   = _valor_total()

        ok(t)
        print()
        print("  --- Resultado ANTT --------------------------------------")
        print(f"  Rota          : {ORIGEM.split(',')[0]} → {DESTINO.split(',')[0]}")
        print(f"  Distancia     : {distancia_str} ({distancia_int} km)")
        print(f"  Tabela        : {tabela_nome or '(inspecionar no browser)'}")
        print(f"  CCD           : {ccd or '?'}")
        print(f"  CC            : {cc or '?'}")
        print(f"  Valor de Ida  : {valor_ida or '?'}")
        print(f"  Retorno Vazio : {valor_retorno or '?'}")
        print(f"  Total         : {valor_total or '(inspecionar no browser)'}")
        print("  --------------------------------------------------------")
        if not tabela_nome and not valor_total:
            print()
            print("  AVISO: campos vazios — o resultado pode ter estrutura diferente.")
            print("  Inspecione o browser para identificar os seletores corretos.")
    except Exception as e:
        falhou(t, str(e))

    print()
    input("Pressione ENTER para fechar o browser...")
    await context.close()
    await browser.close()
    await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
