"""
AnttScraper — Calculadora Oficial ANTT (calculadorafrete.antt.gov.br)

Fluxo por linha:
  1. Cache em disco (data/cache_distancias.json) → se já tiver o par, usa direto
  2. Se não tiver: Nominatim (OSM) geocodifica origem/destino → OSRM calcula km
  3. httpx: GET ANTT → extrai CSRF token
  4. httpx: POST ANTT → extrai valores de frete
  Tudo via httpx síncrono em asyncio.to_thread (sem Playwright).
"""

import asyncio
import json
import re
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app.application.interfaces.site_scraper import SiteScraper
from app.domain.value_objects.parametros_rota import ParametrosRota
from app.domain.value_objects.resultado_rota import ResultadoRota
from app.infrastructure.cache import distancia_cache
from app.core.logging_config import get_logger

logger = get_logger(__name__)

URL_ANTT      = "https://calculadorafrete.antt.gov.br/"
URL_NOMINATIM = "https://nominatim.openstreetmap.org/search"
URL_OSRM      = "http://router.project-osrm.org/route/v1/driving"

# Cache de geocodificação em memória (por sessão) — evita múltiplas chamadas ao Nominatim
_geo_mem:  dict = {}
_lock_geo  = threading.Lock()

# ID numérico ANTT → chave de coluna Excel
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

_UA_APP = "RotaBrasilCotacoes/1.0 (rafael.londrina@gmail.com)"
_UA_BROWSER = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def _checkbox(nome: str, valor: bool) -> list:
    """ASP.NET MVC checkbox pattern."""
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
        "tabela_nome":   _span_apos(html, "Operação de Transporte"),
        "ccd":           _span_apos(html, "Coeficiente de custo de deslocamento (CCD)"),
        "cc":            _span_apos(html, "Coeficiente de custo de carga e descarga (CC)"),
        "valor_ida":     _span_apos(html, "Valor de ida"),
        "valor_retorno": _span_apos(html, "Valor do retorno vazio"),
        "valor_total":   _valor_total(html),
    }


def _fmt_km_br(km: float) -> str:
    """1052.4 → '1.052,4 km'  |  658.2 → '658,2 km'"""
    inteiro = int(km)
    decimal = round((km - inteiro) * 10)
    inteiro_fmt = f"{inteiro:,}".replace(",", ".")
    return f"{inteiro_fmt},{decimal} km"


class AnttScraper(SiteScraper):

    def __init__(self, headless: bool = True):
        self._ativo = False

    async def iniciar_sessao(self) -> None:
        self._ativo = True
        logger.info("AnttScraper: sessão iniciada (Nominatim + OSRM + httpx ANTT)")

    async def encerrar_sessao(self) -> None:
        self._ativo = False

    async def esta_ativo(self) -> bool:
        return self._ativo

    async def consultar(self, parametros: ParametrosRota, delay_segundos: int = 0) -> ResultadoRota:
        composicao, alto_desempenho = _TABELA_FLAGS.get(
            parametros.tabela_frete.upper(), (True, False)
        )
        retorno_vazio = getattr(parametros, "retorno_vazio", False)
        eixos   = max((e for e in _EIXOS_VALIDOS if e <= parametros.eixos), default=2)
        tc      = parametros.tipo_carga or "5"
        tipo_id = int(tc) if tc.isdigit() else _TIPO_CARGA_NOME_IDS.get(tc, 5)

        if parametros.distancia_km:
            distancia_int = int(parametros.distancia_km)
            distancia_str = f"{distancia_int} km"
            cache_rota = None
            logger.debug(f"ANTT: distância manual {distancia_str}")
        else:
            cache_rota = distancia_cache.buscar_completo(parametros.origem, parametros.destino)
            if cache_rota:
                distancia_str = cache_rota["km"]
                distancia_int = distancia_cache._str_para_int(distancia_str)
                logger.debug(f"ANTT: distância do cache {distancia_str}")
            else:
                distancia_str, distancia_int = await asyncio.to_thread(
                    self._buscar_km_sync, parametros.origem, parametros.destino
                )
                cache_rota = distancia_cache.buscar_completo(parametros.origem, parametros.destino)
                logger.debug(f"ANTT: distância {distancia_str} ({distancia_int} km)")

        r = await asyncio.to_thread(
            self._calcular_sync, tipo_id, eixos, distancia_int,
            composicao, alto_desempenho, retorno_vazio,
        )

        # Aproveita pedágio e praças do cache (salvo por QualP/RotasBrasil)
        valor_pedagio_cache = cache_rota.get("pedagio", "") if cache_rota else ""
        pedagios_cache      = [
            {"nome": p["nome"], "tarifa": p["valor"], "por_eixo": p["valor_por_eixo"], "rodovia": p["rodovia"]}
            for p in (cache_rota.get("pracas", []) if cache_rota else [])
        ]

        col_key = _TIPO_CARGA_COLS.get(tipo_id, f"Tipo_Carga_{tc}")
        fretes: dict = {col_key: r.get("valor_total", "")}
        fretes["antt_ccd"]          = r.get("ccd", "")
        fretes["antt_cc"]           = r.get("cc", "")
        fretes["antt_valor_ida"]    = r.get("valor_ida", "")
        fretes["antt_valor_retorno"]= r.get("valor_retorno", "")

        return ResultadoRota(
            tempo_viagem="",
            distancia_km=distancia_str,
            rota_descricao=r.get("tabela_nome", ""),
            valor_pedagio=valor_pedagio_cache,
            valor_combustivel="",
            valor_total=r.get("valor_total", ""),
            fretes=fretes,
            pedagios=pedagios_cache,
            consultado_em=datetime.now(timezone.utc).isoformat(),
        )

    # ── Helpers síncronos (rodam em asyncio.to_thread) ───────────────

    def _geocodificar_sync(self, client: httpx.Client, endereco: str) -> tuple[float, float]:
        """Nominatim: cidade → (lon, lat). Cache em memória por sessão."""
        chave = endereco.lower().strip()
        with _lock_geo:
            if chave in _geo_mem:
                return _geo_mem[chave]["lon"], _geo_mem[chave]["lat"]

        time.sleep(1.1)  # Nominatim: máx 1 req/s
        resp = client.get(URL_NOMINATIM, params={
            "q": endereco,
            "format": "json",
            "limit": 1,
            "countrycodes": "br",
        })
        resp.raise_for_status()
        dados = resp.json()
        if not dados:
            raise RuntimeError(f"Nominatim: endereço não encontrado: {endereco!r}")
        lon = float(dados[0]["lon"])
        lat = float(dados[0]["lat"])
        with _lock_geo:
            _geo_mem[chave] = {"lon": lon, "lat": lat}
        logger.debug(f"ANTT/Nominatim: {endereco!r} → lon={lon} lat={lat}")
        return lon, lat

    def _buscar_km_sync(self, origem: str, destino: str) -> tuple[str, int]:
        """Busca distância: cache em disco primeiro, depois Nominatim + OSRM."""
        cached = distancia_cache.buscar(origem, destino)
        if cached:
            return cached

        headers = {"User-Agent": _UA_APP, "Accept-Language": "pt-BR,pt;q=0.9"}
        with httpx.Client(timeout=15, follow_redirects=True, headers=headers) as client:
            lon1, lat1 = self._geocodificar_sync(client, origem)
            lon2, lat2 = self._geocodificar_sync(client, destino)

            resp = client.get(
                f"{URL_OSRM}/{lon1},{lat1};{lon2},{lat2}",
                params={"overview": "false"},
            )
            resp.raise_for_status()
            dados = resp.json()
            if dados.get("code") != "Ok" or not dados.get("routes"):
                raise RuntimeError(f"OSRM sem rota: {dados.get('code')}")

            distancia_m   = dados["routes"][0]["distance"]
            distancia_km  = distancia_m / 1000
            distancia_int = round(distancia_km)
            distancia_str = _fmt_km_br(distancia_km)

        distancia_cache.salvar(origem, destino, distancia_str, distancia_int)
        return distancia_str, distancia_int

    def _calcular_sync(
        self,
        tipo_id: int, eixos: int, distancia_int: int,
        composicao: bool, alto_desempenho: bool, retorno_vazio: bool,
    ) -> dict:
        """GET (CSRF) + POST (cálculo ANTT) — httpx síncrono."""
        headers = {
            "User-Agent": _UA_BROWSER,
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9",
        }
        try:
            with httpx.Client(timeout=30, follow_redirects=True, headers=headers) as client:
                resp_get = client.get(URL_ANTT)
                m = re.search(
                    r'name="__RequestVerificationToken"\s+type="hidden"\s+value="([^"]+)"',
                    resp_get.text,
                )
                if not m:
                    m = re.search(r'__RequestVerificationToken[^>]*value="([^"]+)"', resp_get.text)
                if not m:
                    raise RuntimeError("CSRF token não encontrado")
                csrf = m.group(1)

                payload = _montar_payload(
                    tipo_id, eixos, distancia_int,
                    composicao, alto_desempenho, retorno_vazio, csrf,
                )
                resp_post = client.post(
                    URL_ANTT,
                    content=urllib.parse.urlencode(payload).encode(),
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Referer": URL_ANTT,
                        "Origin": "https://calculadorafrete.antt.gov.br",
                    },
                )
                logger.info(f"ANTT: POST status={resp_post.status_code}")
                resp_post.raise_for_status()
                r = _parsear_resposta(resp_post.text)
                logger.info(
                    f"ANTT: parsed → tabela={r.get('tabela_nome')!r} "
                    f"total={r.get('valor_total')!r} ccd={r.get('ccd')!r}"
                )
                if not r.get("valor_total"):
                    logger.warning(f"ANTT: resposta vazia — primeiros 500 chars:\n{resp_post.text[:500]}")
                return r
        except Exception as e:
            logger.error(f"ANTT: erro HTTP tipo_id={tipo_id}: {e}")
            return {}
