class RotaBrasilError(Exception):
    """Base para todas as exceções do domínio."""


class SiteIndisponivelError(RotaBrasilError):
    """Site não respondeu ou está fora do ar."""


class ResultadoNaoEncontradoError(RotaBrasilError):
    """Consulta executada mas nenhum resultado foi extraído."""


class CaptchaDetectadoError(RotaBrasilError):
    """reCAPTCHA bloqueou a consulta."""


class TimeoutConsultaError(RotaBrasilError):
    """Timeout aguardando o resultado da consulta."""


class ExcelInvalidoError(RotaBrasilError):
    """Arquivo Excel malformado ou colunas ausentes."""


class XanoApiError(RotaBrasilError):
    """Erro na comunicação com a API do Xano."""
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        super().__init__(f"Xano API {status_code}: {detail}")
