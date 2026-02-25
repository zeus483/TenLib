# router/base.py
from abc import ABC, abstractmethod
from tenlib.router.models import ModelResponse


class BaseModel(ABC):
    """
    Contrato que deben cumplir todos los adaptadores.
    El Orchestrator y el Router solo hablan con esta interfaz.
    Nunca importan claude.py, gemini.py ni gpt.py directamente.
    """

    @abstractmethod
    def translate(self, chunk: str, system_prompt: str) -> ModelResponse:
        """
        Envía el chunk al modelo y devuelve una ModelResponse.
        Nunca lanza excepción por contenido inválido — los errores
        de parseo se capturan internamente y se reflejan en
        confidence y notes.
        SÍ puede lanzar: TimeoutError, RateLimitError, APIError.
        El Router los captura y hace failover.
        """
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """
        Consulta quota del día en storage antes de hacer cualquier
        llamada de red. Si superó el límite → False sin latencia.
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Identificador del modelo. Debe coincidir con quota_usage.model."""
        ...