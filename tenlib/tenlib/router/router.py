# router/router.py
import logging
from router.base import BaseModel
from router.models import ModelResponse

logger = logging.getLogger(__name__)


class AllModelsExhaustedError(Exception):
    """Se lanza cuando ningún modelo tiene quota disponible."""
    pass


class Router:
    """
    Decide qué modelo usar en cada llamada.
    El Orchestrator llama a Router.translate() — nunca a un adaptador directamente.

    Responsabilidades:
    - Seleccionar el modelo disponible de mayor prioridad
    - Hacer failover si el modelo falla por error de red o rate limit
    - Propagar errores de contenido (no son de disponibilidad)
    """

    def __init__(self, models: list[BaseModel]):
        # La lista ya viene ordenada por prioridad desde el config
        if not models:
            raise ValueError("El Router necesita al menos un modelo")
        self._models = models

    def translate(self, chunk: str, system_prompt: str) -> ModelResponse:
        """
        Intenta traducir el chunk con el mejor modelo disponible.
        Si falla por rate limit o red, hace failover automático.
        Lanza AllModelsExhaustedError si ninguno está disponible.
        """
        last_error: Exception | None = None

        for model in self._models:
            if not model.is_available():
                logger.info("Modelo %s no disponible (quota), saltando", model.name)
                continue

            try:
                logger.debug("Intentando traducción con %s", model.name)
                response = model.translate(chunk, system_prompt)
                logger.info(
                    "Chunk traducido con %s | tokens: %d+%d | confidence: %.2f",
                    model.name,
                    response.tokens_input,
                    response.tokens_output,
                    response.confidence,
                )
                return response

            except Exception as e:
                # Distinguimos entre errores retryables (red, quota)
                # y errores de contenido (el chunk tiene un problema)
                if _is_content_error(e):
                    logger.error(
                        "Error de contenido en %s — no se hace failover: %s",
                        model.name, e,
                    )
                    raise

                logger.warning(
                    "Modelo %s falló con error retryable: %s. Pasando al siguiente.",
                    model.name, e,
                )
                last_error = e
                continue

        raise AllModelsExhaustedError(
            f"Ningún modelo disponible. Último error: {last_error}"
        )

    def available_models(self) -> list[str]:
        """Útil para logging y para la UI."""
        return [m.name for m in self._models if m.is_available()]


def _is_content_error(e: Exception) -> bool:
    """
    Determina si el error es del contenido del chunk (no de disponibilidad).
    Estos errores no activan failover — son el mismo error en cualquier modelo.
    """
    import anthropic
    import google.api_core.exceptions as google_ex

    content_errors = (
        anthropic.BadRequestError,
        google_ex.InvalidArgument,
        ValueError,
    )
    return isinstance(e, content_errors)