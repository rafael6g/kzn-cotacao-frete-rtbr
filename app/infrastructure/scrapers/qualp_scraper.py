"""
Scraper para https://qualp.com.br

Estratégia:
- Login por email/senha no início de cada sessão (modal SPA)
- Popup de alerta "Atenção Embarcador e Transportador" é fechado automaticamente
- Campos origem/destino usam Quasar q-field com autocomplete próprio
- Resultado retorna 3 rotas — sempre extrai ROTA 1 (mais eficiente, selecionada por padrão)
- Tabela Frete ANTT com 12 tipos de carga extraída via tr.q-tr
- Veículo: ícones clicáveis (0=caminhão, 1=carro, 2=ônibus, 3=moto)
- Eixos: botões keyboard_arrow_up/down
- Combustível e preço: inputs tel dentro de painéis Quasar
"""

import asyncio
import time
import random
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeout,
)

from app.application.interfaces.site_scraper import SiteScraper
from app.domain.value_objects.parametros_rota import ParametrosRota
from app.domain.value_objects.resultado_rota import ResultadoRota
from app.domain.exceptions import (
    SiteIndisponivelError,
    ResultadoNaoEncontradoError,
    TimeoutConsultaError,
)
from app.core.config import get_settings
from app.core.logging_config import get_logger
from app.infrastructure.cache import distancia_cache

logger = get_logger(__name__)
settings = get_settings()

URL_BASE = "https://qualp.com.br/#/"

_TABELA_LABELS = {
    "A": "Tabela A - Lotação",
    "B": "Tabela B - Agregados",
    "C": "Tabela C - Lotação de alto desempenho",
    "D": "Tabela D - Agregados de alto desempenho",
}

_ESTADOS = {
    "AC": "Acre", "AL": "Alagoas", "AM": "Amazonas", "AP": "Amapá",
    "BA": "Bahia", "CE": "Ceará", "DF": "Distrito Federal",
    "ES": "Espírito Santo", "GO": "Goiás", "MA": "Maranhão",
    "MG": "Minas Gerais", "MS": "Mato Grosso do Sul", "MT": "Mato Grosso",
    "PA": "Pará", "PB": "Paraíba", "PE": "Pernambuco", "PI": "Piauí",
    "PR": "Paraná", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte",
    "RO": "Rondônia", "RR": "Roraima", "RS": "Rio Grande do Sul",
    "SC": "Santa Catarina", "SE": "Sergipe", "SP": "São Paulo",
    "TO": "Tocantins",
}

# ── Seletores do login ────────────────────────────────────────────────
SEL_INPUT_EMAIL  = "input[type='email']"
SEL_INPUT_SENHA  = "input[type='password']"

# ── Seletores do formulário ───────────────────────────────────────────
SEL_CONTAINER_ORIGEM  = ".q-field__control:has(input[placeholder='Origem'])"
SEL_INPUT_DESTINO     = "input[placeholder='Destino'], input[placeholder='Destino 1']"
SEL_SUGESTAO          = ".waypoints-location-drawer .q-scrollarea__content > div"
SEL_BTN_CALCULAR      = "button:has-text('CALCULAR')"

# ── Seletores do resultado ────────────────────────────────────────────
SEL_RESULT_TABLE  = "div.route-table"           # container da tabela de resultado
SEL_LABEL_ROW     = "div.flex.justify-between"  # cada linha label/valor
SEL_TAB_ATIVA     = "div.q-tab--active"         # aba ROTA selecionada
SEL_FRETE_ROW     = "tr.q-tr"                   # linhas da tabela ANTT


_VIEWPORTS = [
    {"width": 1366, "height": 768},
    {"width": 1440, "height": 900},
    {"width": 1536, "height": 864},
    {"width": 1280, "height": 800},
    {"width": 1920, "height": 1080},
]

def _j(base: int, pct: float = 0.25) -> int:
    """Retorna valor aleatório em torno de base ±pct — quebra padrão de bot."""
    delta = int(base * pct)
    return random.randint(base - delta, base + delta)


class QualPScraper(SiteScraper):

    def __init__(self, usuario: str, senha: str, headless: bool = True,
                 session_file: str = ".qualp_session.json"):
        self._usuario      = usuario
        self._senha        = senha
        self._headless     = headless
        self._session_file = Path(session_file)
        self._playwright   = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._form: dict = {}
        self._login_ts: float = 0.0  # timestamp do último login bem-sucedido

    # ── Ciclo de vida ─────────────────────────────────────────────────

    async def iniciar_sessao(self) -> None:
        logger.info("QualP: iniciando browser Playwright...")
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self._headless,
            slow_mo=50 if not self._headless else settings.playwright_slow_mo_ms,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        ctx_kwargs = dict(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport=random.choice(_VIEWPORTS),
            locale="pt-BR",
            permissions=[],
        )
        if self._session_file.exists():
            ctx_kwargs["storage_state"] = str(self._session_file)
            logger.info(f"QualP: carregando sessão salva de '{self._session_file}'")

        self._context = await self._browser.new_context(**ctx_kwargs)
        await self._context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3]});
            Object.defineProperty(navigator, 'languages', {get: () => ['pt-BR','pt','en']});
            window.chrome = {runtime: {}};
        """)
        self._page = await self._context.new_page()

        # Fecha automaticamente qualquer popup/nova aba que o site tentar abrir
        self._context.on("page", lambda popup: asyncio.ensure_future(popup.close()))
        # Descarta dialogs (alert/confirm/prompt) do browser
        self._page.on("dialog", lambda d: asyncio.ensure_future(d.dismiss()))

        # Em modo headless bloqueia imagens/fontes para poupar memória/banda
        if self._headless:
            await self._context.route(
                "**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf}",
                lambda route: route.abort(),
            )
        await self._context.route("**/googletagmanager.com/**", lambda r: r.abort())
        await self._context.route("**/google-analytics.com/**", lambda r: r.abort())

        try:
            await self._page.goto(URL_BASE, timeout=settings.playwright_timeout_ms, wait_until="networkidle")
        except Exception as e:
            raise SiteIndisponivelError(f"Não foi possível acessar QualP: {e}")

        await self._fechar_popup_alerta()

        # Verifica se sessão salva ainda é válida — botão "Logar" visível = não logado
        sessao_expirada = await self._page.locator("text=Logar").first.is_visible(timeout=3000)
        if sessao_expirada:
            if self._session_file.exists():
                logger.info("QualP: sessão expirada, fazendo login novamente...")
                self._session_file.unlink()
            await self._fazer_login()
            await self._salvar_sessao()
        elif not self._session_file.exists():
            await self._salvar_sessao()

        logger.info("QualP: sessão iniciada com sucesso.")

    async def encerrar_sessao(self) -> None:
        logger.info("QualP: encerrando sessão Playwright...")
        try:
            if self._page:    await self._page.close()
            if self._context: await self._context.close()
            if self._browser: await self._browser.close()
            if self._playwright: await self._playwright.stop()
        except Exception as e:
            logger.warning(f"QualP: erro ao encerrar sessão: {e}")
        finally:
            self._page = self._context = self._browser = self._playwright = None
            self._form = {}

    async def _salvar_sessao(self) -> None:
        try:
            await self._context.storage_state(path=str(self._session_file))
            logger.info(f"QualP: sessão salva em '{self._session_file}'")
        except Exception as e:
            logger.warning(f"QualP: não foi possível salvar sessão: {e}")

    async def esta_ativo(self) -> bool:
        if not self._page:
            return False
        # Pula verificação por 60s após login para evitar falso negativo durante transição
        if time.time() - self._login_ts < 60:
            return True
        try:
            await self._page.evaluate("1 + 1")
            botao_logar = self._page.locator("text=Logar").first
            if await botao_logar.is_visible(timeout=2000):
                return False
            return True
        except Exception:
            return False

    # ── Consulta principal ────────────────────────────────────────────

    async def consultar(self, params: ParametrosRota, delay_segundos: int = 0) -> ResultadoRota:
        if not self._page:
            raise SiteIndisponivelError("Sessão não iniciada.")

        # Verifica se ainda está logado antes de cada consulta
        logado = await self.esta_ativo()
        if not logado:
            logger.info("QualP: sessão expirada antes da consulta — refazendo login...")
            await self._fazer_login()
            await self._salvar_sessao()

        logger.info(f"QualP: consultando {params.origem} → {params.destino} | v={params.veiculo_label} eixos={params.eixos}")

        try:
            self._form["_tabela_frete_pendente"] = params.tabela_frete
            await self._limpar_formulario()
            await self._selecionar_veiculo(params.veiculo)
            await self._ajustar_eixos(params.eixos)
            await self._preencher_combustivel(params.preco_combustivel, params.consumo_km_l)
            await self._preencher_origem(params.origem)
            await self._preencher_destino(params.destino)
            await self._submeter(delay_segundos)
            resultado = await self._extrair_resultado()
            distancia_cache.salvar(
                params.origem, params.destino,
                resultado.distancia_km,
                pedagio=resultado.valor_pedagio,
                pedagios=resultado.pedagios,
            )
            return resultado

        except PlaywrightTimeout as e:
            raise TimeoutConsultaError(f"QualP timeout: {e}")
        except (SiteIndisponivelError, ResultadoNaoEncontradoError):
            raise
        except Exception as e:
            logger.exception(f"QualP erro inesperado: {e}")
            raise ResultadoNaoEncontradoError(f"Erro inesperado: {e}")

    # ── Login e popup ─────────────────────────────────────────────────

    async def _fechar_popup_alerta(self) -> None:
        """Fecha popup 'Atenção Embarcador e Transportador' se aparecer."""
        try:
            titulo = self._page.locator("text=Embarcador e Transportador").first
            if await titulo.is_visible(timeout=4000):
                btn = self._page.locator("button:near(:text('Embarcador'))").first
                await btn.click()
                await self._page.wait_for_timeout(_j(800))
                logger.debug("QualP: popup de alerta fechado.")
        except Exception:
            pass

    async def _fazer_login(self) -> None:
        """Abre modal de login, preenche credenciais e aguarda redirecionamento."""
        # Abre modal de login pelo botão do header
        try:
            btn = self._page.locator("text=Logar").first
            if await btn.is_visible(timeout=5000):
                await btn.click()
                await self._page.wait_for_timeout(_j(1500))
        except PlaywrightTimeout:
            pass

        # Preenche e-mail
        try:
            campo_email = self._page.locator(SEL_INPUT_EMAIL).first
            await campo_email.wait_for(state="visible", timeout=10000)
            await campo_email.click()
            await self._page.wait_for_timeout(_j(500))
            await campo_email.type(self._usuario, delay=_j(90))
        except PlaywrightTimeout:
            raise SiteIndisponivelError("QualP: campo de e-mail não encontrado no modal de login.")

        # Preenche senha
        campo_senha = self._page.locator(SEL_INPUT_SENHA).first
        await campo_senha.click()
        await self._page.wait_for_timeout(_j(600))
        await campo_senha.type(self._senha, delay=_j(90))

        # Clica LOGAR (percorre botões visíveis para encontrar o correto)
        buttons = self._page.locator("button")
        count = await buttons.count()
        clicado = False
        for i in range(count):
            btn = buttons.nth(i)
            txt = (await btn.inner_text()).strip()
            if txt == "LOGAR" and await btn.is_visible():
                await btn.click()
                clicado = True
                break
        if not clicado:
            raise SiteIndisponivelError("QualP: botão LOGAR não encontrado.")

        # Aguarda URL mudar (modal fechar = login OK)
        try:
            await self._page.wait_for_function(
                "() => !window.location.hash.includes('ds=login')",
                timeout=15000,
            )
            logger.info("QualP: login realizado com sucesso.")
            self._login_ts = time.time()
        except PlaywrightTimeout:
            raise SiteIndisponivelError("QualP: timeout aguardando login — credenciais inválidas ou bloqueio.")

    # ── Formulário ────────────────────────────────────────────────────

    async def _limpar_formulario(self) -> None:
        pass  # estado gerenciado por _form; cada campo limpa a si mesmo se necessário

    async def _selecionar_veiculo(self, veiculo_id: int) -> None:
        if self._form.get("veiculo") == veiculo_id:
            logger.debug(f"QualP: veículo {veiculo_id} já selecionado, pulando")
            return
        indice = {2: 0, 1: 1, 3: 2, 4: 3}.get(veiculo_id, 0)
        try:
            icones = self._page.locator(".vehicle-icons img, .vehicle-type img, [class*='vehicle'] img")
            count = await icones.count()
            if count > indice:
                await icones.nth(indice).click()
                await self._page.wait_for_timeout(_j(300))
            else:
                # Fallback: JS click no nth ícone de veículo
                await self._page.evaluate(f"""
                    () => {{
                        const imgs = document.querySelectorAll('[class*="vehicle"] img, [class*="veiculo"] img');
                        if (imgs[{indice}]) imgs[{indice}].click();
                    }}
                """)
            self._form["veiculo"] = veiculo_id
        except Exception as e:
            logger.warning(f"QualP: não foi possível selecionar veículo {veiculo_id}: {e}")

    async def _selecionar_tabela_frete(self, tabela: str) -> None:
        """Seleciona Tabela A/B/C/D no dropdown de frete ANTT do resultado QualP."""
        tabela = tabela.upper()
        if self._form.get("tabela_frete") == tabela:
            return
        label = _TABELA_LABELS.get(tabela, _TABELA_LABELS["A"])
        try:
            # Clica no q-field__control do primeiro .freight-table (Tabela A/B/C/D)
            # — NÃO em #freight-select (div interno sem evento de abertura)
            await self._page.locator("label.freight-table").first.locator(".q-field__control").click()
            await self._page.wait_for_timeout(_j(400))
            await self._page.locator(f".q-menu .q-item:has-text('{label}')").first.click()
            await self._page.wait_for_timeout(_j(400))
            self._form["tabela_frete"] = tabela
            logger.debug(f"QualP: tabela frete '{label}' selecionada")
        except Exception as e:
            logger.warning(f"QualP: não foi possível selecionar tabela '{tabela}': {e}")

    async def _ler_eixos_atual(self) -> Optional[int]:
        """Lê o número de eixos atual direto do DOM (ex: input.value = '6 eixos')."""
        return await self._page.evaluate(r"""
            () => {
                for (const inp of document.querySelectorAll('input')) {
                    const m = inp.value.match(/^(\d+)\s*eixos?$/i);
                    if (m) return parseInt(m[1]);
                }
                return null;
            }
        """)

    async def _ajustar_eixos(self, eixos_desejados: int) -> None:
        """
        Estrutura real do campo (inspecionada via F12):
          q-field__control
            q-field__prepend > i.cursor-pointer > SVG  ← DIMINUIR (seta p/ baixo)
            q-field__control-container > input[value="N eixos"]
            q-field__append  > i.cursor-pointer > SVG  ← AUMENTAR (seta p/ cima)
        """
        try:
            atual = await self._ler_eixos_atual()
            if atual is None:
                logger.warning("QualP: campo eixos não encontrado na página")
                return

            diferenca = eixos_desejados - atual
            logger.debug(f"QualP: eixos atual={atual} desejado={eixos_desejados} diff={diferenca}")

            if diferenca == 0:
                return

            # input.value é propriedade DOM Vue, não atributo HTML — CSS [value*=] não funciona.
            # Usa JS para localizar o input pelo valor, sobe até .q-field__control e clica no ícone.
            aumentar = diferenca > 0
            for _ in range(abs(diferenca)):
                await self._page.evaluate("""
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
                await self._page.wait_for_timeout(_j(150))

            resultado = await self._ler_eixos_atual()
            logger.debug(f"QualP: eixos após ajuste → {resultado}")

        except Exception as e:
            logger.warning(f"QualP: não foi possível ajustar eixos para {eixos_desejados}: {e}")

    async def _preencher_combustivel(self, preco: float, consumo: float) -> None:
        if self._form.get("preco") == preco and self._form.get("consumo") == consumo:
            logger.debug(f"QualP: combustível preço={preco} consumo={consumo} já preenchido, pulando")
            return
        """
        Preenche consumo e preço pelo accessibility name dos campos Quasar.
        Fallback para input[type='tel'] nth(0/1) se os nomes mudarem.
        """
        consumo_str = f"{consumo:.1f}".replace(".", ",")
        preco_str   = f"{preco:.2f}".replace(".", ",")

        async def _preencher_campo(locator, valor: str, nome: str) -> bool:
            try:
                await locator.wait_for(state="visible", timeout=5000)
                # 3 cliques seguidos selecionam todo o conteúdo existente
                await locator.click(click_count=3, force=True)
                await self._page.wait_for_timeout(_j(200))
                await locator.type(valor, delay=_j(80))
                await self._page.wait_for_timeout(_j(300))
                # Verifica o que foi preenchido de fato
                preenchido = await locator.input_value()
                logger.debug(f"QualP: {nome}={valor!r} → campo={preenchido!r}")
                return True
            except Exception as e:
                logger.warning(f"QualP: erro ao preencher {nome}: {e}")
                return False

        # Tenta pelo accessibility name (mais robusto)
        ok_consumo = await _preencher_campo(
            self._page.get_by_role("textbox", name="Consumo KM/L"),
            consumo_str, "consumo",
        )
        ok_preco = await _preencher_campo(
            self._page.get_by_role("textbox", name="Preço"),
            preco_str, "preço",
        )

        # Fallback: input[type='tel'] por posição
        if not ok_consumo or not ok_preco:
            logger.warning("QualP: fallback para input[type='tel']")
            inputs_tel = self._page.locator("input[type='tel']")
            count = await inputs_tel.count()
            if count >= 1 and not ok_consumo:
                await _preencher_campo(inputs_tel.nth(0), consumo_str, "consumo(fallback)")
            if count >= 2 and not ok_preco:
                await _preencher_campo(inputs_tel.nth(1), preco_str, "preço(fallback)")
        self._form["preco"] = preco
        self._form["consumo"] = consumo

    @staticmethod
    def _formatar_endereco(endereco: str) -> str:
        """
        Converte "Londrina, PR" → "Londrina, Paraná, Brasil"
        para compatibilidade com o autocomplete do QualP.
        Entradas já com 3 partes (ex: "Londrina, Paraná, Brasil") são retornadas sem alteração.
        """
        partes = [p.strip() for p in endereco.split(",")]
        if len(partes) == 2:
            cidade, uf = partes[0], partes[1].upper()
            estado = _ESTADOS.get(uf, uf)
            return f"{cidade.title()}, {estado}, Brasil"
        # Normaliza casing: "TRES LAGOAS, MS, BRASIL" → "Tres Lagoas, Ms, Brasil"
        # Necessário pois planilhas geralmente vêm em MAIÚSCULAS e o autocomplete do QualP
        # não retorna sugestões para entradas em ALL CAPS.
        return ", ".join(p.strip().title() for p in partes)

    async def _preencher_origem(self, endereco: str) -> None:
        """Clica no container Quasar da origem, digita e seleciona primeira sugestão."""
        if self._form.get("origem") == endereco:
            logger.debug(f"QualP: origem '{endereco}' já preenchida, pulando")
            return
        termo = self._formatar_endereco(endereco)
        try:
            container = self._page.locator(SEL_CONTAINER_ORIGEM).first
            await container.wait_for(state="visible", timeout=8000)
            await self._page.evaluate("""
                () => {
                    const inp = document.querySelector("input[placeholder='Origem']");
                    if (!inp) return;
                    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                    setter.call(inp, '');
                    inp.dispatchEvent(new Event('input', {bubbles: true}));
                    inp.dispatchEvent(new Event('change', {bubbles: true}));
                }
            """)
            await self._page.wait_for_timeout(_j(200))
            await container.click()
            await self._page.wait_for_timeout(_j(200))
            await self._page.keyboard.type(termo, delay=_j(50))
            # Força evento input no Vue.js — headless não dispara reatividade via keyboard.type
            await self._page.evaluate("""
                () => {
                    const inp = document.querySelector("input[placeholder='Origem']");
                    if (!inp) return;
                    inp.dispatchEvent(new Event('input', {bubbles: true}));
                    inp.dispatchEvent(new KeyboardEvent('keyup', {key: 's', bubbles: true}));
                }
            """)
            await self._page.wait_for_timeout(_j(2000))
            cidade = termo.split(",")[0].strip()
            await self._selecionar_primeira_sugestao("origem", cidade)
            self._form["origem"] = endereco
        except Exception as e:
            raise ResultadoNaoEncontradoError(f"QualP: erro ao preencher origem '{endereco}': {e}")

    async def _preencher_destino(self, endereco: str) -> None:
        """Clica no input de destino, limpa valor anterior se houver, digita e seleciona sugestão."""
        if self._form.get("destino") == endereco:
            logger.debug(f"QualP: destino '{endereco}' já preenchida, pulando")
            return
        termo = self._formatar_endereco(endereco)
        try:
            campo = self._page.locator(SEL_INPUT_DESTINO).first
            await campo.wait_for(state="visible", timeout=8000)
            # Limpa via JS setter (Quasar — input_value() retorna vazio mesmo com texto visível)
            await self._page.evaluate("""
                () => {
                    const inp = document.querySelector("input[placeholder='Destino'], input[placeholder='Destino 1']");
                    if (!inp) return;
                    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                    setter.call(inp, '');
                    inp.dispatchEvent(new Event('input', {bubbles: true}));
                    inp.dispatchEvent(new Event('change', {bubbles: true}));
                }
            """)
            await self._page.wait_for_timeout(_j(200))
            await campo.click(force=True)
            await self._page.wait_for_timeout(_j(200))
            await self._page.keyboard.type(termo, delay=_j(50))
            # Força evento input no Vue.js — headless não dispara reatividade via keyboard.type
            await self._page.evaluate("""
                () => {
                    const inp = document.querySelector("input[placeholder='Destino'], input[placeholder='Destino 1']");
                    if (!inp) return;
                    inp.dispatchEvent(new Event('input', {bubbles: true}));
                    inp.dispatchEvent(new KeyboardEvent('keyup', {key: 's', bubbles: true}));
                }
            """)
            await self._page.wait_for_timeout(_j(2000))
            cidade = termo.split(",")[0].strip()
            await self._selecionar_primeira_sugestao("destino", cidade)
            self._form["destino"] = endereco
        except Exception as e:
            raise ResultadoNaoEncontradoError(f"QualP: erro ao preencher destino '{endereco}': {e}")

    async def _selecionar_primeira_sugestao(self, campo: str, cidade: str = "") -> None:
        """
        Clica na melhor sugestão do painel waypoints-location-drawer.
        Prioridade:
          1. Sugestão onde o texto da cidade aparece duas vezes (ex: "Londrina - Londrina / Paraná")
          2. Opção "BUSCA LITERAL" (pesquisa exata pelo texto digitado)
          3. Primeira sugestão disponível
        """
        try:
            # Aguarda o painel aparecer — Docker/VPS pode demorar mais que local
            painel = self._page.locator(".waypoints-location-drawer")
            await painel.wait_for(state="visible", timeout=15000)
            await self._page.wait_for_timeout(_j(500))

            sugestoes = self._page.locator(SEL_SUGESTAO)
            count = await sugestoes.count()
            if count == 0:
                raise PlaywrightTimeout("sem sugestões")

            cidade_lower = cidade.lower()
            idx_literal  = -1
            idx_cidade   = -1

            for i in range(count):
                texto = (await sugestoes.nth(i).inner_text()).strip().lower()
                # Opção "BUSCA LITERAL"
                if "busca literal" in texto and idx_literal == -1:
                    idx_literal = i
                # Cidade aparece duas vezes (padrão "Londrina - Londrina / Paraná")
                if cidade_lower and texto.count(cidade_lower) >= 2 and idx_cidade == -1:
                    idx_cidade = i

            alvo = idx_cidade if idx_cidade != -1 else (idx_literal if idx_literal != -1 else 0)
            logger.debug(f"QualP: {campo} — {count} sugestões, escolhendo índice {alvo}")
            await sugestoes.nth(alvo).click()
            await self._page.wait_for_timeout(_j(800))

        except PlaywrightTimeout:
            logger.warning(f"QualP: nenhuma sugestão para '{campo}' — pressionando Enter")
            await self._page.keyboard.press("Enter")
            await self._page.wait_for_timeout(_j(800))

    async def _submeter(self, delay_segundos: int) -> None:
        """Clica no botão CALCULAR e aguarda o resultado aparecer."""
        # Screenshot ANTES de clicar — mostra se origem/destino foram preenchidos
        try:
            campos = await self._page.evaluate("""
                () => {
                    const o = document.querySelector("input[placeholder='Origem']");
                    const d = document.querySelector("input[placeholder='Destino'], input[placeholder='Destino 1']");
                    return {
                        origem: o ? o.value : '?',
                        destino: d ? d.value : '?'
                    };
                }
            """)
            logger.info(f"QualP: campos antes de CALCULAR → origem={campos['origem']!r}  destino={campos['destino']!r}")
            await self._page.screenshot(path="outputs/debug_pre_calcular.png", full_page=False)
        except Exception:
            pass

        try:
            btn = self._page.locator(SEL_BTN_CALCULAR).first
            await btn.wait_for(state="attached", timeout=10000)
            await btn.click(force=True)
            logger.debug("QualP: CALCULAR clicado, aguardando resultado...")
        except PlaywrightTimeout:
            url_atual = self._page.url
            # Salva screenshot para diagnóstico
            try:
                await self._page.screenshot(path="outputs/debug_calcular.png", full_page=False)
                logger.error(f"QualP: CALCULAR não encontrado. URL={url_atual} — screenshot salvo em outputs/debug_calcular.png")
            except Exception:
                logger.error(f"QualP: CALCULAR não encontrado. URL={url_atual}")
            raise SiteIndisponivelError("QualP: botão CALCULAR não encontrado.")

        # Captura fingerprint do resultado anterior (distância) para detectar quando
        # o novo resultado carregar — evita extrair dado stale se a tabela já estava visível.
        fingerprint_anterior = ""
        try:
            tabela_atual = self._page.locator(SEL_RESULT_TABLE).first
            if await tabela_atual.is_visible(timeout=500):
                fingerprint_anterior = await tabela_atual.inner_text(timeout=1000)
        except Exception:
            pass

        # Aguarda o container da tabela de resultado aparecer (ou mudar de conteúdo)
        timeout_ms = settings.playwright_resultado_timeout_ms
        try:
            await self._page.locator(SEL_RESULT_TABLE).first.wait_for(
                state="visible", timeout=timeout_ms
            )
        except PlaywrightTimeout:
            try:
                await self._page.screenshot(path="outputs/debug_resultado.png", full_page=False)
                logger.error("QualP: timeout resultado — screenshot salvo em outputs/debug_resultado.png")
            except Exception:
                pass
            raise TimeoutConsultaError("QualP: timeout aguardando resultado da rota.")

        # Se havia resultado anterior, aguarda o conteúdo mudar (novo cálculo concluído).
        # Evita ler dado stale quando wait_for(visible) retorna imediatamente.
        if fingerprint_anterior:
            import time as _time
            deadline = _time.monotonic() + timeout_ms / 1000
            while _time.monotonic() < deadline:
                try:
                    texto_atual = await self._page.locator(SEL_RESULT_TABLE).first.inner_text(timeout=1000)
                    if texto_atual != fingerprint_anterior:
                        break
                except Exception:
                    break
                await self._page.wait_for_timeout(300)
            else:
                raise TimeoutConsultaError(
                    f"QualP: resultado não mudou após {timeout_ms // 1000}s — possível dado stale."
                )

        if delay_segundos > 0:
            await self._page.wait_for_timeout(delay_segundos * 1000)

    # ── Extração do resultado ─────────────────────────────────────────

    async def _extrair_resultado(self) -> ResultadoRota:
        """
        Extrai os campos da ROTA 1 (aba ativa por padrão).
        Seletores confirmados via DevTools:
          - Container: div.route-table
          - Linhas:    div.flex.justify-between (label à esq, valor à dir)
          - Aba ativa: div.q-tab--active
          - ANTT:      tr.q-tr > td (filtra por "R$" no valor para excluir cabeçalhos)
        """
        page = self._page

        # Escopa buscas no container da rota ativa
        tabela = page.locator(SEL_RESULT_TABLE).first

        async def _label(label: str) -> str:
            try:
                row = tabela.locator(f"{SEL_LABEL_ROW}:has-text('{label}')").first
                # Pega o último elemento filho de texto — funciona para span ou div
                filhos = row.locator("> *")
                cnt = await filhos.count()
                if cnt > 0:
                    return (await filhos.last.inner_text(timeout=2000)).strip()
            except Exception:
                pass
            return ""

        duracao     = await _label("Duração")
        distancia   = await _label("Distância")
        pedagio     = await _label("Pedágio")
        combustivel = await _label("Combustível")
        custo_total = await _label("Custo Total")

        # Descrição: aba ativa contém "ROTA N KM R$..." (accessibility name confirmado)
        try:
            aba = page.locator(SEL_TAB_ATIVA).first
            rota_desc = (await aba.inner_text(timeout=3000)).strip().replace("\n", " ")
        except Exception:
            rota_desc = f"ROTA 1 — {distancia}"

        # Seleciona a tabela ANTT correta (A/B/C/D) antes de extrair
        await self._selecionar_tabela_frete(self._form.pop("_tabela_frete_pendente", "A"))

        # Tabela ANTT: tr.q-tr sem cursor-pointer, com valor contendo "R$"
        fretes: dict[str, str] = {}
        try:
            linhas = await page.query_selector_all(SEL_FRETE_ROW)
            for linha in linhas:
                cls = await linha.get_attribute("class") or ""
                if "cursor-pointer" in cls:
                    continue  # praças de pedágio
                cells = await linha.query_selector_all("td")
                if len(cells) >= 2:
                    nome  = (await cells[0].inner_text()).strip()
                    valor = (await cells[-1].inner_text()).strip()
                    # Aceita apenas linhas com valor monetário real
                    if nome and "R$" in valor and nome not in ("Carga",):
                        fretes[nome] = valor
        except Exception as e:
            logger.warning(f"QualP: erro ao extrair tabela frete: {e}")

        # Praças de pedágio: tr.q-tr.cursor-pointer dentro de div.card-tolls
        pedagios: list[dict] = []
        try:
            toll_rows = await page.query_selector_all("div.card-tolls tr.q-tr.cursor-pointer")
            for row in toll_rows:
                cells = await row.query_selector_all("td.q-td")
                if len(cells) >= 2:
                    col0 = (await cells[0].inner_text()).strip().splitlines()
                    col1 = (await cells[1].inner_text()).strip().splitlines()
                    col0 = [p.strip() for p in col0 if p.strip()]
                    col1 = [p.strip() for p in col1 if p.strip()]
                    nome     = col0[0] if col0 else ""
                    rodovia  = col0[1] if len(col0) > 1 else ""
                    tarifa   = col1[0].replace("\xa0", "") if col1 else ""
                    por_eixo = col1[1].strip("() ") if len(col1) > 1 else ""
                    if nome and tarifa:
                        pedagios.append({"nome": nome, "rodovia": rodovia, "tarifa": tarifa, "por_eixo": por_eixo})
        except Exception as e:
            logger.warning(f"QualP: erro ao extrair praças de pedágio: {e}")

        if not distancia and not pedagio:
            raise ResultadoNaoEncontradoError("QualP: nenhum dado extraído do resultado.")

        logger.info(
            f"QualP: extraído — distância={distancia} pedágio={pedagio} "
            f"combustível={combustivel} total={custo_total} fretes={len(fretes)} praças={len(pedagios)}"
        )

        return ResultadoRota(
            tempo_viagem=duracao,
            distancia_km=distancia,
            rota_descricao=rota_desc,
            valor_pedagio=pedagio,
            valor_combustivel=combustivel,
            valor_total=custo_total,
            fretes=fretes,
            pedagios=pedagios,
            consultado_em=datetime.now(timezone.utc).isoformat(),
        )
