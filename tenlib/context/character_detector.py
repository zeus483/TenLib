import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional


def _normalize_static(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.lower().strip()


_NAME_RE = re.compile(r"\b[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,}\b")

_SPEECH_VERBS = {
    "dijo", "dijeron", "pregunto", "preguntó", "respondio", "respondió",
    "grito", "gritó", "susurro", "susurró", "murmuro", "murmuró",
    "exclamo", "exclamó", "anadio", "añadió",
}
_SPEECH_VERBS_NORMALIZED = {_normalize_static(v) for v in _SPEECH_VERBS}
_ACTION_VERBS = {
    "miro", "miró", "sonrio", "sonrió", "asintio", "asintió",
    "avanzo", "avanzó", "ataco", "atacó", "corrio", "corrió",
    "rio", "rió", "sonrio", "sonrió", "penso", "pensó",
    "ordeno", "ordenó", "entro", "entró", "salio", "salió",
}
_ACTION_VERBS_NORMALIZED = {_normalize_static(v) for v in _ACTION_VERBS}
_TITLE_HINTS = {
    "señor", "señora", "sr", "sra", "sir", "lady", "lord",
    "rey", "reina", "príncipe", "principe", "princesa",
    "general", "capitán", "capitan", "doctor", "doctora",
}
_TITLE_HINTS_NORMALIZED = {
    _normalize_static(value)
    for value in _TITLE_HINTS
}

# Preposiciones genitivas: "de/del" antes de un nombre → señal de lugar u organización.
# "de Tempest", "del Reino" = lugar/org. Diferente de "a Diego" (personal a = personaje).
_GENITIVE_PREPOSITIONS = {"de", "del"}

_NON_CHARACTER_WORDS = {
    _normalize_static(word)
    for word in {
    # Pronombres y artículos
    "el", "la", "los", "las", "un", "una",
    "de", "del", "al", "en", "por", "para", "con", "sin",
    "el", "él", "ella", "ellas", "ello", "ellos",
    "eso", "esto", "esta", "este", "antes", "despues", "después",
    "cuando", "mientras", "aunque", "porque", "pero", "como", "qué", "que",
    "entonces", "asi", "así", "todavia", "todavía", "bueno",
    "luego", "ahora",
    "estaba", "era", "fue", "es", "son", "eres", "estas", "estás",
    "escuche", "escuché",
    "señor", "senor",
    # Lugares, lugares genéricos y partes del mundo ficticio
    "sala", "control", "centro", "verdad", "cualquiera", "demonio",
    # Títulos de grupo y colectivos (no son personajes individuales)
    "guardianes", "guardian", "guerreros", "guerrero",
    "soldados", "soldado", "angeles", "angel",
    "generales", "lideres",
    "ejercito", "ejercitos",
    # Números que aparecen capitalizados como parte de títulos de grupo
    "doce", "siete", "tres", "diez", "cinco", "seis", "ocho", "nueve", "once",
    # Ruido típico de novelas japonesas traducidas
    "kufufufu", "jajaja", "jejeje", "hahaha",
    # Metadatos / sistema
    "texto", "original", "chunk", "capitulo", "capítulo",
    # Marcadores de página/sección frecuentes en light novels escaneadas
    "pagina", "página", "regreso", "estrella",
    # Tipos y razas que no son nombres propios individuales
    "dragon", "slime", "demon", "angel",
    # Títulos en inglés que no son nombres propios
    "lord", "king", "queen", "emperor", "master",
    # Palabras comunes del inglés que aparecen en textos originales sin traducir
    "the", "that", "this", "time", "got", "from", "with", "when", "then",
    "they", "them", "their", "there", "have", "been", "will", "would", "could",
    "which", "what", "where", "who", "how", "some", "all", "one", "two",
    "him", "her", "his", "she", "was", "were", "had", "has", "may", "also",
    "even", "only", "than", "more", "very", "too", "out", "back",
    "being", "said", "still", "again", "most", "other", "into", "over",
    "after", "before", "about", "just", "your", "our", "and", "but", "not",
    "any", "new", "see", "its", "for", "are",
    "reincarnated", "slime",
    }
}


@dataclass
class _CandidateStats:
    occurrences: int = 0
    speech_hits: int = 0
    action_hits: int = 0
    title_hits: int = 0
    sentence_start_hits: int = 0
    genitive_hits: int = 0          # aparece tras "de/del" → señal de lugar/org
    first_index: int = field(default_factory=lambda: 10**9)


def extract_character_mentions(
    source_text: str,
    translated_text: str,
    max_characters: int = 6,
    existing_characters: Optional[dict[str, str]] = None,
) -> dict[str, str]:
    """
    Detecta personajes con evidencia contextual para evitar ruido:
    no basta con estar en mayúscula al inicio de frase.

    Filtros adicionales:
    - Palabras en _NON_CHARACTER_WORDS (grupos, números, ruido)
    - Genitivo puro: nombre que aparece SOLO después de "de/del" sin ningún
      contexto directo de personaje → probable lugar u organización.
    """
    combined = f"{source_text or ''}\n{translated_text or ''}".strip()
    if not combined:
        return {}

    known = existing_characters or {}
    known_by_norm = {_normalize(name): name for name in known}

    stats_by_norm: dict[str, _CandidateStats] = {}
    display_by_norm: dict[str, str] = {}

    for match in _NAME_RE.finditer(combined):
        raw_name = match.group(0)
        norm = _normalize(raw_name)

        stats = stats_by_norm.setdefault(norm, _CandidateStats())
        stats.occurrences += 1
        stats.first_index = min(stats.first_index, match.start())

        if _is_sentence_start(combined, match.start()):
            stats.sentence_start_hits += 1
        if _has_speech_context(combined, raw_name, match.start(), match.end()):
            stats.speech_hits += 1
        if _has_action_context(combined, raw_name, match.start(), match.end()):
            stats.action_hits += 1
        if _has_title_context(combined, match.start()):
            stats.title_hits += 1
        if _has_genitive_context(combined, match.start()):
            stats.genitive_hits += 1

        # Conserva variante canónica del nombre.
        if norm in known_by_norm:
            display_by_norm[norm] = known_by_norm[norm]
        else:
            display_by_norm.setdefault(norm, raw_name)

    ranked: list[tuple[int, int, int, str]] = []
    for norm, stats in stats_by_norm.items():
        display = display_by_norm[norm]

        if norm in known_by_norm:
            score = 100 + stats.occurrences
            ranked.append((score, stats.occurrences, -stats.first_index, display))
            continue

        if norm in _NON_CHARACTER_WORDS:
            continue
        if norm in _SPEECH_VERBS_NORMALIZED or norm in _ACTION_VERBS_NORMALIZED:
            continue

        has_direct_context = (
            stats.speech_hits > 0
            or stats.action_hits > 0
            or stats.title_hits > 0
        )

        # Filtro genitivo: si el nombre aparece ÚNICAMENTE después de "de/del"
        # y no tiene ningún contexto directo de personaje, es probablemente
        # un lugar, organización o título colectivo ("de Tempest", "del Reino").
        if not has_direct_context and stats.genitive_hits >= stats.occurrences:
            continue

        score = _score_candidate(stats)
        repeated_with_body_context = (
            stats.occurrences >= 2 and stats.sentence_start_hits < stats.occurrences
        )

        if score >= 2 and (has_direct_context or repeated_with_body_context):
            ranked.append((score, stats.occurrences, -stats.first_index, display))

    ranked.sort(reverse=True)

    selected: dict[str, str] = {}
    for _, _, _, name in ranked:
        if name not in selected:
            selected[name] = "personaje mencionado en esta escena"
        if len(selected) >= max_characters:
            break

    return selected


def _score_candidate(stats: _CandidateStats) -> int:
    score = min(stats.occurrences, 3)
    score += stats.speech_hits * 3
    score += stats.action_hits * 3
    score += stats.title_hits * 2

    if stats.occurrences == stats.sentence_start_hits:
        score -= 2
    return score


def _normalize(value: str) -> str:
    return _normalize_static(value)


def _is_sentence_start(text: str, index: int) -> bool:
    i = index - 1
    while i >= 0 and text[i].isspace():
        i -= 1
    return i < 0 or text[i] in ".!?\n"


def _has_speech_context(text: str, name: str, start: int, end: int) -> bool:
    before = text[max(0, start - 42):start]
    after = text[end:end + 42]
    speech_re = "|".join(re.escape(v) for v in _SPEECH_VERBS)
    return bool(
        re.search(rf"\b(?:{speech_re})\s+{re.escape(name)}\b", before, flags=re.IGNORECASE)
        or re.search(rf"^\s+(?:{speech_re})\b", after, flags=re.IGNORECASE)
    )


def _has_action_context(text: str, name: str, start: int, end: int) -> bool:
    after = text[end:end + 24]
    action_re = "|".join(re.escape(v) for v in _ACTION_VERBS)
    return bool(re.search(rf"^\s+(?:{action_re})\b", after, flags=re.IGNORECASE))


def _has_title_context(text: str, start: int) -> bool:
    before = text[max(0, start - 20):start]
    tokens = re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]+", before)
    if not tokens:
        return False
    return _normalize(tokens[-1]) in _TITLE_HINTS_NORMALIZED


def _has_genitive_context(text: str, start: int) -> bool:
    """
    Detecta si el nombre aparece inmediatamente después de una preposición
    genitiva ("de" / "del"). Esta combinación es señal de lugar u organización
    ("ejecutivos de Tempest", "rey del Norte") más que de personaje individual.

    Se busca hacia atrás ignorando espacios para encontrar el último token.
    """
    before = text[max(0, start - 25):start]
    tokens = re.findall(r"[A-Za-záéíóúñÁÉÍÓÚÑ]+", before)
    if not tokens:
        return False
    return _normalize(tokens[-1]) in _GENITIVE_PREPOSITIONS
