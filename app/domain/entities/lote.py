from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime
from enum import Enum


class StatusLote(str, Enum):
    AGUARDANDO = "aguardando"
    PROCESSANDO = "processando"
    CONCLUIDO = "concluido"
    ERRO = "erro"
    CANCELADO = "cancelado"


@dataclass
class LoteCotacao:
    nome: str
    configuracao_site_id: int
    total_linhas: int
    delay_segundos: int
    arquivo_entrada: str
    id: Optional[int] = None
    status: StatusLote = StatusLote.AGUARDANDO
    linhas_processadas: int = 0
    linhas_cache: int = 0
    linhas_consultadas: int = 0
    linhas_erro: int = 0
    arquivo_saida: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @property
    def percentual(self) -> float:
        if self.total_linhas == 0:
            return 0.0
        return round((self.linhas_processadas / self.total_linhas) * 100, 1)

    @property
    def finalizado(self) -> bool:
        return self.status in (StatusLote.CONCLUIDO, StatusLote.ERRO, StatusLote.CANCELADO)
