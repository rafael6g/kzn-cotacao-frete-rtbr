"""
Diagnóstico passo a passo do QualPScraper.
Executa UMA rota e mede o tempo de cada etapa individualmente.
"""

import asyncio
import time
from pathlib import Path
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

# ── Configuração ──────────────────────────────────────────────────────
USUARIO  = "ti@real94.com.br"
SENHA    = "Real3636@@"
ORIGEM   = "Londrina, Parana, Brasil"
DESTINO  = "Sao Paulo, Sao Paulo, Brasil"
VEICULO  = 2      # 1=Carro 2=Caminhão 3=Ônibus 4=Moto
EIXOS    = 5
CONSUMO  = 2.50
PRECO    = 7.25
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

    # Eixos
    t = passo(f"Ajusta eixos para {EIXOS}...")
    try:
        atual = await page.evaluate(r"() => { const inp = Array.from(document.querySelectorAll('input')).find(i => /^\d+ eixos$/.test(i.value)); return inp ? parseInt(inp.value) : 6; }")
        if atual == EIXOS:
            ok(t, f"ja estava em {atual}")
        else:
            await page.evaluate(f"""
                () => {{
                    const inp = Array.from(document.querySelectorAll('input'))
                        .find(i => /^\\d+ eixos$/.test(i.value));
                    if (!inp) return;
                    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                    setter.call(inp, '{EIXOS} eixos');
                    inp.dispatchEvent(new Event('input', {{bubbles: true}}));
                    inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                }}
            """)
            await page.wait_for_timeout(300)
            novo = await page.evaluate(r"() => { const inp = Array.from(document.querySelectorAll('input')).find(i => /^\d+ eixos$/.test(i.value)); return inp ? inp.value : '?'; }")
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
        campo = page.get_by_role("textbox", name="Preco")
        await campo.wait_for(state="visible", timeout=5000)
        await campo.click(click_count=3, force=True)
        await page.wait_for_timeout(200)
        await campo.type(preco_str, delay=80)
        await page.wait_for_timeout(300)
        ok(t, f"campo='{await campo.input_value()}'")
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
        await painel.wait_for(state="visible", timeout=5000)
        sugestoes = page.locator(".waypoints-location-drawer .q-scrollarea__content > div")
        count = await sugestoes.count()
        cidade = ORIGEM.split(",")[0].strip().lower()
        alvo = 0
        for i in range(count):
            txt = (await sugestoes.nth(i).inner_text()).strip().lower()
            if txt.count(cidade) >= 2:
                alvo = i; break
        await sugestoes.nth(alvo).click()
        await page.wait_for_timeout(800)
        ok(t, f"{count} sugestoes, indice {alvo}")
    except Exception as e:
        falhou(t, str(e))

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
        await painel.wait_for(state="visible", timeout=5000)
        sugestoes = page.locator(".waypoints-location-drawer .q-scrollarea__content > div")
        count = await sugestoes.count()
        cidade = DESTINO.split(",")[0].strip().lower()
        alvo = 0
        for i in range(count):
            txt = (await sugestoes.nth(i).inner_text()).strip().lower()
            if txt.count(cidade) >= 2:
                alvo = i; break
        await sugestoes.nth(alvo).click()
        await page.wait_for_timeout(800)
        ok(t, f"{count} sugestoes, indice {alvo}")
    except Exception as e:
        falhou(t, str(e))

    # CALCULAR
    t = passo("Clica CALCULAR...")
    try:
        btn = page.locator("button:has-text('CALCULAR')").first
        await btn.wait_for(state="visible", timeout=5000)
        await btn.click()
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
        duracao     = await _label("Duracao")
        distancia   = await _label("Distancia")
        pedagio     = await _label("Pedagio")
        combustivel = await _label("Combustivel")
        total       = await _label("Custo Total")
        ok(t)
        print()
        print("  --- Resultado -----------------------------------")
        print(f"  Duracao    : {duracao}")
        print(f"  Distancia  : {distancia}")
        print(f"  Pedagio    : {pedagio}")
        print(f"  Combustivel: {combustivel}")
        print(f"  Custo Total: {total}")
        print("  -------------------------------------------------")
    except Exception as e:
        falhou(t, str(e))

    print()
    input("Pressione ENTER para fechar o browser...")
    await context.close()
    await browser.close()
    await pw.stop()


asyncio.run(main())
