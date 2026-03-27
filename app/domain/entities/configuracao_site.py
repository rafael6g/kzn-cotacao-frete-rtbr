from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime


@dataclass
class ConfiguracaoSite:
    nome: str
    url_base: str
    validade_cache_horas: int
    delay_padrao_segundos: int
    campos_input: dict
    campos_resultado: dict
    id: Optional[int] = None
    descricao: str = ""
    ativo: bool = True
    created_at: Optional[datetime] = None
