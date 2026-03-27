from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime


@dataclass(frozen=True)
class ResultadoRota:
    """
    Value Object imutável com todos os campos extraídos do retorno do site.
    Os valores são mantidos como strings no formato original do site (ex: 'R$ 207,00').
    """
    tempo_viagem: str           # ex: "5 h 20 min"
    distancia_km: str           # ex: "386,2 km"
    rota_descricao: str         # ex: "via Rodovia Celso Garcia Cid..."
    valor_pedagio: str          # ex: "R$ 207,00"
    valor_combustivel: str      # ex: "R$ 1.119,91"
    valor_total: str            # ex: "R$ 1.326,91"
    valor_frete: Optional[str] = None   # ex: "R$ 3.511,62" (Carga Geral)
    consultado_em: Optional[str] = None # ISO datetime da consulta

    def to_dict(self) -> dict:
        return {
            "tempo_viagem": self.tempo_viagem,
            "distancia_km": self.distancia_km,
            "rota_descricao": self.rota_descricao,
            "valor_pedagio": self.valor_pedagio,
            "valor_combustivel": self.valor_combustivel,
            "valor_total": self.valor_total,
            "valor_frete": self.valor_frete,
            "consultado_em": self.consultado_em,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ResultadoRota":
        return cls(
            tempo_viagem=data.get("tempo_viagem", ""),
            distancia_km=data.get("distancia_km", ""),
            rota_descricao=data.get("rota_descricao", ""),
            valor_pedagio=data.get("valor_pedagio", ""),
            valor_combustivel=data.get("valor_combustivel", ""),
            valor_total=data.get("valor_total", ""),
            valor_frete=data.get("valor_frete"),
            consultado_em=data.get("consultado_em"),
        )
