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
    tabela_frete: str = "A"  # "A" | "B" | "C" | "D" — ANTT Resolução 5.867/2026
    retorno_vazio: bool = False          # ANTT — adiciona 0,92 × dist × CCD ao valor
    distancia_km: Optional[float] = None # ANTT — km da rota (se None, busca via RotasBrasil)

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
            self.tabela_frete.upper(),
            str(self.retorno_vazio),
            str(int(self.distancia_km)) if self.distancia_km else "",
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
            "tabela_frete": self.tabela_frete,
            "retorno_vazio": self.retorno_vazio,
            "distancia_km": self.distancia_km,
        }
