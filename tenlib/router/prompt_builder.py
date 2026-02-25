# router/prompt_builder.py
from typing import Optional


_TRANSLATE_SYSTEM = """\
    Eres un editor y traductor literario experto. Tu objetivo es traducir el \
    fragmento que recibirás manteniendo fielmente el tono, el ritmo y los matices \
    estilísticos del autor, sin omitir ni resumir ninguna frase original.

    --- CONTEXTO DE LA OBRA ---
    - Idioma origen: {source_lang}
    - Idioma destino: {target_lang}
    - Voz narrativa general: {voice}

    --- BIBLIA DEL LIBRO (reglas estrictas e inquebrantables) ---

    GLOSARIO (términos con traducción fija — NO alterar):
    {glossary}

    DECISIONES DE ESTILO (aplicar sin excepción):
    {decisions}

    PERSONAJES (tono y personalidad para los diálogos):
    {characters}

    --- CONTINUIDAD ---
    Escena inmediatamente anterior: {last_scene}

    --- INSTRUCCIONES DE SALIDA ---
    Responde ÚNICAMENTE con un objeto JSON válido.
    Para asegurar la máxima calidad, primero analiza los retos del texto, \
    luego asigna tu nivel de confianza, y finalmente entrega la traducción.

    Estructura estricta del JSON:
    {{
    "notes": "Analiza los desafíos del fragmento (modismos, tono, jerga) y documenta \
    las decisiones de traducción tomadas. Prohibido dejar vacío.",
    "confidence": 0.0,
    "translation": "El texto traducido completo, respetando párrafos y saltos de línea del original."
    }}

    Reglas del JSON:
    - "notes" va primero — es tu proceso de razonamiento antes de traducir.
    - "confidence": float entre 0.0 y 1.0.
        * 1.0 = traducción directa, sin pérdida de matices.
        * < 0.75 = ambigüedad, múltiples opciones válidas, o expresiones idiomáticas complejas.
    - No omitas ni resumas ninguna frase del fragmento original.
    - Si usas bloque markdown, el contenido interno debe ser JSON válido y parseable.
    """

# Fallbacks — nunca dejan secciones vacías en el prompt
_VOICE_DEFAULT       = "narrador en tercera persona, tiempo pasado"
_GLOSSARY_EMPTY      = "Sin glosario todavía — extrae términos relevantes que encuentres."
_DECISIONS_EMPTY     = "Ninguna todavía — este es el primer fragmento."
_CHARACTERS_EMPTY    = "Sin perfiles definidos todavía — infiere el tono de cada personaje del texto."
_LAST_SCENE_EMPTY    = "Inicio del libro — no hay contexto previo."


def build_translate_prompt(
    source_lang: str,
    target_lang: str,
    voice:       str             = _VOICE_DEFAULT,
    decisions:   list[str]       = None,
    glossary:    dict            = None,
    characters:  dict            = None,   # ← nuevo parámetro
    last_scene:  Optional[str]   = None,
) -> str:
    """
    Construye el system prompt para el modo traducción.

    El fragmento a traducir NO va aquí — viaja como mensaje de usuario
    en la llamada al modelo. Esto mantiene separadas las instrucciones
    del contenido y mejora la adherencia a las reglas en todos los modelos.
    """
    return _TRANSLATE_SYSTEM.format(
        source_lang = source_lang,
        target_lang = target_lang,
        voice       = voice or _VOICE_DEFAULT,
        glossary    = _format_glossary(glossary),
        decisions   = _format_decisions(decisions),
        characters  = _format_characters(characters),
        last_scene  = last_scene or _LAST_SCENE_EMPTY,
    )


# ------------------------------------------------------------------
# Formatters internos — cada sección tiene su propia lógica
# ------------------------------------------------------------------

def _format_glossary(glossary: Optional[dict]) -> str:
    if not glossary:
        return _GLOSSARY_EMPTY
    return "\n".join(f"  - {src} → {tgt}" for src, tgt in glossary.items())


def _format_decisions(decisions: Optional[list[str]]) -> str:
    if not decisions:
        return _DECISIONS_EMPTY
    return "\n".join(f"  - {d}" for d in decisions)


def _format_characters(characters: Optional[dict]) -> str:
    """
    Formatea el apartado de personajes de la Book Bible.

    Entrada esperada (estructura del README):
    {
        "Kvothe": "protagonista, voz activa, habla directo y sin rodeos",
        "Chronicler": "escriba, tono formal y observador"
    }
    """
    if not characters:
        return _CHARACTERS_EMPTY
    lines = []
    for name, description in characters.items():
        lines.append(f"  - {name}: {description}")
    return "\n".join(lines)