# context/bible.py
import json
import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Optional


@dataclass
class BibleUpdate:
    """
    Lo que devuelve el Extractor después de procesar un chunk.
    Solo contiene lo nuevo — no la Bible completa.

    rejected: nombres que la IA confirmó que NO son personajes (lugares, organizaciones,
              títulos colectivos). Se eliminan de la Bible si ya estaban presentes.
    """
    voice:      Optional[str]  = None
    glossary:   dict[str, str] = field(default_factory=dict)
    characters: dict[str, str] = field(default_factory=dict)
    decisions:  list[str]      = field(default_factory=list)
    last_scene: Optional[str]  = None
    rejected:   list[str]      = field(default_factory=list)


@dataclass
class BookBible:
    """
    Memoria editorial persistente del libro.
    Empieza vacía y se construye sola chunk a chunk.
    Se serializa a JSON para vivir en SQLite.
    """
    voice:      str            = "narrador en tercera persona, tiempo pasado"
    decisions:  list[str]      = field(default_factory=list)
    glossary:   dict[str, str] = field(default_factory=dict)
    characters: dict[str, str] = field(default_factory=dict)
    last_scene: str            = "Inicio del libro — no hay contexto previo."

    # ------------------------------------------------------------------
    # Mutación
    # ------------------------------------------------------------------

    def apply(self, update: BibleUpdate) -> None:
        """
        Incorpora un BibleUpdate a la Bible actual.
        Merge no destructivo: los valores existentes no se sobreescriben
        salvo last_scene, que siempre refleja el chunk más reciente.
        """
        # Voz narrativa (si llega una actualización explícita)
        if update.voice and update.voice.strip():
            self.voice = update.voice.strip()

        # Rechazados: eliminar de la Bible los nombres que la IA descartó
        for name in update.rejected:
            self.characters.pop(name, None)

        # Nuevas entradas del glosario (no sobreescribir las existentes)
        for term, translation in update.glossary.items():
            if term not in self.glossary and len(self.glossary) < _MAX_GLOSSARY_ENTRIES:
                self.glossary[term] = translation

        # Personajes: agregar nuevos o actualizar si la descripción actual es genérica.
        # Permite que el AI extractor enriquezca entradas que el detector local
        # añadió con la descripción placeholder "personaje mencionado en esta escena".
        for name, description in update.characters.items():
            if not _is_valid_character_name(name):
                continue
            if name not in self.characters:
                if len(self.characters) < _MAX_CHARACTER_ENTRIES:
                    self.characters[name] = description
            elif (
                self.characters[name] == _GENERIC_CHARACTER_DESCRIPTION
                and description != _GENERIC_CHARACTER_DESCRIPTION
                and description.strip()
            ):
                # El AI aportó descripción real: actualizar la genérica
                self.characters[name] = description

        # Decisiones nuevas (evitar duplicados)
        for decision in update.decisions:
            cleaned = _clean_decision(decision)
            if not cleaned:
                continue
            if _is_new_decision(cleaned, self.decisions):
                self.decisions.append(cleaned)

        if len(self.decisions) > _MAX_DECISIONS_ENTRIES:
            self.decisions = self.decisions[-_MAX_DECISIONS_ENTRIES:]

        # last_scene siempre se actualiza
        if update.last_scene:
            self.last_scene = _truncate_text(update.last_scene, _MAX_LAST_SCENE_CHARS)

    def is_empty(self) -> bool:
        return (
            not self.glossary
            and not self.characters
            and not self.decisions
        )

    # ------------------------------------------------------------------
    # Serialización
    # ------------------------------------------------------------------

    def to_json(self) -> str:
        return json.dumps({
            "voice":      self.voice,
            "decisions":  self.decisions,
            "glossary":   self.glossary,
            "characters": self.characters,
            "last_scene": self.last_scene,
        }, ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, raw: str) -> "BookBible":
        data = json.loads(raw)
        return cls(
            voice      = data.get("voice", cls.voice),
            decisions  = data.get("decisions", []),
            glossary   = data.get("glossary", {}),
            characters = data.get("characters", {}),
            last_scene = data.get("last_scene", cls.last_scene),
        )

    @classmethod
    def empty(cls) -> "BookBible":
        """Bible inicial para un libro nuevo."""
        return cls()


_MAX_GLOSSARY_ENTRIES = 600
_MAX_CHARACTER_ENTRIES = 240
_MAX_DECISIONS_ENTRIES = 18
_MAX_LAST_SCENE_CHARS = 420
_MAX_DECISION_CHARS = 220

# Descripción que asigna el detector local cuando no tiene información real.
# Si el AI extractor luego aporta una descripción concreta, se permite actualizar.
_GENERIC_CHARACTER_DESCRIPTION = "personaje mencionado en esta escena"

_NON_CHARACTER_SINGLE_WORDS = {
    "el", "la", "los", "las",
    "un", "una", "unos", "unas",
    "yo", "tu", "tú", "mi", "mis", "me",
    "nos", "nosotros", "nosotras",
    "ella", "ellas", "ello", "ellos",
    "eso", "esto", "esa", "ese", "esas", "esos",
    "aqui", "aquí", "alli", "allí",
    "antes", "despues", "después",
    "estaba", "estaban", "era", "eran", "fue", "fueron", "es", "son",
    "texto", "original", "chunk", "capitulo", "capítulo",
}


def _normalize_token(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return normalized.lower().strip()


def _is_valid_character_name(name: str) -> bool:
    candidate = (name or "").strip()
    if len(candidate) < 2 or len(candidate) > 80:
        return False

    if not re.fullmatch(r"[A-Za-zÁÉÍÓÚÑáéíóúñ' -]+", candidate):
        return False

    tokens = [t for t in re.split(r"\s+", candidate) if t]
    if not tokens:
        return False

    # Si llega un único token, filtramos solo ruido evidente.
    normalized_tokens = [_normalize_token(t) for t in tokens]
    if len(normalized_tokens) == 1 and normalized_tokens[0] in _NON_CHARACTER_SINGLE_WORDS:
        return False

    # Al menos una palabra debe verse como nombre propio.
    has_proper_like = any(token[0].isupper() for token in tokens if token)
    return has_proper_like


def _truncate_text(text: str, max_chars: int) -> str:
    cleaned = " ".join((text or "").split()).strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 1].rstrip() + "…"


def _clean_decision(decision: str) -> str:
    cleaned = " ".join((decision or "").split()).strip()
    if not cleaned:
        return ""
    return _truncate_text(cleaned, _MAX_DECISION_CHARS)


def _normalize_decision(decision: str) -> str:
    text = (decision or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^\wáéíóúñü ]+", "", text)
    return text


def _is_new_decision(candidate: str, existing: list[str]) -> bool:
    normalized = _normalize_decision(candidate)
    if not normalized:
        return False

    for current in existing:
        curr_norm = _normalize_decision(current)
        if normalized == curr_norm:
            return False
        if SequenceMatcher(None, normalized, curr_norm).ratio() >= 0.84:
            return False
    return True
