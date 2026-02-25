# router/gemini.py
import logging
import time
from typing import TYPE_CHECKING

import google.generativeai as genai
from google.api_core import exceptions as google_exceptions

from tenlib.router.base import BaseModel
from tenlib.router.models import ModelConfig, ModelResponse
from tenlib.router.response_parser import parse_model_response

if TYPE_CHECKING:
    from tenlib.storage.repository import Repository

logger = logging.getLogger(__name__)

_RETRYABLE_ERRORS = (
    google_exceptions.ResourceExhausted,   # 429
    google_exceptions.DeadlineExceeded,    # timeout
    google_exceptions.ServiceUnavailable,
)

_GENERATION_CONFIG = {
    "response_mime_type": "application/json",   # Gemini soporta forzar JSON nativo
}


class GeminiAdapter(BaseModel):

    def __init__(self, config: ModelConfig, repo: "Repository"):
        self._config = config
        self._repo   = repo
        genai.configure(api_key=config.api_key)
        self._model = genai.GenerativeModel(
            model_name     = "gemini-2.0-flash",
            generation_config = genai.GenerationConfig(
                temperature       = config.temperature,
                response_mime_type = "application/json",
            ),
        )

    @property
    def name(self) -> str:
        return self._config.name   # "gemini"

    def is_available(self) -> bool:
        if self._config._unavailable_until is not None:
            if time.time() < self._config._unavailable_until:
                return False
            self._config._unavailable_until = None

        used = self._repo.get_token_usage_today(self.name)
        return used < self._config.daily_token_limit

    def translate(self, chunk: str, system_prompt: str) -> ModelResponse:
        full_prompt = f"{system_prompt}\n\n{chunk}"

        try:
            response = self._model.generate_content(
                full_prompt,
                request_options={"timeout": self._config.timeout_seconds},
            )
        except _RETRYABLE_ERRORS as e:
            logger.warning("Gemini error retryable: %s", e)
            self._config._unavailable_until = time.time() + 300
            raise

        raw_text      = response.text
        # Gemini devuelve tokens en usage_metadata
        tokens_input  = response.usage_metadata.prompt_token_count
        tokens_output = response.usage_metadata.candidates_token_count

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