# router/claude.py
import logging
import time
from typing import TYPE_CHECKING

import anthropic

from tenlib.router.base import BaseModel
from tenlib.router.models import ModelConfig, ModelResponse
from tenlib.router.response_parser import parse_model_response

if TYPE_CHECKING:
    from tenlib.storage.repository import Repository

logger = logging.getLogger(__name__)

# Errores que activan failover hacia otro modelo
_RETRYABLE_ERRORS = (
    anthropic.RateLimitError,
    anthropic.APITimeoutError,
    anthropic.APIConnectionError,
)


class ClaudeAdapter(BaseModel):

    def __init__(self, config: ModelConfig, repo: "Repository"):
        self._config = config
        self._repo   = repo
        self._client = anthropic.Anthropic(
            api_key     = config.api_key,
            timeout     = config.timeout_seconds,
        )

    @property
    def name(self) -> str:
        return self._config.name   # "claude" — coincide con quota_usage.model

    def is_available(self) -> bool:
        # Primero: ¿está en cooldown temporal por error de red?
        if self._config._unavailable_until is not None:
            if time.time() < self._config._unavailable_until:
                return False
            self._config._unavailable_until = None  # cooldown expirado

        # Segundo: ¿tiene quota disponible hoy?
        used = self._repo.get_token_usage_today(self.name)
        return used < self._config.daily_token_limit

    def translate(self, chunk: str, system_prompt: str) -> ModelResponse:
        try:
            response = self._client.messages.create(
                model      = "claude-haiku-4-5-20251001",
                max_tokens = 4096,
                temperature = self._config.temperature,
                system     = system_prompt,
                messages   = [{"role": "user", "content": chunk}],
            )
        except _RETRYABLE_ERRORS as e:
            logger.warning("Claude error retryable: %s", e)
            # Cooldown de 5 minutos antes de intentar Claude de nuevo
            self._config._unavailable_until = time.time() + 300
            raise   # El Router captura esto y hace failover

        except anthropic.BadRequestError as e:
            # El chunk en sí tiene problemas (ej: contenido bloqueado)
            # No es un error de disponibilidad — es un error de contenido
            logger.error("Claude BadRequest en chunk: %s", e)
            raise

        raw_text       = response.content[0].text
        tokens_input   = response.usage.input_tokens
        tokens_output  = response.usage.output_tokens

        # Reportar tokens reales al storage
        self._repo.add_token_usage(self.name, tokens_input + tokens_output)

        parsed = parse_model_response(raw_text, self.name)

        return ModelResponse(
            translation   = parsed["translation"],
            confidence    = parsed["confidence"],
            notes         = parsed["notes"],
            model_used    = self.name,
            tokens_input  = tokens_input,
            tokens_output = tokens_output,
        )