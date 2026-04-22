"""
Diagnóstico passo a passo do QualPScraper.
Executa UMA rota e mede o tempo de cada etapa individualmente.
"""

import asyncio
import time
from pathlib import Path
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

import random
import sys

USUARIO  = "ti@real94.com.br"
SENHA    = "Real3636@@"
VEICULO       = 2      # 1=Carro 2=Caminhão 3=Ônibus 4=Moto
EIXOS         = 5
CONSUMO       = 2.50
PRECO         = 7.25
TABELA_FRETE  = "B"   # "A" | "B" | "C" | "D"

_ORIGEM_FIXA = "Tres Lagoas, Mato Grosso do Sul, Brasil"

_DESTINOS = [
    "Castanhal, Para, Brasil",
    "Hortolandia, Sao Paulo, Brasil",
    "Palhoca, Santa Catarina, Brasil",
    "Santa Cruz do Rio Pardo, Sao Paulo, Brasil",
    "Sao Paulo, Sao Paulo, Brasil",
    "Cachoeirinha, Rio Grande do Sul, Brasil",
    "Porto Alegre, Rio Grande do Sul, Brasil",
    "Sapucaia do Sul, Rio Grande do Sul, Brasil",
    "Sumare, Sao Paulo, Brasil",
    "Teixeira de Freitas, Bahia, Brasil",
]

# Uso:
#   python diagnostico_qualp.py                      → origem fixa, destino aleatório
#   python diagnostico_qualp.py 9b                   → eixos=9, tabela=B
#   python diagnostico_qualp.py "ORIGEM" "DESTINO"   → rota específica
ORIGEM  = _ORIGEM_FIXA
DESTINO = random.choice(_DESTINOS)

if len(sys.argv) >= 3:
    ORIGEM  = sys.argv[1]
    DESTINO = sys.argv[2]
elif len(sys.argv) >= 2:
    import re as _re
    _m = _re.match(r"(\d+)([abcdABCD])", sys.argv[1])
    if _m:
        EIXOS        = int(_m.group(1))
        TABELA_FRETE = _m.group(2).upper()
    else:
        EIXOS = int(sys.argv[1])
SESSION  = ".qualp_session.json"
URL_BASE = "https://qualp.com.br/#/"

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
    print(f"  QualP Diagnostico")
    print(f"  {ORIGEM}  ->  {DESTINO}")
    print(f"  veiculo={VEICULO} | eixos={EIXOS} | consumo={CONSUMO} | preco={PRECO}")
    print("=" * 60)

    # 1. Browser
    t = passo("Abre browser (Chromium)...")
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=False, slow_mo=0, args=[
        "--no-sandbox", "--disable-setuid-sandbox",
        "--disable-blink-features=AutomationControlled",
    ])
    ok(t)

    # 2. Contexto
    t = passo("Carrega contexto / sessao...")
    ctx_kwargs = dict(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 800},
        locale="pt-BR",
        permissions=[],
    )
    session_file = Path(SESSION)
    if session_file.exists():
        ctx_kwargs["storage_state"] = str(session_file)
    context = await browser.new_context(**ctx_kwargs)
    page = await context.new_page()
    context.on("page", lambda p: asyncio.ensure_future(p.close()))
    page.on("dialog", lambda d: asyncio.ensure_future(d.dismiss()))
    ok(t, "sessao salva" if session_file.exists() else "sem sessao")

    # 3. Navega
    t = passo("Navega para qualp.com.br...")
    try:
        await page.goto(URL_BASE, timeout=30000, wait_until="networkidle")
        ok(t, page.url)
    except Exception as e:
        falhou(t, str(e))
        await browser.close(); await pw.stop(); return

    # 4. Popup alerta
    t = passo("Fecha popup 'Embarcador'...")
    try:
        titulo = page.locator("text=Embarcador e Transportador").first
        if await titulo.is_visible(timeout=3000):
            btn = page.locator("button:near(:text('Embarcador'))").first
            await btn.click()
            await page.wait_for_timeout(800)
            ok(t, "fechado")
        else:
            ok(t, "nao apareceu")
    except Exception:
        ok(t, "nao apareceu")

    # 5. Verifica login
    t = passo("Verifica se esta logado...")
    botao_logar = page.locator("text=Logar").first
    nao_logado = await botao_logar.is_visible(timeout=2000)
    ok(t, "NAO logado" if nao_logado else "ja logado")

    # 6-10. Login se necessário
    if nao_logado:
        t = passo("Clica botao Logar (header)...")
        try:
            await botao_logar.click()
            await page.wait_for_timeout(1500)
            ok(t)
        except Exception as e:
            falhou(t, str(e))

        t = passo("Digita e-mail...")
        try:
            campo_email = page.locator("input[type='email']").first
            await campo_email.wait_for(state="visible", timeout=10000)
            await campo_email.click()
            await page.wait_for_timeout(400)
            await campo_email.type(USUARIO, delay=80)
            ok(t)
        except Exception as e:
            falhou(t, str(e))

        t = passo("Digita senha...")
        try:
            campo_senha = page.locator("input[type='password']").first
            await campo_senha.click()
            await page.wait_for_timeout(400)
            await campo_senha.type(SENHA, delay=80)
            ok(t)
        except Exception as e:
            falhou(t, str(e))

        t = passo("Clica LOGAR e aguarda redirect...")
        try:
            buttons = page.locator("button")
            count = await buttons.count()
            for i in range(count):
                btn = buttons.nth(i)
                if (await btn.inner_text()).strip() == "LOGAR" and await btn.is_visible():
                    await btn.click()
                    break
            await page.wait_for_function(
                "() => !window.location.hash.includes('ds=login')", timeout=15000
            )
            ok(t)
        except Exception as e:
            falhou(t, str(e))

        t = passo("Salva sessao em arquivo...")
        try:
            await context.storage_state(path=SESSION)
            ok(t, SESSION)
        except Exception as e:
            falhou(t, str(e))

    # Veículo
    t = passo(f"Seleciona veiculo (id={VEICULO})...")
    indice = {2: 0, 1: 1, 3: 2, 4: 3}.get(VEICULO, 0)
    try:
        icones = page.locator(".vehicle-icons img, .vehicle-type img, [class*='vehicle'] img")
        count = await icones.count()
        if count > indice:
            await icones.nth(indice).click()
            await page.wait_for_timeout(300)
            ok(t, f"indice {indice} de {count}")
        else:
            await page.evaluate(f"() => {{ const imgs = document.querySelectorAll('[class*=\"vehicle\"] img'); if (imgs[{indice}]) imgs[{indice}].click(); }}")
            ok(t, "via JS fallback")
    except Exception as e:
        falhou(t, str(e))

    # Eixos — clica nos botões via JS (setter Vue não dispara reatividade)
    # prepend = diminuir | append = aumentar
    t = passo(f"Ajusta eixos para {EIXOS}...")
    try:
        atual = await page.evaluate(r"() => { for (const inp of document.querySelectorAll('input')) { const m = inp.value.match(/^(\d+)\s*eixos?$/i); if (m) return parseInt(m[1]); } return null; }")
        if atual is None:
            falhou(t, "campo eixos não encontrado")
        elif atual == EIXOS:
            ok(t, f"já estava em {atual}")
        else:
            aumentar = EIXOS > atual
            for _ in range(abs(EIXOS - atual)):
                await page.evaluate("""
                    (aumentar) => {
                        for (const inp of document.querySelectorAll('input')) {
                            if (/eixos?/i.test(inp.value)) {
                                const ctrl = inp.closest('.q-field__control');
                                if (!ctrl) return;
                                const sel = aumentar ? '.q-field__append' : '.q-field__prepend';
                                const icon = ctrl.querySelector(sel + ' i.cursor-pointer');
                                if (icon) icon.click();
                                return;
                            }
                        }
                    }
                """, aumentar)
                await page.wait_for_timeout(200)
            novo = await page.evaluate(r"() => { for (const inp of document.querySelectorAll('input')) { const m = inp.value.match(/^(\d+)\s*eixos?$/i); if (m) return inp.value; } return '?'; }")
            ok(t, f"{atual} eixos -> {novo}")
    except Exception as e:
        falhou(t, str(e))

    # Consumo
    t = passo(f"Digita consumo ({CONSUMO} km/l)...")
    consumo_str = f"{CONSUMO:.1f}".replace(".", ",")
    try:
        campo = page.get_by_role("textbox", name="Consumo KM/L")
        await campo.wait_for(state="visible", timeout=5000)
        await campo.click(click_count=3, force=True)
        await page.wait_for_timeout(200)
        await campo.type(consumo_str, delay=80)
        await page.wait_for_timeout(300)
        ok(t, f"campo='{await campo.input_value()}'")
    except Exception as e:
        falhou(t, str(e))

    # Preço combustível
    t = passo(f"Digita preco combustivel ({PRECO})...")
    preco_str = f"{PRECO:.2f}".replace(".", ",")
    try:
        campo = page.get_by_role("textbox", name="Preço")  # acento obrigatório
        preenchido = False
        try:
            await campo.wait_for(state="visible", timeout=5000)
            await campo.click(click_count=3, force=True)
            await page.wait_for_timeout(200)
            await campo.type(preco_str, delay=80)
            await page.wait_for_timeout(300)
            ok(t, f"campo='{await campo.input_value()}'")
            preenchido = True
        except Exception:
            pass
        if not preenchido:
            # Fallback: input[type='tel'] posição 1 (0=consumo, 1=preço)
            inputs_tel = page.locator("input[type='tel']")
            if await inputs_tel.count() >= 2:
                f = inputs_tel.nth(1)
                await f.click(click_count=3, force=True)
                await page.wait_for_timeout(200)
                await f.type(preco_str, delay=80)
                await page.wait_for_timeout(300)
                ok(t, f"fallback tel campo='{await f.input_value()}'")
            else:
                falhou(t, "campo não encontrado (nem tel fallback)")
    except Exception as e:
        falhou(t, str(e))

    # Origem
    t = passo(f"Digita origem ({ORIGEM.split(',')[0]})...")
    try:
        container = page.locator(".q-field__control:has(input[placeholder='Origem'])").first
        await container.wait_for(state="visible", timeout=8000)
        await container.click()
        await page.wait_for_timeout(600)
        await page.keyboard.type(ORIGEM, delay=80)
        await page.wait_for_timeout(3000)
        ok(t)
    except Exception as e:
        falhou(t, str(e))

    # Sugestão origem
    t = passo("Seleciona sugestao origem...")
    try:
        painel = page.locator(".waypoints-location-drawer")
        await painel.wait_for(state="visible", timeout=2000)
        await page.wait_for_timeout(200)
        sugestoes = page.locator(".waypoints-location-drawer .q-scrollarea__content > div")
        count = await sugestoes.count()
        cidade = ORIGEM.split(",")[0].strip().lower()
        alvo = 0
        for i in range(count):
            txt = (await sugestoes.nth(i).inner_text()).strip().lower()
            if txt.count(cidade) >= 2:
                alvo = i; break
        await sugestoes.nth(alvo).click()
        await page.wait_for_timeout(200)
        ok(t, f"{count} sugestoes, indice {alvo}")
    except Exception:
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(200)
        ok(t, "fallback Enter")

    # Destino
    t = passo(f"Digita destino ({DESTINO.split(',')[0]})...")
    try:
        campo = page.locator("input[placeholder='Destino'], input[placeholder='Destino 1']").first
        await campo.wait_for(state="visible", timeout=8000)
        valor_atual = await campo.input_value()
        if valor_atual:
            await campo.click(click_count=3, force=True)
            await page.wait_for_timeout(200)
            await campo.press("Delete")
            await page.wait_for_timeout(500)
        await campo.click(force=True)
        await page.wait_for_timeout(600)
        await page.keyboard.type(DESTINO, delay=80)
        await page.wait_for_timeout(3000)
        ok(t, f"anterior='{valor_atual}'" if valor_atual else "campo vazio")
    except Exception as e:
        falhou(t, str(e))

    # Sugestão destino
    t = passo("Seleciona sugestao destino...")
    try:
        painel = page.locator(".waypoints-location-drawer")
        await painel.wait_for(state="visible", timeout=2000)
        await page.wait_for_timeout(200)
        sugestoes = page.locator(".waypoints-location-drawer .q-scrollarea__content > div")
        count = await sugestoes.count()
        cidade = DESTINO.split(",")[0].strip().lower()
        alvo = 0
        for i in range(count):
            txt = (await sugestoes.nth(i).inner_text()).strip().lower()
            if txt.count(cidade) >= 2:
                alvo = i; break
        await sugestoes.nth(alvo).click()
        await page.wait_for_timeout(200)
        ok(t, f"{count} sugestoes, indice {alvo}")
    except Exception:
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(200)
        ok(t, "fallback Enter")

    # CALCULAR
    t = passo("Clica CALCULAR...")
    try:
        btn = page.locator("button:has-text('CALCULAR')").first
        await btn.wait_for(state="attached", timeout=5000)
        await btn.click(force=True)
        ok(t)
    except Exception as e:
        falhou(t, str(e))

    # Aguarda resultado
    t = passo("Aguarda resultado (div.route-table)...")
    try:
        await page.locator("div.route-table").first.wait_for(state="visible", timeout=30000)
        ok(t)
    except Exception as e:
        falhou(t, str(e))

    # Tabela Frete A/B/C/D
    _TABELA_LABELS = {
        "A": "Tabela A - Lotação",
        "B": "Tabela B - Agregados",
        "C": "Tabela C - Lotação de alto desempenho",
        "D": "Tabela D - Agregados de alto desempenho",
    }
    t = passo(f"Seleciona tabela frete ({TABELA_FRETE})...")
    try:
        label = _TABELA_LABELS.get(TABELA_FRETE.upper(), _TABELA_LABELS["A"])
        await page.locator("label.freight-table").first.locator(".q-field__control").click()
        await page.wait_for_timeout(400)
        await page.locator(f".q-menu .q-item:has-text('{label}')").first.click()
        await page.wait_for_timeout(400)
        ok(t, label)
    except Exception as e:
        falhou(t, str(e))

    # Extrai
    t = passo("Extrai dados da tabela...")
    try:
        tabela = page.locator("div.route-table").first
        async def _label(label):
            try:
                row = tabela.locator(f"div.flex.justify-between:has-text('{label}')").first
                filhos = row.locator("> *")
                cnt = await filhos.count()
                return (await filhos.last.inner_text(timeout=2000)).strip() if cnt > 0 else ""
            except Exception:
                return ""
        duracao     = await _label("Duração")
        distancia   = await _label("Distância")
        pedagio     = await _label("Pedágio")
        combustivel = await _label("Combustível")
        total       = await _label("Custo Total")
        # Tabela frete ANTT — tr.q-tr SEM cursor-pointer (excluir praças de pedágio)
        linhas_frete = []
        rows = page.locator("tr.q-tr")
        for i in range(await rows.count()):
            row = rows.nth(i)
            cls = await row.get_attribute("class") or ""
            if "cursor-pointer" in cls:
                continue
            cols = row.locator("td.q-td")
            if await cols.count() >= 2:
                carga = (await cols.nth(0).inner_text()).strip()
                valor = (await cols.nth(1).inner_text()).strip().replace("\xa0", "")
                if "R$" in valor:
                    # Valores zerados (R$ 0,00) exibe como "0"
                    import re as _re
                    num = _re.sub(r"[^\d,]", "", valor).replace(",", ".")
                    valor_fmt = "0" if (not num or float(num) == 0) else valor
                    linhas_frete.append((carga, valor_fmt))

        # Praças de pedágio — tr.q-tr COM cursor-pointer, dentro de card-tolls
        pedagios = []
        toll_rows = page.locator("div.card-tolls tr.q-tr.cursor-pointer")
        for i in range(await toll_rows.count()):
            cols = toll_rows.nth(i).locator("td.q-td")
            if await cols.count() >= 2:
                col0 = await cols.nth(0).inner_text()
                col1 = await cols.nth(1).inner_text()
                # col0: "P3 - Jacarezinho\nBR-369 - KM 1.500"
                partes0 = [p.strip() for p in col0.strip().splitlines() if p.strip()]
                nome = partes0[0] if partes0 else ""
                rodovia = partes0[1] if len(partes0) > 1 else ""
                # col1: "R$ 64,00\n (12,80 eixo)"
                partes1 = [p.strip() for p in col1.strip().splitlines() if p.strip()]
                tarifa = partes1[0].replace("\xa0", "") if partes1 else ""
                por_eixo = partes1[1].strip("() ") if len(partes1) > 1 else ""
                if nome and tarifa:
                    pedagios.append((nome, rodovia, tarifa, por_eixo))

        ok(t)
        print()
        print("  --- Resultado -----------------------------------")
        print(f"  Duracao    : {duracao}")
        print(f"  Distancia  : {distancia}")
        print(f"  Pedagio    : {pedagio}")
        print(f"  Combustivel: {combustivel}")
        print(f"  Custo Total: {total}")
        if linhas_frete:
            print("  --- Tabela Frete ANTT ---------------------------")
            for carga, valor in linhas_frete:
                print(f"  {carga:<30} {valor}")
        if pedagios:
            print(f"  --- Praças de Pedágio ({len(pedagios)}) -----------------------")
            for nome, rodovia, tarifa, por_eixo in pedagios:
                print(f"  {nome:<30} {tarifa:>12}  {por_eixo}  {rodovia}")
        print("  -------------------------------------------------")
    except Exception as e:
        falhou(t, str(e))

    print()
    input("Pressione ENTER para fechar o browser...")
    await context.close()
    await browser.close()
    await pw.stop()


asyncio.run(main())
