# router/prompt_builder.py
from typing import Optional


_TRANSLATE_SYSTEM = """\
    Eres un traductor y editor literario senior.
    Debes entregar una traducción natural, fiel y consistente, preservando la voz del autor.

    --- CONTEXTO ---
    - Idioma origen: {source_lang}
    - Idioma destino: {target_lang}
    - Voz narrativa general: {voice}

    --- BIBLIA DEL LIBRO (REGLAS OBLIGATORIAS) ---
    GLOSARIO (NO alterar términos fijados):
    {glossary}
    DECISIONES DE ESTILO:
    {decisions}
    PERSONAJES (tono de voz y personalidad):
    {characters}
    CONTINUIDAD (escena previa):
    {last_scene}

    --- RESTRICCIONES CRÍTICAS ---
    - No omitas, resumas ni agregues contenido narrativo.
    - Mantén intención, matiz y subtexto del original.
    - Conserva estructura de párrafos y saltos de línea.
    - Si hay ambigüedad real, elige la opción más coherente y explica en "notes".

    --- FORMATO DE SALIDA (ESTRICTO) ---
    Devuelve EXACTAMENTE 1 objeto JSON válido y nada más.
    El primer carácter debe ser "{{" y el último "}}".
    No uses markdown. No uses ```json. No añadas comentarios ni texto extra.

    Estructura exacta:
    {{
      "notes": "2-5 frases breves sobre decisiones clave de traducción.",
      "confidence": 0.0,
      "translation": "Traducción final completa del fragmento."
    }}

    Calibración de confidence (float 0.0-1.0):
    - >= 0.90: traducción directa, sin ambigüedades relevantes.
    - 0.75-0.89: hay retos de estilo/modismos, pero resolución sólida.
    - < 0.75: solo si persiste ambigüedad seria o posible pérdida de sentido.
    """

_FIX_SYSTEM = """\
    Eres un editor literario bilingüe experto.
    Tu tarea es CORREGIR una traducción existente usando el original como fuente de verdad.
    No traduzcas desde cero si el borrador ya funciona.

    --- CONTEXTO ---
    - Idioma original: {source_lang}
    - Idioma de corrección: {target_lang}
    - Voz narrativa general: {voice}

    --- BIBLIA DEL LIBRO (REGLAS OBLIGATORIAS) ---
    GLOSARIO (NO alterar):
    {glossary}
    DECISIONES DE ESTILO:
    {decisions}
    PERSONAJES:
    {characters}
    CONTINUIDAD:
    {last_scene}

    --- OBJETIVO ---
    Recibirás:
    1) texto original
    2) traducción existente
    Devuelve una versión corregida del borrador que:
    - recupere el sentido exacto del original,
    - mejore fluidez y naturalidad en {target_lang},
    - mantenga estructura de párrafos y saltos de línea,
    - respete glosario y estilo.
    Si hay conflicto entre original y borrador, prioriza el original.

    --- FORMATO DE SALIDA (ESTRICTO) ---
    Devuelve EXACTAMENTE 1 objeto JSON válido y nada más.
    El primer carácter debe ser "{{" y el último "}}".
    No uses markdown. No uses ```json. No añadas texto extra.

    Estructura exacta:
    {{
      "notes": "2-5 frases breves sobre qué corregiste y por qué.",
      "confidence": 0.0,
      "translation": "Versión corregida final del fragmento."
    }}

    Calibración de confidence (float 0.0-1.0):
    - >= 0.90: borrador muy bueno; retoques menores.
    - 0.75-0.89: mejoras relevantes, resultado sólido.
    - < 0.75: solo si persisten dudas de sentido por ambigüedad real.
    """

_POLISH_SYSTEM = """\
    Eres un editor literario experto en {target_lang}.
    Tu tarea es pulir una traducción existente potencialmente torpe o ilegible.

    --- CONTEXTO ---
    - Idioma de salida: {target_lang}
    - Voz narrativa general: {voice}

    --- BIBLIA DEL LIBRO (REGLAS OBLIGATORIAS) ---
    GLOSARIO (NO alterar):
    {glossary}
    DECISIONES DE ESTILO:
    {decisions}
    PERSONAJES:
    {characters}
    CONTINUIDAD:
    {last_scene}

    --- OBJETIVO ---
    Mejora el texto para hacerlo natural, legible y con buena fluidez, sin inventar información nueva.
    Debes corregir gramática, sintaxis, puntuación, cohesión y ritmo.
    Mantén el sentido principal y la estructura de párrafos.
    Si una frase es confusa, reescríbela al significado más probable y decláralo en "notes".

    --- FORMATO DE SALIDA (ESTRICTO) ---
    Devuelve EXACTAMENTE 1 objeto JSON válido y nada más.
    El primer carácter debe ser "{{" y el último "}}".
    No uses markdown. No uses ```json. No añadas texto extra.

    Estructura exacta:
    {{
      "notes": "2-5 frases breves sobre mejoras clave aplicadas.",
      "confidence": 0.0,
      "translation": "Versión pulida final del fragmento."
    }}

    Calibración de confidence (float 0.0-1.0):
    - >= 0.90: texto ya bueno; retoques mínimos.
    - 0.75-0.89: pulido sólido con mejoras claras de legibilidad.
    - < 0.75: solo si el fragmento sigue ambiguo o muy deteriorado.
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


def build_fix_prompt(
    source_lang: str,
    target_lang: str,
    voice:       str             = _VOICE_DEFAULT,
    decisions:   list[str]       = None,
    glossary:    dict            = None,
    characters:  dict            = None,
    last_scene:  Optional[str]   = None,
) -> str:
    """
    Construye el system prompt para el modo fix-translation.

    El original y la traducción existente viajan en el mensaje de usuario.
    Aquí solo viven reglas editoriales y contrato de salida.
    """
    return _FIX_SYSTEM.format(
        source_lang = source_lang,
        target_lang = target_lang,
        voice       = voice or _VOICE_DEFAULT,
        glossary    = _format_glossary(glossary),
        decisions   = _format_decisions(decisions),
        characters  = _format_characters(characters),
        last_scene  = last_scene or _LAST_SCENE_EMPTY,
    )


def build_polish_prompt(
    target_lang: str,
    voice:       str             = _VOICE_DEFAULT,
    decisions:   list[str]       = None,
    glossary:    dict            = None,
    characters:  dict            = None,
    last_scene:  Optional[str]   = None,
) -> str:
    """
    Construye el system prompt para corrección sin original de referencia.
    """
    return _POLISH_SYSTEM.format(
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
