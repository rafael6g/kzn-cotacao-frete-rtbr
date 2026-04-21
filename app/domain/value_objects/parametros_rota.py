import hashlib
from dataclasses import dataclass
from typing import Optional


VEICULO_LABELS = {1: "Carro", 2: "Caminhão", 3: "Ônibus", 4: "Moto"}


@dataclass(frozen=True)
class ParametrosRota:
    """
    Value Object imutável com todos os parâmetros de uma consulta de rota.
    A chave de cache é derivada deterministicamente deste objeto.
    """
    origem: str
    destino: str
    veiculo: int          # 1=Carro 2=Caminhão 3=Ônibus 4=Moto
    eixos: int            # número de eixos (ex: 6)
    preco_combustivel: float
    consumo_km_l: float
    tipo_carga: str = "todas"
    evitar_pedagio: bool = False
    evitar_balsa: bool = False
    data_tarifa: Optional[str] = None  # formato YYYY-MM-DD
    site: str = ""  # "" = rotasbrasil (chave legada), "qualp" = qualp.com.br

    def chave_cache(self) -> str:
        """SHA-256 dos parâmetros normalizados — usado como índice no Xano."""
        partes = "|".join([
            self.site.lower().strip(),
            self.origem.lower().strip(),
            self.destino.lower().strip(),
            str(self.veiculo),
            str(self.eixos),
            f"{self.preco_combustivel:.2f}",
            f"{self.consumo_km_l:.2f}",
            self.tipo_carga.lower().strip(),
            str(self.evitar_pedagio),
            str(self.evitar_balsa),
            self.data_tarifa or "",
        ])
        return hashlib.sha256(partes.encode("utf-8")).hexdigest()

    @property
    def veiculo_label(self) -> str:
        return VEICULO_LABELS.get(self.veiculo, "Desconhecido")

    def to_dict(self) -> dict:
        return {
            "origem": self.origem,
            "destino": self.destino,
            "veiculo": self.veiculo,
            "veiculo_label": self.veiculo_label,
            "eixos": self.eixos,
            "preco_combustivel": self.preco_combustivel,
            "consumo_km_l": self.consumo_km_l,
            "tipo_carga": self.tipo_carga,
            "evitar_pedagio": self.evitar_pedagio,
            "evitar_balsa": self.evitar_balsa,
            "data_tarifa": self.data_tarifa,
            "site": self.site,
        }
