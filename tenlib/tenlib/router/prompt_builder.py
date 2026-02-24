# router/prompt_builder.py
from typing import Optional


# Separado del builder porque puede crecer:
# fix_translation, write, summarize tienen sus propias plantillas.
_TRANSLATE_SYSTEM = """\
Eres un editor literario profesional especializado en traducción literaria.
Tu tarea es traducir el fragmento de texto que recibirás preservando:
- La voz narrativa y el tono del autor
- Los matices estilísticos y el ritmo de las frases
- Cualquier rasgo cultural o lingüístico relevante

PARÁMETROS DE TRADUCCIÓN:
- Idioma origen: {source_lang}
- Idioma destino: {target_lang}
- Voz narrativa: {voice}

DECISIONES DE ESTILO TOMADAS (respétalas sin excepción):
{decisions}

GLOSARIO (estos términos tienen traducción fija — no los alteres):
{glossary}

CONTEXTO DE CONTINUIDAD (lo que ocurrió justo antes de este fragmento):
{last_scene}

INSTRUCCIÓN DE RESPUESTA:
Responde ÚNICAMENTE con un objeto JSON con esta estructura exacta:
{{
  "translation": "el texto traducido completo",
  "confidence": 0.0,
  "notes": "decisiones tomadas, dudas o advertencias"
}}

Reglas del JSON:
- confidence es un float entre 0.0 y 1.0
- 1.0 = traducción directa y sin ambigüedad
- < 0.75 = había ambigüedad, múltiples opciones válidas, o expresión idiomática difícil
- notes documenta las decisiones importantes (no escribas "ninguna" — siempre hay algo)
- Sin texto fuera del JSON
- Sin bloques de código markdown
- Sin explicaciones previas ni posteriores

FRAGMENTO A TRADUCIR:
"""

_DECISIONS_EMPTY = "Ninguna todavía — este es el primer fragmento."
_GLOSSARY_EMPTY  = "Sin glosario todavía — extrae términos relevantes que encuentres."
_LAST_SCENE_EMPTY = "Inicio del libro — no hay contexto previo."


def build_translate_prompt(
    source_lang:  str,
    target_lang:  str,
    voice:        str        = "narrador en tercera persona",
    decisions:    list[str]  = None,
    glossary:     dict       = None,
    last_scene:   str        = None,
) -> str:
    """
    Construye el system prompt para el modo traducción.
    Todos los parámetros opcionales tienen fallbacks seguros —
    nunca deja secciones vacías que confundan al modelo.
    """
    decisions_str = (
        "\n".join(f"- {d}" for d in decisions)
        if decisions else _DECISIONS_EMPTY
    )

    glossary_str = (
        "\n".join(f"- {k} → {v}" for k, v in glossary.items())
        if glossary else _GLOSSARY_EMPTY
    )

    return _TRANSLATE_SYSTEM.format(
        source_lang = source_lang,
        target_lang = target_lang,
        voice       = voice,
        decisions   = decisions_str,
        glossary    = glossary_str,
        last_scene  = last_scene or _LAST_SCENE_EMPTY,
    )