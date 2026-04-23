"""
Diagnóstico headless do QualP para rodar no EasyPanel/Docker.
Mesmo fluxo do diagnostico_qualp.py mas:
  - headless=True (sem janela)
  - Loga valor dos campos após cada etapa crítica
  - Tira screenshots em outputs/ (visível via /debug/screenshot/)
  - Sem input() no final — não trava o terminal
  - Credenciais via .env (settings)

Uso no bash do EasyPanel:
    python diagnostico_qualp_headless.py           # eixos=3 (padrão)
    python diagnostico_qualp_headless.py 5         # eixos=5
    python diagnostico_qualp_headless.py 9         # eixos=9
"""

import asyncio
import time
import sys
from pathlib import Path
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

# Carrega credenciais do .env
import os, sys
sys.path.insert(0, "/app")
from app.core.config import get_settings
settings = get_settings()

USUARIO = settings.qualp_usuario
SENHA   = settings.qualp_senha

# Parâmetros — eixos pode ser passado como argumento: python diagnostico_qualp_headless.py 5
VEICULO      = 2        # caminhão
EIXOS        = int(sys.argv[1]) if len(sys.argv) > 1 else 3
CONSUMO      = 2.50
PRECO        = 7.25
TABELA_FRETE = "A"

ORIGEM  = "Tres Lagoas, Mato Grosso do Sul, Brasil"
DESTINO = "Campinas, Sao Paulo, Brasil"

SESSION      = ".qualp_session.json"
URL_BASE     = "https://qualp.com.br/#/"
OUTPUTS_DIR  = Path("outputs")

# ── Helpers ───────────────────────────────────────────────────────────

_step = 0

def passo(descricao: str):
    global _step
    _step += 1
    print(f"[{_step:02d}] {descricao:<50}", end="", flush=True)
    return time.perf_counter()

def ok(t0: float, extra: str = ""):
    elapsed = time.perf_counter() - t0
    sufixo = f"  ({extra})" if extra else ""
    print(f"OK  {elapsed:.1f}s{sufixo}")

def falhou(t0: float, erro: str):
    elapsed = time.perf_counter() - t0
    print(f"ERRO  {elapsed:.1f}s  ->  {erro}")

async def campo_valor(page, placeholder: str) -> str:
    """Lê o valor atual de um input pelo placeholder."""
    try:
        return await page.evaluate(f"""
            () => {{
                const inp = document.querySelector("input[placeholder='{placeholder}']");
                return inp ? inp.value : '(não encontrado)';
            }}
        """)
    except Exception:
        return "(erro ao ler)"

async def screenshot(page, nome: str):
    """Salva screenshot em outputs/."""
    try:
        OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
        path = str(OUTPUTS_DIR / f"{nome}.png")
        await page.screenshot(path=path, full_page=False)
        print(f"        → screenshot salvo: {nome}.png  (acesse /debug/screenshot/{nome})")
    except Exception as e:
        print(f"        → screenshot falhou: {e}")


# ── Diagnóstico ───────────────────────────────────────────────────────

async def main():
    global _step
    _step = 0

    print("=" * 65)
    print("  QualP Diagnóstico HEADLESS — Docker/EasyPanel")
    print(f"  {ORIGEM}")
    print(f"  → {DESTINO}")
    print(f"  veículo={VEICULO} | eixos={EIXOS} | consumo={CONSUMO} | preço={PRECO}")
    print("=" * 65)

    if not USUARIO or not SENHA:
        print("ERRO: QUALP_USUARIO ou QUALP_SENHA não configurados no .env")
        sys.exit(1)

    # [01] Browser headless
    t = passo("Abre browser headless (Chromium)...")
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=True,
        slow_mo=0,
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
        ],
    )
    ok(t)

    # [02] Contexto
    t = passo("Carrega contexto / sessão...")
    ctx_kwargs = dict(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        viewport={"width": 1366, "height": 768},
        locale="pt-BR",
        permissions=[],
    )
    session_file = Path(SESSION)
    if session_file.exists():
        ctx_kwargs["storage_state"] = str(session_file)
    context = await browser.new_context(**ctx_kwargs)
    await context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        window.chrome = {runtime: {}};
    """)
    page = await context.new_page()
    context.on("page", lambda p: asyncio.ensure_future(p.close()))
    page.on("dialog", lambda d: asyncio.ensure_future(d.dismiss()))
    ok(t, "sessão salva" if session_file.exists() else "sem sessão")

    # [03] Navega
    t = passo("Navega para qualp.com.br...")
    try:
        await page.goto(URL_BASE, timeout=30000, wait_until="networkidle")
        ok(t, page.url[:60])
    except Exception as e:
        falhou(t, str(e))
        await screenshot(page, "diag_erro_navegacao")
        await browser.close(); await pw.stop(); return

    # [04] Popup alerta
    t = passo("Fecha popup 'Embarcador'...")
    try:
        titulo = page.locator("text=Embarcador e Transportador").first
        if await titulo.is_visible(timeout=3000):
            btn = page.locator("button:near(:text('Embarcador'))").first
            await btn.click()
            await page.wait_for_timeout(800)
            ok(t, "fechado")
        else:
            ok(t, "não apareceu")
    except Exception:
        ok(t, "não apareceu")

    # [05] Verifica login
    t = passo("Verifica se está logado...")
    botao_logar = page.locator("text=Logar").first
    nao_logado = await botao_logar.is_visible(timeout=2000)
    ok(t, "NÃO logado — fará login" if nao_logado else "já logado")

    # [06-10] Login se necessário
    if nao_logado:
        t = passo("Clica botão Logar (header)...")
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
            await screenshot(page, "diag_erro_login")

        t = passo("Salva sessão...")
        try:
            await context.storage_state(path=SESSION)
            ok(t, SESSION)
        except Exception as e:
            falhou(t, str(e))

    # [XX] Veículo
    t = passo(f"Seleciona veículo (id={VEICULO} caminhão)...")
    indice = {2: 0, 1: 1, 3: 2, 4: 3}.get(VEICULO, 0)
    try:
        icones = page.locator(".vehicle-icons img, .vehicle-type img, [class*='vehicle'] img")
        count = await icones.count()
        if count > indice:
            await icones.nth(indice).click()
            await page.wait_for_timeout(300)
            ok(t, f"índice {indice} de {count}")
        else:
            await page.evaluate(f"() => {{ const imgs = document.querySelectorAll('[class*=\"vehicle\"] img'); if (imgs[{indice}]) imgs[{indice}].click(); }}")
            ok(t, "via JS fallback")
    except Exception as e:
        falhou(t, str(e))

    # [XX] Eixos
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
            ok(t, f"{atual} → {novo}")
    except Exception as e:
        falhou(t, str(e))

    # [XX] Consumo
    t = passo(f"Preenche consumo ({CONSUMO} km/l)...")
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

    # [XX] Preço combustível
    t = passo(f"Preenche preço ({PRECO} R$/L)...")
    preco_str = f"{PRECO:.2f}".replace(".", ",")
    try:
        campo = page.get_by_role("textbox", name="Preço")
        await campo.wait_for(state="visible", timeout=5000)
        await campo.click(click_count=3, force=True)
        await page.wait_for_timeout(200)
        await campo.type(preco_str, delay=80)
        await page.wait_for_timeout(300)
        ok(t, f"campo='{await campo.input_value()}'")
    except Exception as e:
        falhou(t, str(e))

    # ── ORIGEM ────────────────────────────────────────────────────────

    # [XX] JS clear origem
    t = passo("JS clear origem...")
    await page.evaluate("""
        () => {
            const inp = document.querySelector("input[placeholder='Origem']");
            if (!inp) return;
            const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
            setter.call(inp, '');
            inp.dispatchEvent(new Event('input', {bubbles: true}));
            inp.dispatchEvent(new Event('change', {bubbles: true}));
        }
    """)
    ok(t)

    # [XX] Clica container origem
    t = passo("Clica container origem...")
    try:
        container = page.locator(".q-field__control:has(input[placeholder='Origem'])").first
        await container.wait_for(state="visible", timeout=8000)
        await container.click()
        await page.wait_for_timeout(600)
        ok(t)
    except Exception as e:
        falhou(t, str(e))

    # [XX] Digita origem
    t = passo(f"Digita origem...")
    await page.keyboard.type(ORIGEM, delay=80)
    val = await campo_valor(page, "Origem")
    ok(t, f"campo='{val}'")

    # [XX] Dispara evento input Vue.js (necessário em headless)
    t = passo("Dispara evento input Vue.js (origem)...")
    await page.evaluate("""
        () => {
            const inp = document.querySelector("input[placeholder='Origem']");
            if (!inp) return;
            inp.dispatchEvent(new Event('input', {bubbles: true}));
            inp.dispatchEvent(new KeyboardEvent('keyup', {key: 's', bubbles: true}));
        }
    """)
    await page.wait_for_timeout(3000)  # mesmo timing do diagnostico_qualp.py
    ok(t)

    # [XX] Aguarda painel autocomplete origem
    t = passo("Aguarda painel autocomplete origem...")
    painel_apareceu = False
    try:
        painel = page.locator(".waypoints-location-drawer")
        await painel.wait_for(state="visible", timeout=15000)
        await page.wait_for_timeout(500)
        sugestoes = page.locator(".waypoints-location-drawer .q-scrollarea__content > div")
        count = await sugestoes.count()
        painel_apareceu = True
        ok(t, f"{count} sugestões")
    except PlaywrightTimeout:
        falhou(t, "painel não apareceu em 15s — pressionando Enter como fallback")
        await screenshot(page, "diag_sem_painel_origem")
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(800)

    # [XX] Seleciona sugestão origem
    if painel_apareceu:
        t = passo("Seleciona sugestão origem...")
        try:
            sugestoes = page.locator(".waypoints-location-drawer .q-scrollarea__content > div")
            count = await sugestoes.count()
            cidade_lower = ORIGEM.split(",")[0].strip().lower()
            alvo = 0
            for i in range(count):
                txt = (await sugestoes.nth(i).inner_text()).strip().lower()
                if txt.count(cidade_lower) >= 2:
                    alvo = i
                    break
            texto_alvo = (await sugestoes.nth(alvo).inner_text()).strip()
            await sugestoes.nth(alvo).click()
            await page.wait_for_timeout(800)
            ok(t, f"índice={alvo}  texto='{texto_alvo[:50]}'")
        except Exception as e:
            falhou(t, str(e))

    # [XX] CRÍTICO: verifica campo origem após seleção
    t = passo("✦ Verifica origem APÓS seleção (crítico)...")
    val_origem = await campo_valor(page, "Origem")
    ok(t, f"campo='{val_origem}'")
    await screenshot(page, "diag_apos_origem")
    if not val_origem.strip():
        print("        ⚠️  CAMPO VAZIO — autocomplete não committou o valor no Vue!")

    # ── DESTINO ───────────────────────────────────────────────────────

    # [XX] JS clear destino
    t = passo("JS clear destino...")
    await page.evaluate("""
        () => {
            const inp = document.querySelector("input[placeholder='Destino'], input[placeholder='Destino 1']");
            if (!inp) return;
            const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
            setter.call(inp, '');
            inp.dispatchEvent(new Event('input', {bubbles: true}));
            inp.dispatchEvent(new Event('change', {bubbles: true}));
        }
    """)
    ok(t)

    # [XX] Clica campo destino
    t = passo("Clica campo destino...")
    try:
        campo = page.locator("input[placeholder='Destino'], input[placeholder='Destino 1']").first
        await campo.wait_for(state="visible", timeout=8000)
        await campo.click(force=True)
        await page.wait_for_timeout(600)
        ok(t)
    except Exception as e:
        falhou(t, str(e))

    # [XX] Digita destino
    t = passo(f"Digita destino...")
    await page.keyboard.type(DESTINO, delay=80)
    val = await campo_valor(page, "Destino")
    ok(t, f"campo='{val}'")

    # [XX] Dispara evento input Vue.js (necessário em headless)
    t = passo("Dispara evento input Vue.js (destino)...")
    await page.evaluate("""
        () => {
            const inp = document.querySelector("input[placeholder='Destino'], input[placeholder='Destino 1']");
            if (!inp) return;
            inp.dispatchEvent(new Event('input', {bubbles: true}));
            inp.dispatchEvent(new KeyboardEvent('keyup', {key: 's', bubbles: true}));
        }
    """)
    await page.wait_for_timeout(3000)  # mesmo timing do diagnostico_qualp.py
    ok(t)

    # [XX] Aguarda painel autocomplete destino
    t = passo("Aguarda painel autocomplete destino...")
    painel_apareceu_dest = False
    try:
        painel = page.locator(".waypoints-location-drawer")
        await painel.wait_for(state="visible", timeout=15000)
        await page.wait_for_timeout(500)
        sugestoes = page.locator(".waypoints-location-drawer .q-scrollarea__content > div")
        count = await sugestoes.count()
        painel_apareceu_dest = True
        ok(t, f"{count} sugestões")
    except PlaywrightTimeout:
        falhou(t, "painel não apareceu em 15s — pressionando Enter como fallback")
        await screenshot(page, "diag_sem_painel_destino")
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(800)

    # [XX] Seleciona sugestão destino
    if painel_apareceu_dest:
        t = passo("Seleciona sugestão destino...")
        try:
            sugestoes = page.locator(".waypoints-location-drawer .q-scrollarea__content > div")
            count = await sugestoes.count()
            cidade_lower = DESTINO.split(",")[0].strip().lower()
            alvo = 0
            for i in range(count):
                txt = (await sugestoes.nth(i).inner_text()).strip().lower()
                if txt.count(cidade_lower) >= 2:
                    alvo = i
                    break
            texto_alvo = (await sugestoes.nth(alvo).inner_text()).strip()
            await sugestoes.nth(alvo).click()
            await page.wait_for_timeout(800)
            ok(t, f"índice={alvo}  texto='{texto_alvo[:50]}'")
        except Exception as e:
            falhou(t, str(e))

    # [XX] CRÍTICO: verifica campo destino após seleção
    t = passo("✦ Verifica destino APÓS seleção (crítico)...")
    val_destino = await campo_valor(page, "Destino")
    ok(t, f"campo='{val_destino}'")
    await screenshot(page, "diag_apos_destino")
    if not val_destino.strip():
        print("        ⚠️  CAMPO VAZIO — autocomplete não committou o valor no Vue!")

    # [XX] Loga campos antes de CALCULAR
    t = passo("✦ Campos antes de CALCULAR (crítico)...")
    orig_final = await campo_valor(page, "Origem")
    dest_final = await campo_valor(page, "Destino")
    ok(t, f"origem='{orig_final}'  destino='{dest_final}'")
    await screenshot(page, "diag_pre_calcular")

    if not orig_final.strip() or not dest_final.strip():
        print()
        print("  ❌ DIAGNÓSTICO: campos vazios antes de CALCULAR")
        print("     → O problema é que o clique na sugestão não commita o valor no Vue")
        print("     → Ver screenshots: /debug/screenshot/diag_apos_origem")
        print("                        /debug/screenshot/diag_apos_destino")
    else:
        print()
        print("  ✅ Campos preenchidos — CALCULAR deve funcionar")

    # [XX] Clica CALCULAR
    t = passo("Clica CALCULAR...")
    try:
        btn = page.locator("button:has-text('CALCULAR')").first
        await btn.wait_for(state="attached", timeout=10000)
        await btn.click(force=True)
        ok(t)
    except Exception as e:
        falhou(t, str(e))
        await screenshot(page, "diag_sem_calcular")

    # [XX] Aguarda resultado
    t = passo("Aguarda div.route-table (90s)...")
    try:
        await page.locator("div.route-table").first.wait_for(state="visible", timeout=90000)
        ok(t)
        await screenshot(page, "diag_resultado")
    except PlaywrightTimeout:
        falhou(t, "timeout — div.route-table não apareceu")
        await screenshot(page, "diag_timeout_resultado")
        print()
        print("  ❌ DIAGNÓSTICO: timeout aguardando resultado")
        print("     → Ver screenshot: /debug/screenshot/diag_timeout_resultado")
        await context.close()
        await browser.close()
        await pw.stop()
        return

    # [XX] Extrai resultado
    t = passo("Extrai resultado...")
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
        distancia   = await _label("Distância")
        pedagio     = await _label("Pedágio")
        total       = await _label("Custo Total")
        ok(t, f"dist={distancia}  pedágio={pedagio}  total={total}")
        print()
        print("  ✅ SUCESSO — QualP headless funcionou!")
        print(f"     Distância : {distancia}")
        print(f"     Pedágio   : {pedagio}")
        print(f"     Total     : {total}")
    except Exception as e:
        falhou(t, str(e))

    print()
    print("Screenshots salvos em outputs/ — acesse via /debug/screenshot/diag_*")
    await context.close()
    await browser.close()
    await pw.stop()


asyncio.run(main())
