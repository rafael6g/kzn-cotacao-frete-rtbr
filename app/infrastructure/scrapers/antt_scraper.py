"""
AnttScraper — Calculadora Oficial ANTT (calculadorafrete.antt.gov.br)

Fluxo por linha:
  1. Playwright: RotasBrasil → preenche O/D → extrai div.distance (km)
  2. httpx: GET ANTT → extrai CSRF token
  3. httpx: POST ANTT × 12 tipos de carga → extrai valores
"""

import re
import random
from datetime import datetime, timezone
from typing import Optional

import httpx
from playwright.async_api import async_playwright

from app.application.interfaces.site_scraper import SiteScraper
from app.domain.value_objects.parametros_rota import ParametrosRota
from app.domain.value_objects.resultado_rota import ResultadoRota
from app.core.logging_config import get_logger

logger = get_logger(__name__)

URL_ANTT = "https://calculadorafrete.antt.gov.br/"
URL_RB   = "https://rotasbrasil.com.br"

# ID numérico ANTT → chave de coluna Excel (mesma do QualP/RotasBrasil)
_TIPO_CARGA_COLS = {
    1:  "Tipo_Carga_Granel Sólido",
    2:  "Tipo_Carga_Granel Líquido",
    3:  "Tipo_Carga_Frigorificada",
    4:  "Tipo_Carga_Conteinerizada",
    5:  "Tipo_Carga_Carga Geral",
    6:  "Tipo_Carga_Neogranel",
    7:  "Tipo_Carga_Perigosa (granel sólido)",
    8:  "Tipo_Carga_Perigosa (granel líquido)",
    9:  "Tipo_Carga_Perigosa (frigorificada)",
    10: "Tipo_Carga_Perigosa (conteinerizada)",
    11: "Tipo_Carga_Perigosa (carga geral)",
    12: "Tipo_Carga_Granel Pressurizada",
}

# Nome do dropdown ANTT → ID numérico
_TIPO_CARGA_NOME_IDS = {
    "Granel sólido": 1,
    "Granel líquido": 2,
    "Frigorificada ou Aquecida": 3,
    "Conteinerizada": 4,
    "Carga Geral": 5,
    "Neogranel": 6,
    "Perigosa (granel sólido)": 7,
    "Perigosa (granel líquido)": 8,
    "Perigosa (Frigorificada ou Aquecida)": 9,
    "Perigosa (conteinerizada)": 10,
    "Perigosa (carga geral)": 11,
    "Carga Granel Pressurizada": 12,
}

# tabela_frete A/B/C/D → (composicao_veicular, alto_desempenho)
_TABELA_FLAGS = {
    "A": (True,  False),
    "B": (False, False),
    "C": (True,  True),
    "D": (False, True),
}

# Eixos suportados pela ANTT (sem 8 — arredonda para 7)
_EIXOS_VALIDOS = [2, 3, 4, 5, 6, 7, 9]

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def _checkbox(nome: str, valor: bool) -> list:
    """ASP.NET MVC checkbox pattern: checked → [true, false]; unchecked → [false]."""
    if valor:
        return [(nome, "true"), (nome, "false")]
    return [(nome, "false")]


def _montar_payload(tipo_id: int, eixos: int, distancia: int,
                    composicao: bool, alto_desempenho: bool,
                    retorno_vazio: bool, csrf: str) -> list:
    payload = [
        ("__RequestVerificationToken", csrf),
        ("Filtro.IdTipoCarga",         str(tipo_id)),
        ("Filtro.NumeroEixos",         str(eixos)),
        ("Filtro.Distancia",           str(distancia)),
    ]
    payload += _checkbox("Filtro.CargaLotacao",   composicao)
    payload += _checkbox("Filtro.AltoDesempenho", alto_desempenho)
    payload += _checkbox("Filtro.RetornoVazio",   retorno_vazio)
    return payload


def _span_apos(html: str, rotulo: str) -> str:
    idx = html.find(rotulo)
    if idx == -1:
        return ""
    m = re.search(r"<span[^>]*>(.*?)</span>", html[idx:], re.DOTALL)
    return re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else ""


def _valor_total(html: str) -> str:
    m = re.search(r'class="[^"]*valorFrete[^"]*"[^>]*>(.*?)</', html, re.DOTALL)
    if m:
        return re.sub(r"<[^>]+>", "", m.group(1)).strip()
    m = re.search(r"R\$\s*[\d.,]+", html)
    return m.group(0).strip() if m else ""


def _parsear_resposta(html: str) -> dict:
    return {
        "tabela_nome":    _span_apos(html, "Operação de Transporte"),
        "ccd":            _span_apos(html, "Coeficiente de custo de deslocamento (CCD)"),
        "cc":             _span_apos(html, "Coeficiente de custo de carga e descarga (CC)"),
        "valor_ida":      _span_apos(html, "Valor de ida"),
        "valor_retorno":  _span_apos(html, "Valor do retorno vazio"),
        "valor_total":    _valor_total(html),
    }


class AnttScraper(SiteScraper):

    def __init__(self, headless: bool = True):
        self._headless = headless
        self._pw       = None
        self._browser  = None
        self._page     = None   # página RotasBrasil (reutilizada entre linhas)
        self._client: Optional[httpx.AsyncClient] = None
        self._ativo    = False

    async def iniciar_sessao(self) -> None:
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=self._headless,
            slow_mo=0,
            args=["--no-sandbox", "--disable-setuid-sandbox",
                  "--disable-blink-features=AutomationControlled"],
        )
        ctx = await self._browser.new_context(
            user_agent=_UA,
            viewport={"width": 1366, "height": 768},
            locale="pt-BR",
        )
        self._page = await ctx.new_page()
        await self._page.goto(URL_RB, wait_until="networkidle", timeout=30000)

        self._client = httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
            headers={
                "User-Agent": _UA,
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                "Accept-Language": "pt-BR,pt;q=0.9",
            },
        )
        self._ativo = True
        logger.info("AnttScraper: sessão iniciada (RotasBrasil + httpx ANTT)")

    async def encerrar_sessao(self) -> None:
        try:
            if self._browser:
                await self._browser.close()
            if self._pw:
                await self._pw.stop()
        except Exception as e:
            logger.warning(f"AnttScraper: erro ao fechar browser: {e}")
        try:
            if self._client:
                await self._client.aclose()
        except Exception as e:
            logger.warning(f"AnttScraper: erro ao fechar httpx: {e}")
        self._ativo = False

    async def esta_ativo(self) -> bool:
        return self._ativo

    async def consultar(self, parametros: ParametrosRota, delay_segundos: int = 0) -> ResultadoRota:
        # 1. Distância via RotasBrasil (ou valor manual da planilha)
        if parametros.distancia_km:
            distancia_int = int(parametros.distancia_km)
            distancia_str = f"{distancia_int} km"
            logger.debug(f"ANTT: distância manual {distancia_str}")
        else:
            distancia_str, distancia_int = await self._buscar_km(
                parametros.origem, parametros.destino
            )
            logger.debug(f"ANTT: distância via RotasBrasil {distancia_str} → {distancia_int} km")

        # 2. Mapeamento de parâmetros
        composicao, alto_desempenho = _TABELA_FLAGS.get(
            parametros.tabela_frete.upper(), (True, False)
        )
        eixos = max((e for e in _EIXOS_VALIDOS if e <= parametros.eixos), default=2)
        retorno_vazio = getattr(parametros, "retorno_vazio", False)

        # 3. CSRF fresco para este conjunto de requisições
        csrf = await self._obter_csrf()

        # 4. Resolve tipo_carga: pode vir como ID numérico (form) ou nome (planilha)
        tc = parametros.tipo_carga or "5"
        if tc.isdigit():
            tipo_id = int(tc)
        else:
            tipo_id = _TIPO_CARGA_NOME_IDS.get(tc, 5)
        col_key = _TIPO_CARGA_COLS.get(tipo_id, f"Tipo_Carga_{tc}")

        # 5. POST único para o tipo selecionado
        payload = _montar_payload(
            tipo_id, eixos, distancia_int,
            composicao, alto_desempenho, retorno_vazio, csrf
        )
        try:
            resp = await self._client.post(
                URL_ANTT,
                data=payload,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": URL_ANTT,
                },
            )
            resp.raise_for_status()
            r = _parsear_resposta(resp.text)
        except Exception as e:
            logger.warning(f"ANTT: erro tipo_id={tipo_id}: {e}")
            r = {}

        tabela_nome       = r.get("tabela_nome", "")
        ccd               = r.get("ccd", "")
        cc                = r.get("cc", "")
        valor_ida         = r.get("valor_ida", "")
        valor_retorno_str = r.get("valor_retorno", "")
        valor_total_str   = r.get("valor_total", "")

        fretes: dict = {col_key: valor_total_str}
        fretes["antt_ccd"] = ccd
        fretes["antt_cc"]  = cc

        return ResultadoRota(
            tempo_viagem="",
            distancia_km=distancia_str,
            rota_descricao=tabela_nome,
            valor_pedagio=valor_ida,
            valor_combustivel=valor_retorno_str,
            valor_total=valor_total_str,
            fretes=fretes,
            pedagios=[],
            consultado_em=datetime.now(timezone.utc).isoformat(),
        )

    # ── Helpers privados ──────────────────────────────────────────────

    async def _obter_csrf(self) -> str:
        resp = await self._client.get(URL_ANTT)
        m = re.search(
            r'name="__RequestVerificationToken"\s+type="hidden"\s+value="([^"]+)"',
            resp.text,
        )
        if not m:
            m = re.search(r'__RequestVerificationToken[^>]*value="([^"]+)"', resp.text)
        if not m:
            raise RuntimeError("ANTT: CSRF token não encontrado na página")
        return m.group(1)

    async def _buscar_km(self, origem: str, destino: str) -> tuple[str, int]:
        """
        Preenche O/D no RotasBrasil (página já aberta), aguarda resultado,
        extrai div.distance e retorna (str_original, int_km).
        """
        page = self._page
        SEL_RESULTADO = "div.routeResult.active"

        # Limpa e preenche origem
        await page.fill("#txtEnderecoPartida", "")
        await page.type("#txtEnderecoPartida", origem, delay=random.randint(10, 25))
        await page.wait_for_timeout(1200)
        try:
            loc = page.locator(".ui-autocomplete .ui-menu-item").first
            await loc.wait_for(state="visible", timeout=3000)
            await loc.click()
            await page.locator(".ui-autocomplete").wait_for(state="hidden", timeout=2000)
        except Exception:
            await page.press("#txtEnderecoPartida", "Tab")

        # Limpa e preenche destino
        await page.fill("#txtEnderecoChegada", "")
        await page.type("#txtEnderecoChegada", destino, delay=random.randint(10, 25))
        await page.wait_for_timeout(1200)
        try:
            loc = page.locator(".ui-autocomplete .ui-menu-item").first
            await loc.wait_for(state="visible", timeout=3000)
            await loc.click()
            await page.locator(".ui-autocomplete").wait_for(state="hidden", timeout=2000)
        except Exception:
            await page.press("#txtEnderecoChegada", "Tab")

        # Se já existe resultado anterior, aguarda sumir antes de buscar
        tem_anterior = await page.query_selector(SEL_RESULTADO) is not None
        await page.evaluate("document.getElementById('btnSubmit').click()")
        if tem_anterior:
            try:
                await page.wait_for_selector(SEL_RESULTADO, state="hidden", timeout=5000)
            except Exception:
                pass

        await page.wait_for_selector(SEL_RESULTADO, state="visible", timeout=30000)

        el = await page.query_selector("div.distance")
        distancia_str = (await el.inner_text()).strip() if el else "0 km"

        # "3.076,6 km" → 3076
        num = re.sub(r"[^\d,]", "", distancia_str.split(",")[0].replace(".", ""))
        distancia_int = int(num) if num else 0

        return distancia_str, distancia_int
