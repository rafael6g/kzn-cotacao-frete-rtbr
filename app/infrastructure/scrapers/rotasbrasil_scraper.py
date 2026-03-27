"""
Scraper para https://rotasbrasil.com.br

Estratégia:
- Browser Chromium abre UMA VEZ por lote (sessão persistente)
- Cada consulta preenche o formulário, aguarda o resultado e extrai os dados
- Autocomplete dos endereços é tratado com espera por sugestões + seleção
- reCAPTCHA v3 (invisível) — sem login pode aparecer após várias consultas;
  o scraper detecta e lança CaptchaDetectadoError para que o use case registre o erro
- O delay entre consultas é controlado pelo use case, NÃO aqui
"""

import re
import random
import asyncio
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


async def _digitar_humano(page, seletor: str, texto: str) -> None:
    """
    Digita texto caractere a caractere com delays variados simulando um digitador humano.
    - Velocidade base: ~60 WPM = ~200ms/char com variação ±80ms
    - Pausa extra ocasional (como quem pensa antes de continuar)
    - Pausa maior após vírgulas e espaços
    """
    await page.click(seletor)
    # Seleciona tudo e apaga antes de digitar
    await page.keyboard.press("Control+a")
    await page.keyboard.press("Delete")
    await asyncio.sleep(0.15)

    for i, char in enumerate(texto):
        await page.keyboard.type(char)

        if char in (",", "."):
            delay = random.uniform(0.25, 0.45)   # pausa após pontuação
        elif char == " ":
            delay = random.uniform(0.18, 0.32)   # pausa entre palavras
        else:
            delay = random.uniform(0.10, 0.22)   # digitação normal ~60 WPM

        # Pausa ocasional aleatória (como hesitar) — ~15% das teclas
        if random.random() < 0.15:
            delay += random.uniform(0.20, 0.50)

        await asyncio.sleep(delay)

URL_BASE = "https://rotasbrasil.com.br"

# ── Seletores do formulário ──────────────────────────────────────────
SEL_INPUT_ORIGEM      = "#txtEnderecoPartida"
SEL_INPUT_DESTINO     = "#txtEnderecoChegada"
SEL_BTN_BUSCAR        = "#btnSubmit"
SEL_INPUT_COMBUSTIVEL = "#precoCombustivel"
SEL_INPUT_CONSUMO     = "#consumo"
SEL_SELECT_CARGA      = "#selectCarga"
SEL_BTN_MOSTRAR_EIXO  = "#divMostrarEixo"   # botão que abre o seletor de eixos
SEL_PAINEL_RESULTADO  = "#painelResults"    # painel onde o resultado aparece
SEL_CAPTCHA_V2        = "#recaptchaV2"

# Mapeamento tipo_de_carga (texto) → valor do <select#selectCarga>
CARGA_VALORES = {
    "Carga Geral":   "353",
    "Granel":        "354",
    "Neogranel":     "355",
    "Frigorificado": "356",
    "Perigosa":      "357",
}

# ── Seletores dos campos do resultado ────────────────────────────────
SEL_RESULTADO_ATIVO = "div.routeResult.active"   # sinal de que o resultado carregou
SEL_TEMPO           = "div.color-primary-500"
SEL_DISTANCIA       = "div.distance"
SEL_QTD_PEDAGIO     = "#countPedagiosRota0"
SEL_VL_PEDAGIO      = "span.vlPedagio"
SEL_VL_COMBUSTIVEL  = "span.vlCombustivel"
SEL_VL_TOTAL        = "div.results b"
SEL_VL_FRETE        = "div.valorFreteMin .valorFreteMinDados.text-right"


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
            slow_mo=200 if not self._headless else settings.playwright_slow_mo_ms,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",   # importante para VPS com pouca RAM
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

        # Navega até a página inicial e aguarda carregar
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
            await self._selecionar_tipo_carga(params.tipo_carga)
            await self._submeter_formulario(delay_segundos=delay_segundos)
            resultado = await self._extrair_resultado(params)
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
        # Aguarda eventuais dropdowns fecharem
        await self._page.wait_for_timeout(300)

    async def _selecionar_veiculo(self, veiculo_id: int) -> None:
        """
        Clica no ícone do veículo correspondente.
        HTML: <div class="input icon-veiculo caminhao" veiculoId="2"></div>
        """
        classes = {1: "carro", 2: "caminhao", 3: "onibus", 4: "moto"}
        classe = classes.get(veiculo_id, "caminhao")
        sel = f"div.icon-veiculo.{classe}"
        try:
            await self._page.click(sel, timeout=5000)
            logger.debug(f"Veículo '{classe}' selecionado via clique.")
            await self._page.wait_for_timeout(1000)   # JS do site precisa reagir
        except Exception:
            await self._page.evaluate(
                f"document.getElementById('veiculo').value = '{veiculo_id}'"
            )
            logger.debug(f"Veículo {veiculo_id} setado via JS (fallback).")

    async def _preencher_endereco(self, seletor: str, endereco: str) -> None:
        """
        Digita o endereço e seleciona a primeira sugestão VISÍVEL do autocomplete jQuery UI.
        Formato esperado: "Cidade, Estado, Brasil" para garantir a seleção correta.
        Usa page.locator().first para evitar clicar em itens de listas anteriores já fechadas.
        """
        await _digitar_humano(self._page, seletor, endereco)

        try:
            loc = self._page.locator(".ui-autocomplete .ui-menu-item").first
            await loc.wait_for(state="visible", timeout=4000)
            sugestao = (await loc.inner_text()).strip()
            await loc.click()
            logger.debug(f"Autocomplete: clicou em '{sugestao[:50]}' para: {endereco}")
            # Aguarda a lista fechar antes de prosseguir para o próximo campo
            await self._page.locator(".ui-autocomplete").wait_for(state="hidden", timeout=2000)
        except Exception:
            await self._page.press(seletor, "Tab")
            logger.debug(f"Sem autocomplete — Tab pressionado para: {endereco}")

        await self._page.wait_for_timeout(500)

    async def _selecionar_tipo_carga(self, tipo_carga: str) -> None:
        """
        Seleciona tipo de carga no <select id="selectCarga">.
        O valor do option é numérico (ex: "353" = Carga Geral).
        """
        valor = CARGA_VALORES.get(tipo_carga, "353")
        try:
            await self._page.select_option(SEL_SELECT_CARGA, valor)
            logger.debug(f"Tipo de carga '{tipo_carga}' → valor '{valor}' selecionado.")
        except Exception as e:
            logger.warning(f"Não foi possível selecionar tipo de carga: {e}")

    async def _preencher_combustivel(self, preco: float, consumo: float) -> None:
        preco_str = f"{preco:.2f}".replace(".", ",")
        consumo_str = f"{consumo:.2f}".replace(".", ",")

        await _digitar_humano(self._page, SEL_INPUT_COMBUSTIVEL, preco_str)
        await asyncio.sleep(random.uniform(0.3, 0.6))
        await _digitar_humano(self._page, SEL_INPUT_CONSUMO, consumo_str)

        logger.debug(f"Combustível: R$ {preco_str}/L | Consumo: {consumo_str} km/L")

    async def _selecionar_eixos(self, eixos: int) -> None:
        """
        Seleciona número de eixos — fluxo real do site legado:
        1. Após clicar no caminhão, aparece #divMostrarEixo (botão "mostrar eixos")
        2. Clicar em #divMostrarEixo abre o painel de eixos
        3. Clicar em div.eixoDiv[eixoid='{n}'] seleciona o eixo
        Fallback: seta #eixo hidden input via JS.
        """
        try:
            # Aguarda o botão de eixos aparecer (só existe para caminhão)
            await self._page.wait_for_selector(SEL_BTN_MOSTRAR_EIXO, timeout=5000, state="visible")
            await self._page.click(SEL_BTN_MOSTRAR_EIXO)
            await self._page.wait_for_timeout(800)

            # Clica no eixo correto
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
        Clica em BUSCAR via JavaScript (clique direto falha nesse site)
        e aguarda o resultado aparecer.
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

        # IMPORTANTE: clique via JS — clique direto falha neste site
        await self._page.evaluate("document.getElementById('btnSubmit').click()")
        logger.debug("Botão BUSCAR clicado via JS.")

        # ── Delay configurável: consulta → aguarda N segundos → extrai ──
        # O site precisa de tempo para processar e renderizar.
        # O delay também evita detecção de bot (comportamento humano).
        espera_ms = max(delay_segundos * 1000, 2000)  # mínimo 2s
        logger.info(f"Aguardando {espera_ms / 1000:.0f}s para o resultado carregar...")
        await self._page.wait_for_timeout(espera_ms)

        # Confirma que o resultado realmente carregou após a espera
        try:
            await self._page.wait_for_selector(
                SEL_RESULTADO_ATIVO,
                state="visible",
                timeout=10000,  # 10s extra caso ainda não tenha aparecido
            )
        except PlaywrightTimeout:
            raise TimeoutConsultaError(
                f"Resultado não apareceu após {espera_ms / 1000:.0f}s de espera"
            )

    # ── Extração do resultado ─────────────────────────────────────────

    async def _extrair_resultado(self, params: ParametrosRota) -> ResultadoRota:
        """
        Extrai campos do painel #painelResults.
        Seletores baseados no script Selenium legado que funcionava.
        Fallback: regex no texto do painel.
        """
        texto_painel = await self._page.inner_text(SEL_PAINEL_RESULTADO)
        logger.debug(f"Texto do painel (primeiros 400 chars):\n{texto_painel[:400]}")

        async def _texto(sel: str) -> str:
            try:
                el = await self._page.query_selector(sel)
                return (await el.inner_text()).strip() if el else ""
            except Exception:
                return ""

        async def _attr(sel: str, attr: str) -> str:
            try:
                el = await self._page.query_selector(sel)
                return (await el.get_attribute(attr) or "").strip() if el else ""
            except Exception:
                return ""

        def _fmt_brl(val: str) -> str:
            """Garante prefixo R$ e formato consistente: R$ 1.234,56"""
            v = val.strip()
            if not v:
                return ""
            if not v.startswith("R$"):
                v = f"R$ {v}"
            return v

        tempo          = await _texto(SEL_TEMPO)
        distancia      = await _texto(SEL_DISTANCIA)
        vl_pedagio     = _fmt_brl(await _texto(SEL_VL_PEDAGIO))
        vl_combustivel = _fmt_brl(await _texto(SEL_VL_COMBUSTIVEL))
        vl_total       = _fmt_brl(await _texto(SEL_VL_TOTAL))
        vl_frete       = _fmt_brl(await _texto(SEL_VL_FRETE))
        qtd_pedagio    = (await _attr(SEL_QTD_PEDAGIO, "textContent")).strip() or await _texto(SEL_QTD_PEDAGIO)

        # Fallbacks via regex no texto completo do painel
        if not distancia:
            distancia = self._regex_distancia(texto_painel)
        if not tempo:
            tempo = self._regex_tempo(texto_painel)
        if not vl_pedagio:
            vl_pedagio = self._regex_pedagio(texto_painel)
        if not vl_combustivel:
            vl_combustivel = self._regex_combustivel(texto_painel)
        if not vl_frete:
            vl_frete = self._regex_frete(texto_painel, params.tipo_carga)
        if not vl_total:
            vl_total = self._regex_total(texto_painel)

        if not distancia and not vl_pedagio:
            html_painel = await self._page.inner_html(SEL_PAINEL_RESULTADO)
            logger.error(f"Resultado não extraído. HTML:\n{html_painel[:1500]}")
            raise ResultadoNaoEncontradoError(
                "Não foi possível extrair resultado. Seletores podem ter mudado."
            )

        rota_descricao = self._regex_rota(texto_painel)

        logger.info(
            f"Extraído — tempo={tempo} dist={distancia} pedágio={vl_pedagio} "
            f"combust={vl_combustivel} frete={vl_frete}"
        )

        return ResultadoRota(
            tempo_viagem=tempo,
            distancia_km=distancia,
            rota_descricao=rota_descricao,
            valor_pedagio=vl_pedagio,
            valor_combustivel=vl_combustivel,
            valor_total=vl_total,
            valor_frete=vl_frete if vl_frete else None,
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

    @staticmethod
    def _regex_frete(texto: str, tipo_carga: str) -> str:
        m = re.search(
            rf"{re.escape(tipo_carga)}[^R\n]*R\$\s*([\d.,]+)",
            texto,
            re.IGNORECASE,
        )
        return f"R$ {m.group(1)}" if m else ""
