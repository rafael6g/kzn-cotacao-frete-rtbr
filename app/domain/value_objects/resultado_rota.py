from dataclasses import dataclass, field
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
    fretes: dict = field(default_factory=dict)    # ex: {"Carga Geral": "R$ 3.511,62", ...}
    pedagios: list = field(default_factory=list)  # ex: [{"nome": "P3 - Jacarezinho", "rodovia": "BR-369 - KM 1.500", "tarifa": "R$64,00", "por_eixo": "12,80 eixo"}]
    consultado_em: str = ""     # ISO datetime da consulta
    expira_em_iso: str = ""     # Data de expiração do cache (DD/MM/AAAA HH:MM), injetado pelo repo

    def to_dict(self) -> dict:
        return {
            "tempo_viagem": self.tempo_viagem,
            "distancia_km": self.distancia_km,
            "rota_descricao": self.rota_descricao,
            "valor_pedagio": self.valor_pedagio,
            "valor_combustivel": self.valor_combustivel,
            "valor_total": self.valor_total,
            "fretes": self.fretes,
            "pedagios": self.pedagios,
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
            fretes=data.get("fretes", {}),
            pedagios=data.get("pedagios", []),
            consultado_em=data.get("consultado_em", ""),
            expira_em_iso=data.get("expira_em_iso", ""),
        )
