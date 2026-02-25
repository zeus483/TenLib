# router/models.py
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ModelResponse:
    translation:  str
    confidence:   float
    notes:        str
    model_used:   str
    tokens_input: int
    tokens_output: int


@dataclass
class ModelConfig:
    """
    Configuración de un modelo individual.
    Se carga desde ~/.tenlib/config.yaml.
    """
    name:              str
    priority:          int
    daily_token_limit: int
    api_key:           Optional[str] = None   # None si es plan Pro/free
    timeout_seconds:   int = 60
    temperature:       float = 0.3

    # Control de cooldown temporal (no viene del YAML, es runtime)
    _unavailable_until: Optional[float] = field(
        default=None, compare=False, repr=False
    )