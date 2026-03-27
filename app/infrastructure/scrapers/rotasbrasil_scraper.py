"""
Scraper para https://rotasbrasil.com.br

Estratégia:
- Browser Chromium abre UMA VEZ por lote (sessão persistente)
- Cada consulta preenche o formulário, aguarda o resultado e extrai os dados
- Autocomplete dos endereços é tratado com espera por sugestões + seleção
- Tipo de carga sempre "todas" → extrai os 12 tipos de uma vez via #tabelaDeFrete0
- reCAPTCHA v3 (invisível) — sem login pode aparecer após várias consultas;
  o scraper detecta e lança CaptchaDetectadoError para que o use case registre o erro
- O delay entre consultas é controlado pelo use case, NÃO aqui
"""

import re
from datetime import datetime, timezone
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
    CaptchaDetectadoError,
    TimeoutConsultaError,
)
from app.core.config import get_settings
from app.core.logging_config import get_logger

logger = get_logger(__name__)
settings = get_settings()


async def _digitar_endereco(page, seletor: str, texto: str) -> None:
    """
    Digita endereço caractere a caractere com delay mínimo (15ms) para acionar
    o autocomplete jQuery UI — o site depende dos eventos keydown/keypress.
    Mais rápido que antes (era 50ms) mas confiável para disparar o dropdown.
    """
    await page.fill(seletor, "")
    await page.type(seletor, texto, delay=15)


URL_BASE = "https://rotasbrasil.com.br"

# ── Seletores do formulário ──────────────────────────────────────────
SEL_INPUT_ORIGEM      = "#txtEnderecoPartida"
SEL_INPUT_DESTINO     = "#txtEnderecoChegada"
SEL_BTN_BUSCAR        = "#btnSubmit"
SEL_INPUT_COMBUSTIVEL = "#precoCombustivel"
SEL_INPUT_CONSUMO     = "#consumo"
SEL_SELECT_CARGA      = "#selectCarga"
SEL_BTN_MOSTRAR_EIXO  = "#divMostrarEixo"
SEL_PAINEL_RESULTADO  = "#painelResults"
SEL_CAPTCHA_V2        = "#recaptchaV2"

# ── Seletores dos campos do resultado ────────────────────────────────
SEL_RESULTADO_ATIVO = "div.routeResult.active"
SEL_TEMPO           = "div.color-primary-500"
SEL_DISTANCIA       = "div.distance"
SEL_TITULO          = ".titulo"
SEL_QTD_PEDAGIO     = "#countPedagiosRota0"
SEL_VL_PEDAGIO      = "span.vlPedagio"
SEL_VL_COMBUSTIVEL  = "span.vlCombustivel"
SEL_VL_TOTAL        = "div.results b"


class RotasBrasilScraper(SiteScraper):

    def __init__(self, headless: bool = True):
        self._headless = headless
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    # ── Ciclo de vida ─────────────────────────────────────────────────

    async def iniciar_sessao(self) -> None:
        logger.info("Iniciando browser Playwright (Chromium)...")
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
        self._context = await self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="pt-BR",
        )
        self._page = await self._context.new_page()

        # Bloqueia recursos desnecessários para poupar memória na VPS
        await self._context.route(
            "**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf}",
            lambda route: route.abort(),
        )
        await self._context.route(
            "**/googletagmanager.com/**",
            lambda route: route.abort(),
        )
        await self._context.route(
            "**/google-analytics.com/**",
            lambda route: route.abort(),
        )

        try:
            await self._page.goto(URL_BASE, timeout=settings.playwright_timeout_ms, wait_until="networkidle")
            logger.info("Página inicial carregada.")
        except Exception as e:
            raise SiteIndisponivelError(f"Não foi possível acessar {URL_BASE}: {e}")

    async def encerrar_sessao(self) -> None:
        logger.info("Encerrando sessão Playwright...")
        try:
            if self._page:
                await self._page.close()
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception as e:
            logger.warning(f"Erro ao encerrar sessão: {e}")
        finally:
            self._page = None
            self._context = None
            self._browser = None
            self._playwright = None

    async def esta_ativo(self) -> bool:
        if not self._page:
            return False
        try:
            await self._page.evaluate("1 + 1")
            return True
        except Exception:
            return False

    # ── Consulta principal ────────────────────────────────────────────

    async def consultar(self, params: ParametrosRota, delay_segundos: int = 0) -> ResultadoRota:
        if not self._page:
            raise SiteIndisponivelError("Sessão não iniciada. Chame iniciar_sessao() primeiro.")

        logger.info(f"Consultando: {params.origem} → {params.destino} | veículo={params.veiculo_label} eixos={params.eixos}")

        try:
            await self._limpar_formulario()
            await self._selecionar_veiculo(params.veiculo)
            await self._selecionar_eixos(params.eixos)
            await self._preencher_endereco(SEL_INPUT_ORIGEM, params.origem)
            await self._preencher_endereco(SEL_INPUT_DESTINO, params.destino)
            await self._preencher_combustivel(params.preco_combustivel, params.consumo_km_l)
            await self._page.select_option(SEL_SELECT_CARGA, "todas")
            await self._submeter_formulario(delay_segundos=delay_segundos)
            resultado = await self._extrair_resultado()
            return resultado

        except CaptchaDetectadoError:
            raise
        except PlaywrightTimeout as e:
            raise TimeoutConsultaError(f"Timeout aguardando resultado: {e}")
        except (SiteIndisponivelError, ResultadoNaoEncontradoError):
            raise
        except Exception as e:
            logger.exception(f"Erro inesperado na consulta: {e}")
            raise ResultadoNaoEncontradoError(f"Erro inesperado: {e}")

    # ── Etapas do formulário ──────────────────────────────────────────

    async def _limpar_formulario(self) -> None:
        """Limpa os campos de origem e destino para nova consulta."""
        for sel in [SEL_INPUT_ORIGEM, SEL_INPUT_DESTINO]:
            await self._page.fill(sel, "")

    async def _selecionar_veiculo(self, veiculo_id: int) -> None:
        classes = {1: "carro", 2: "caminhao", 3: "onibus", 4: "moto"}
        classe = classes.get(veiculo_id, "caminhao")
        sel = f"div.icon-veiculo.{classe}"
        try:
            await self._page.click(sel, timeout=3000)
            logger.debug(f"Veículo '{classe}' selecionado via clique.")
        except Exception:
            await self._page.evaluate(
                f"document.getElementById('veiculo').value = '{veiculo_id}'"
            )
            logger.debug(f"Veículo {veiculo_id} setado via JS (fallback).")

    async def _preencher_endereco(self, seletor: str, endereco: str) -> None:
        """
        Preenche o endereço e seleciona a primeira sugestão do autocomplete jQuery UI.
        Usa fill() para preencher instantaneamente, depois aguarda o dropdown aparecer.
        """
        await _digitar_endereco(self._page, seletor, endereco)

        try:
            loc = self._page.locator(".ui-autocomplete .ui-menu-item").first
            await loc.wait_for(state="visible", timeout=5000)
            sugestao = (await loc.inner_text()).strip()
            await loc.click()
            logger.debug(f"Autocomplete: clicou em '{sugestao[:50]}' para: {endereco}")
            await self._page.locator(".ui-autocomplete").wait_for(state="hidden", timeout=2000)
        except Exception:
            await self._page.press(seletor, "Tab")
            logger.debug(f"Sem autocomplete — Tab pressionado para: {endereco}")

    async def _preencher_combustivel(self, preco: float, consumo: float) -> None:
        preco_str = f"{preco:.2f}".replace(".", ",")
        consumo_str = f"{consumo:.2f}".replace(".", ",")

        await self._page.fill(SEL_INPUT_COMBUSTIVEL, preco_str)
        await self._page.fill(SEL_INPUT_CONSUMO, consumo_str)

        logger.debug(f"Combustível: R$ {preco_str}/L | Consumo: {consumo_str} km/L")

    async def _selecionar_eixos(self, eixos: int) -> None:
        try:
            await self._page.wait_for_selector(SEL_BTN_MOSTRAR_EIXO, timeout=3000, state="visible")
            await self._page.click(SEL_BTN_MOSTRAR_EIXO)

            sel_eixo = f"div.eixoDiv[eixoid='{eixos}']"
            await self._page.wait_for_selector(sel_eixo, timeout=3000, state="visible")
            await self._page.click(sel_eixo)
            logger.debug(f"Eixo {eixos} selecionado via painel visual.")
        except Exception as e:
            logger.debug(f"Painel de eixos não disponível ({e}) — setando via JS.")
            await self._page.evaluate(
                f"""
                var el = document.getElementById('eixo');
                if (el) {{
                    el.value = '{eixos}';
                    el.dispatchEvent(new Event('change', {{bubbles: true}}));
                }}
                """
            )

    async def _submeter_formulario(self, delay_segundos: int = 0) -> None:
        """
        Clica em BUSCAR via JavaScript e aguarda o novo resultado aparecer.
        Garante que o resultado da consulta ANTERIOR saia do DOM antes de validar
        o novo — resolve o bug de múltiplas rotas com div.routeResult.active persistente.
        """
        # Verifica reCAPTCHA v2 antes de submeter
        try:
            captcha_display = await self._page.evaluate(
                "document.getElementById('recaptchaV2')?.style?.display"
            )
            if captcha_display and captcha_display != "none":
                raise CaptchaDetectadoError(
                    "reCAPTCHA v2 detectado. Considere criar uma conta no rotasbrasil.com.br."
                )
        except CaptchaDetectadoError:
            raise
        except Exception:
            pass

        # Registra se já existe resultado ativo (de consulta anterior)
        tem_resultado_anterior = await self._page.query_selector(SEL_RESULTADO_ATIVO) is not None

        # IMPORTANTE: clique via JS — clique direto falha neste site
        await self._page.evaluate("document.getElementById('btnSubmit').click()")
        logger.debug("Botão BUSCAR clicado via JS.")

        # Se havia resultado anterior, espera ele sumir primeiro (evita falso positivo)
        if tem_resultado_anterior:
            try:
                await self._page.wait_for_selector(
                    SEL_RESULTADO_ATIVO, state="hidden", timeout=5000
                )
            except PlaywrightTimeout:
                pass  # se não sumiu, continua mesmo assim

        # Aguarda o resultado aparecer — usa delay_segundos como timeout máximo.
        # Assim, se o site responder em 3s num delay de 15s, avança imediatamente.
        timeout_ms = max(delay_segundos * 1000, 8000)  # mínimo 8s
        logger.info(f"Aguardando resultado (timeout máx: {timeout_ms / 1000:.0f}s)...")
        try:
            await self._page.wait_for_selector(
                SEL_RESULTADO_ATIVO,
                state="visible",
                timeout=timeout_ms,
            )
        except PlaywrightTimeout:
            raise TimeoutConsultaError(
                f"Resultado não apareceu após {timeout_ms / 1000:.0f}s de espera"
            )

    # ── Extração do resultado ─────────────────────────────────────────

    async def _extrair_resultado(self) -> ResultadoRota:
        """
        Extrai campos fixos do painel #painelResults e todos os fretes de
        #tabelaDeFrete0 (visível quando selectCarga = "todas").
        """
        texto_painel = await self._page.inner_text(SEL_PAINEL_RESULTADO)
        logger.debug(f"Texto do painel (primeiros 400 chars):\n{texto_painel[:400]}")

        async def _texto(sel: str) -> str:
            try:
                el = await self._page.query_selector(sel)
                return (await el.inner_text()).strip() if el else ""
            except Exception:
                return ""

        def _fmt_brl(val: str) -> str:
            v = val.strip()
            if not v:
                return ""
            return v if v.startswith("R$") else f"R$ {v}"

        tempo          = await _texto(SEL_TEMPO)
        rota_descricao = await _texto(SEL_TITULO)
        distancia      = await _texto(SEL_DISTANCIA)
        vl_pedagio     = _fmt_brl(await _texto(SEL_VL_PEDAGIO))
        vl_combustivel = _fmt_brl(await _texto(SEL_VL_COMBUSTIVEL))
        vl_total       = _fmt_brl(await _texto(SEL_VL_TOTAL))

        # Fallbacks via regex no texto completo do painel
        if not distancia:
            distancia = self._regex_distancia(texto_painel)
        if not tempo:
            tempo = self._regex_tempo(texto_painel)
        if not vl_pedagio:
            vl_pedagio = self._regex_pedagio(texto_painel)
        if not vl_combustivel:
            vl_combustivel = self._regex_combustivel(texto_painel)
        if not vl_total:
            vl_total = self._regex_total(texto_painel)
        if not rota_descricao:
            rota_descricao = self._regex_rota(texto_painel)

        if not distancia and not vl_pedagio:
            html_painel = await self._page.inner_html(SEL_PAINEL_RESULTADO)
            logger.error(f"Resultado não extraído. HTML:\n{html_painel[:1500]}")
            raise ResultadoNaoEncontradoError(
                "Não foi possível extrair resultado. Seletores podem ter mudado."
            )

        # Extrai todos os 12 tipos de frete de uma vez via #tabelaDeFrete0
        fretes = await self._page.evaluate("""
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

        logger.info(
            f"Extraído — tempo={tempo} dist={distancia} pedágio={vl_pedagio} "
            f"combust={vl_combustivel} total={vl_total} fretes={len(fretes)} tipos"
        )

        return ResultadoRota(
            tempo_viagem=tempo,
            distancia_km=distancia,
            rota_descricao=rota_descricao,
            valor_pedagio=vl_pedagio,
            valor_combustivel=vl_combustivel,
            valor_total=vl_total,
            fretes=fretes,
            consultado_em=datetime.now(timezone.utc).isoformat(),
        )

    # ── Regex fallbacks ───────────────────────────────────────────────

    @staticmethod
    def _regex_distancia(texto: str) -> str:
        m = re.search(r"(\d{1,4}[.,]\d{1,2})\s*km", texto, re.IGNORECASE)
        return f"{m.group(1)} km" if m else ""

    @staticmethod
    def _regex_pedagio(texto: str) -> str:
        m = re.search(r"ped[aá]gio[^R\n]*R\$\s*([\d.,]+)", texto, re.IGNORECASE)
        return f"R$ {m.group(1)}" if m else ""

    @staticmethod
    def _regex_combustivel(texto: str) -> str:
        m = re.search(r"combust[ií]vel[^R\n]*R\$\s*([\d.,]+)", texto, re.IGNORECASE)
        return f"R$ {m.group(1)}" if m else ""

    @staticmethod
    def _regex_total(texto: str) -> str:
        m = re.search(r"total[^R\n]*R\$\s*([\d.,]+)", texto, re.IGNORECASE)
        return f"R$ {m.group(1)}" if m else ""

    @staticmethod
    def _regex_tempo(texto: str) -> str:
        m = re.search(r"(\d+)\s*h\s*(\d+)\s*min", texto, re.IGNORECASE)
        if m:
            return f"{m.group(1)}h{m.group(2)}min"
        m = re.search(r"(\d+)\s*h", texto, re.IGNORECASE)
        return f"{m.group(1)}h" if m else ""

    @staticmethod
    def _regex_rota(texto: str) -> str:
        m = re.search(r"via\s+(.+?)(?:\n|$)", texto, re.IGNORECASE)
        return m.group(0).strip() if m else ""
