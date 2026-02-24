# router/config_loader.py
import os
from pathlib import Path
from typing import Optional

import yaml

from tenlib.router.models import ModelConfig

_DEFAULT_CONFIG_PATH = Path.home() / ".tenlib" / "config.yaml"


def load_model_configs(config_path: Optional[str] = None) -> list[ModelConfig]:
    """
    Carga la configuración de modelos desde YAML.
    Resuelve variables de entorno en los api_key (${VAR}).
    Devuelve la lista ordenada por prioridad ascendente.
    """
    path = Path(config_path or os.environ.get("TENLIB_CONFIG_PATH") or _DEFAULT_CONFIG_PATH)

    if not path.exists():
        raise FileNotFoundError(
            f"Config no encontrada en {path}. "
            f"Copia config.example.yaml a ~/.tenlib/config.yaml"
        )

    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    configs = []
    for entry in raw.get("models", []):
        api_key = _resolve_env(entry.get("api_key"))
        configs.append(ModelConfig(
            name              = entry["name"],
            priority          = entry.get("priority", 99),
            daily_token_limit = entry.get("daily_token_limit", 80_000),
            api_key           = api_key,
            timeout_seconds   = entry.get("timeout_seconds", 60),
            temperature       = entry.get("temperature", 0.3),
        ))

    return sorted(configs, key=lambda c: c.priority)


def _resolve_env(value: Optional[str]) -> Optional[str]:
    """Expande ${VAR_NAME} desde el entorno."""
    if not value or not value.startswith("${"):
        return value
    var_name = value.strip("${}").strip()
    return os.environ.get(var_name)