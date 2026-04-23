import time
from dataclasses import dataclass
from typing import Optional

import httpx

from app.core.config import get_settings


@dataclass
class UsuarioAtual:
    id: int
    nome: str
    email: str
    role: str
    empresa_id: int
    empresa_nome: str


_cache: dict[str, tuple[UsuarioAtual, float]] = {}
_CACHE_TTL = 60.0


async def validar_token(token: str) -> Optional[UsuarioAtual]:
    agora = time.monotonic()

    usuario, expira_em = _cache.get(token, (None, 0.0))
    if usuario and agora < expira_em:
        return usuario

    settings = get_settings()
    if not settings.kzn_auth_url:
        return None

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{settings.kzn_auth_url}/kzn_auth/me",
                headers={"Authorization": f"Bearer {token}"},
            )
        if resp.status_code != 200:
            return None

        data = resp.json()
        empresa = data.get("empresa") or {}
        usuario = UsuarioAtual(
            id=data["id"],
            nome=data.get("nome", ""),
            email=data.get("email", ""),
            role=data.get("role", "user"),
            empresa_id=data.get("empresa_id", 0),
            empresa_nome=empresa.get("nome", "") if isinstance(empresa, dict) else str(empresa),
        )
        _cache[token] = (usuario, agora + _CACHE_TTL)
        return usuario
    except Exception:
        return None
