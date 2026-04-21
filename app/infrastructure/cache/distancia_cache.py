"""
Cache persistente de distâncias entre cidades — armazenado no Xano.
Compartilhado por todos os scrapers (QualP, RotasBrasil, ANTT).

Estrutura de cada registro no Xano (tabela cache_distancias):
  id, origem, destino, km, pedagio, pracas (json)
"""

import re
import threading

import httpx

from app.core.logging_config import get_logger

logger = get_logger(__name__)

_lock = threading.Lock()

# Cache em memória por sessão — evita múltiplas chamadas ao Xano para a mesma rota
_mem: dict = {}


def _get_settings():
    from app.core.config import get_settings
    return get_settings()


def _url() -> str:
    s = _get_settings()
    return f"{s.xano_url}{s.xano_ep_cache_distancias}"


def _chave(origem: str, destino: str) -> str:
    return f"{origem.lower().strip()}||{destino.lower().strip()}"


def _str_para_int(km: str) -> int:
    """'1.052,6 km' ou '1052 km' → 1052"""
    num = re.sub(r"[^\d,]", "", km.split(",")[0].replace(".", ""))
    return int(num) if num else 0


def _normalizar_pracas(pedagios: list) -> list:
    """Converte lista de praças do scraper para o formato do cache."""
    pracas = []
    for p in (pedagios or []):
        por_eixo = p.get("por_eixo", "")
        if por_eixo and not por_eixo.startswith("R$"):
            por_eixo = f"R${por_eixo}"
        pracas.append({
            "nome":           p.get("nome", ""),
            "rodovia":        p.get("rodovia", ""),
            "valor":          p.get("tarifa", ""),
            "valor_por_eixo": por_eixo,
        })
    return pracas


def _buscar_xano(origem: str, destino: str) -> dict | None:
    """Busca no Xano pelo par origem+destino. Retorna o registro completo ou None."""
    try:
        resp = httpx.get(
            _url(),
            params={"origem": origem, "destino": destino},
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        items = resp.json()
        if isinstance(items, dict):
            items = items.get("items", [])
        for item in items:
            if (item.get("origem", "").lower().strip() == origem.lower().strip() and
                    item.get("destino", "").lower().strip() == destino.lower().strip()):
                return item
        return None
    except Exception as e:
        logger.warning(f"Cache distância Xano GET erro: {e}")
        return None


def buscar(origem: str, destino: str) -> tuple[str, int] | None:
    """Retorna (km_str, km_int) se encontrado, ou None."""
    chave = _chave(origem, destino)
    with _lock:
        if chave in _mem:
            v = _mem[chave]
            return v["km"], _str_para_int(v["km"])

    v = _buscar_xano(origem, destino)
    if v:
        with _lock:
            _mem[chave] = v
        logger.debug(f"Cache distância hit: {origem} → {destino} = {v['km']}")
        return v["km"], _str_para_int(v["km"])
    return None


def buscar_completo(origem: str, destino: str) -> dict | None:
    """Retorna o registro completo do cache ou None."""
    chave = _chave(origem, destino)
    with _lock:
        if chave in _mem:
            logger.debug(f"Cache distância hit (mem): {origem} → {destino}")
            return _mem[chave]

    v = _buscar_xano(origem, destino)
    if v:
        with _lock:
            _mem[chave] = v
        logger.debug(f"Cache distância hit (Xano): {origem} → {destino} = {v['km']}")
        return v
    return None


def salvar(
    origem: str,
    destino: str,
    distancia_str: str,
    distancia_int: int | None = None,
    pedagio: str = "",
    pedagios: list | None = None,
) -> None:
    """Salva ou atualiza o par origem→destino no Xano."""
    if not distancia_str:
        return

    pracas_novas = _normalizar_pracas(pedagios) if pedagios else None
    chave = _chave(origem, destino)

    existente = _buscar_xano(origem, destino)

    # pracas: só atualiza se vier lista não-vazia (apenas QualP tem praças)
    pracas_salvar = (
        pracas_novas if pracas_novas
        else (existente.get("pracas", []) if existente else [])
    )
    payload = {
        "km":      distancia_str,
        "pedagio": pedagio or (existente.get("pedagio", "") if existente else ""),
        "pracas":  pracas_salvar,
    }

    try:
        if existente:
            resp = httpx.patch(
                f"{_url()}/{existente['id']}",
                json=payload,
                timeout=10,
            )
        else:
            payload["origem"] = origem
            payload["destino"] = destino
            resp = httpx.post(_url(), json=payload, timeout=10)

        if resp.status_code in (200, 201):
            registro = resp.json()
            with _lock:
                _mem[chave] = registro
            logger.info(
                f"Cache distância salvo: {origem} → {destino} = {distancia_str}"
                + (f" | pedágio={pedagio}" if pedagio else "")
                + (f" | {len(pracas_novas)} praças" if pracas_novas else "")
            )
        else:
            logger.warning(f"Cache distância Xano save erro {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        logger.warning(f"Cache distância Xano save exceção: {e}")
