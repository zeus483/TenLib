# router/response_parser.py
import json
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Captura JSON dentro de bloques ```json ... ``` o ``` ... ```
_MARKDOWN_JSON_RE = re.compile(
    r"```(?:json)?\s*(\{.*?\})\s*```",
    re.DOTALL,
)

# Captura el primer objeto JSON que aparezca en el texto
_BARE_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_model_response(raw_text: str, model_name: str) -> dict:
    """
    Intenta parsear la respuesta del modelo con degradación progresiva.

    Estrategia:
    1. JSON directo (el camino feliz)
    2. JSON dentro de bloque markdown
    3. Primer objeto JSON en el texto libre
    4. Extracción de emergencia (texto como traducción, confidence baja)

    Nunca lanza excepción — siempre devuelve un dict con las tres claves.
    """
    text = raw_text.strip()

    # Intento 1: JSON directo
    result = _try_parse(text)
    if result:
        return _validate_and_fill(result)

    # Intento 2: dentro de bloque markdown
    match = _MARKDOWN_JSON_RE.search(text)
    if match:
        result = _try_parse(match.group(1))
        if result:
            logger.warning(
                "%s envolvió la respuesta en markdown — considera reforzar el prompt",
                model_name,
            )
            return _validate_and_fill(result)

    # Intento 3: buscar cualquier objeto JSON en el texto
    match = _BARE_JSON_RE.search(text)
    if match:
        result = _try_parse(match.group(0))
        if result:
            logger.warning("%s devolvió JSON con texto extra alrededor", model_name)
            return _validate_and_fill(result)

    # Intento 4: recuperación de emergencia
    # El texto entero se trata como la traducción
    logger.error(
        "%s devolvió respuesta no parseable. Usando texto como traducción con confidence 0.3",
        model_name,
    )
    return {
        "translation": text,
        "confidence":  0.3,
        "notes":       f"ADVERTENCIA: respuesta no estructurada de {model_name}. Requiere revisión manual.",
    }


def _try_parse(text: str) -> Optional[dict]:
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, ValueError):
        pass
    return None


def _validate_and_fill(data: dict) -> dict:
    """
    Garantiza que el dict tiene las tres claves con tipos correctos.
    Rellena con defaults seguros si faltan.
    """
    translation = str(data.get("translation") or "").strip()
    if not translation:
        translation = str(data.get("text") or data.get("result") or "").strip()

    raw_confidence = data.get("confidence", 0.5)
    try:
        confidence = float(raw_confidence)
        confidence = max(0.0, min(1.0, confidence))  # clamp [0, 1]
    except (TypeError, ValueError):
        confidence = 0.5

    notes = str(data.get("notes") or data.get("note") or "Sin notas.").strip()

    return {
        "translation": translation,
        "confidence":  confidence,
        "notes":       notes,
    }