from dataclasses import dataclass
from typing import Optional
from datetime import datetime
from enum import Enum

from app.domain.value_objects.parametros_rota import ParametrosRota
from app.domain.value_objects.resultado_rota import ResultadoRota


class StatusCotacao(str, Enum):
    AGUARDANDO = "aguardando"
    CACHE = "cache"
    CONSULTADO = "consultado"
    ERRO = "erro"


class FonteResultado(str, Enum):
    CACHE = "cache"
    SITE = "site"


@dataclass
class Cotacao:
    lote_id: int
    linha_numero: int
    parametros: ParametrosRota
    id: Optional[int] = None
    resultado: Optional[ResultadoRota] = None
    status: StatusCotacao = StatusCotacao.AGUARDANDO
    fonte: Optional[FonteResultado] = None
    erro_mensagem: Optional[str] = None
    created_at: Optional[datetime] = None
