# context/compressor.py
from tenlib.context.bible import BookBible

_MAX_DECISIONS_IN_PROMPT = 8
_MAX_LAST_SCENE_IN_PROMPT = 320


class BibleCompressor:
    """
    Responsabilidad única: dado un chunk de texto, devolver una copia
    de la Bible con solo la información relevante para ese fragmento.

    No modifica la Bible original — siempre devuelve una nueva instancia.
    """

    def compress(self, bible: BookBible, chunk_text: str) -> BookBible:
        """
        Filtra glosario y personajes a los que aparecen en el chunk.
        Decisions y last_scene se recortan para mantener presupuesto de tokens.

        En libros con elencos grandes reduce hasta 40% los tokens por llamada.
        """
        if bible.is_empty():
            return BookBible(
                voice      = bible.voice,
                decisions  = _select_recent_decisions(bible.decisions),
                glossary   = {},
                characters = {},
                last_scene = _truncate_scene(bible.last_scene),
            )

        chunk_lower = chunk_text.lower()

        relevant_glossary = {
            term: translation
            for term, translation in bible.glossary.items()
            if term.lower() in chunk_lower
        }

        relevant_characters = {
            name: description
            for name, description in bible.characters.items()
            if name.lower() in chunk_lower
        }

        return BookBible(
            voice      = bible.voice,
            decisions  = _select_recent_decisions(bible.decisions),
            glossary   = relevant_glossary,
            characters = relevant_characters,
            last_scene = _truncate_scene(bible.last_scene),
        )

    def compression_ratio(self, original: BookBible, compressed: BookBible) -> float:
        """
        Métrica de cuánto se redujo la Bible.
        Útil para logging y para detectar si el compressor está siendo efectivo.
        """
        original_entries  = len(original.glossary) + len(original.characters)
        compressed_entries = len(compressed.glossary) + len(compressed.characters)

        if original_entries == 0:
            return 1.0

        return compressed_entries / original_entries


def _select_recent_decisions(decisions: list[str]) -> list[str]:
    if len(decisions) <= _MAX_DECISIONS_IN_PROMPT:
        return decisions
    return decisions[-_MAX_DECISIONS_IN_PROMPT:]


def _truncate_scene(scene: str) -> str:
    clean = " ".join((scene or "").split()).strip()
    if len(clean) <= _MAX_LAST_SCENE_IN_PROMPT:
        return clean
    return clean[: _MAX_LAST_SCENE_IN_PROMPT - 1].rstrip() + "…"
