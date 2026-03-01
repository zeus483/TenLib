# context/extractor.py
import json
import logging
import re
from typing import Optional, Protocol

from tenlib.context.bible import BibleUpdate

logger = logging.getLogger(__name__)

# Cada cuántos chunks se extrae aunque el modelo no reporte nada nuevo
_EXTRACT_EVERY_N = 5

_EXTRACTION_PROMPT = """\
Analiza el fragmento original y su traducción. Extrae únicamente información nueva \
que deba recordarse para mantener consistencia en el resto del libro.

FRAGMENTO ORIGINAL:
{original}

TRADUCCIÓN:
{translation}

NOTAS DEL TRADUCTOR:
{notes}

{candidates_section}\
Extrae:
0. Voz narrativa: persona gramatical (primera/tercera), tiempo verbal (pasado/presente) \
y rasgo principal del narrador (ej. "íntima y reflexiva", "épica y descriptiva", \
"irónica y distante"). Ejemplo: "narrador en primera persona, tiempo pasado, \
tono íntimo y contemplativo".
1. Glosario de términos del universo ficcional: habilidades, técnicas, razas, objetos \
especiales, títulos únicos y nombres de lugares que aparecen en este fragmento. \
Incluye TODO término relevante con su traducción establecida, incluso los que se decidió \
mantener sin traducir (ej. "Void" → "Void"). \
Ejemplo: {{"Pseudo-Dragon Body": "[Cuerpo de Pseudo-Dragón]", "Void": "Void", \
"Heart Core": "[Núcleo del Corazón]", "Eternal Twilight": "Eternal Twilight"}}.
2. Personajes: solo individuos con nombre propio (personas, criaturas, entidades únicas) \
que actúan, hablan o tienen relevancia narrativa. \
NO incluyas lugares, reinos, organizaciones, grupos ni títulos colectivos. \
Para cada personaje incluye género (M/F/N), rol narrativo, estilo de habla y personalidad. \
Formato: "Género: M | Rol: protagonista | Habla: directo y amigable | Personalidad: optimista, decidido"
3. Decisiones de estilo puras (máximo 3): convenciones que NO son términos del glosario. \
Solo lo concreto: tratamiento del diálogo, uso de tuteo/ustedeo, estructuras gramaticales \
especiales. NO incluyas: términos técnicos (van en glossary), observaciones genéricas \
sobre voz o tono ("se mantiene la voz", "se preserva el tono"), frases sin acción futura \
clara. Ejemplo válido: "usar tuteo consistente en diálogos entre protagonistas".
4. Resumen en 2 frases de qué ocurrió en esta escena (para continuidad).

Responde ÚNICAMENTE con JSON válido:
{{
  "voice": "persona, tiempo verbal y rasgo principal del narrador",
  "glossary": {{"término_original": "término_traducido"}},
  "characters": {{"nombre": "Género: M/F/N | Rol: ... | Habla: ... | Personalidad: ..."}},
  "rejected": ["nombre_que_no_es_personaje"],
  "decisions": ["decisión concreta que debe mantenerse"],
  "last_scene": "resumen de 2 frases de la escena"
}}

Si no hay nada nuevo en alguna categoría, devuelve un objeto/lista vacío.
No inventes términos que no aparezcan en el fragmento.
"""

# Sección de candidatos que se inyecta cuando el detector local aportó nombres.
# La IA valida cuáles son personajes reales y enriquece sus descripciones.
_CANDIDATES_SECTION = """\
CANDIDATOS DE PERSONAJES DETECTADOS AUTOMÁTICAMENTE:
{candidates_list}

Para la sección "characters": revisa cada candidato de la lista anterior.
- Si es un individuo real (personaje que actúa, habla o tiene relevancia narrativa): \
inclúyelo con el formato "Género: M/F/N | Rol: ... | Habla: ... | Personalidad: ..."
- Si es un lugar, organización, grupo, título colectivo, palabra común del inglés \
(That, The, Time, Got, Dragon, Lord...) o sustantivo común del español (Página, Regreso, \
Estrella...): NO lo incluyas en "characters". Ponlo en "rejected".
Además, añade cualquier personaje nuevo que encuentres en el fragmento y no esté listado.

"""

# Captura JSON en bloque markdown. Usa {.*} greedy para soportar JSON anidado.
# (glossary y characters son dicts → el non-greedy {.*?} rompía con ellos)
_MARKDOWN_JSON_RE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)
_BARE_JSON_RE     = re.compile(r"\{.*\}", re.DOTALL)


class TranslationModel(Protocol):
    """
    Interfaz mínima que el Extractor necesita del modelo.
    Desacoplado del Router — solo necesita poder hacer una llamada.
    """
    def translate(self, chunk: str, system_prompt: str): ...


class BibleExtractor:
    """
    Responsabilidad única: dada una traducción, devolver un BibleUpdate
    con los nuevos términos, personajes y decisiones detectadas.

    Cuando se proveen character_candidates (detectados por el detector local),
    el AI los valida: confirma los que son personajes reales, descarta los que
    son lugares/organizaciones/grupos, y añade los suyos propios.

    No modifica la Bible — solo devuelve qué cambiaría.
    La decisión de aplicar el update la toma el Orchestrator.
    """

    def __init__(self, model: TranslationModel, extract_every_n: int = _EXTRACT_EVERY_N):
        self._model           = model
        self._extract_every_n = extract_every_n
        self._chunks_since_last_extract = 0

    def should_extract(self, chunk_index: int, notes: str, force: bool = False) -> bool:
        """
        Decide si vale la pena extraer en este chunk.
        Extrae siempre si:
        - Es el primer chunk (chunk_index == 0)
        - force=True (candidatos nuevos detectados localmente)
        - El modelo reportó términos nuevos en sus notas
        - Han pasado N chunks desde la última extracción
        """
        if chunk_index == 0:
            return True

        if force:
            return True

        notes_lower = notes.lower()
        model_found_something = any(
            keyword in notes_lower
            for keyword in [
                "nuevo", "new", "término", "term",
                "personaje", "character", "nombre", "name",
                "decisión", "decision",
            ]
        )
        if model_found_something:
            return True

        self._chunks_since_last_extract += 1
        if self._chunks_since_last_extract >= self._extract_every_n:
            return True

        return False

    def extract(
        self,
        original:             str,
        translation:          str,
        notes:                str,
        chunk_index:          int,
        character_candidates: Optional[dict[str, str]] = None,
        force:                bool                     = False,
    ) -> Optional[BibleUpdate]:
        """
        Extrae nuevos términos y decisiones del chunk traducido.

        Si se pasan character_candidates, el prompt incluye esa lista para
        que la IA valide cuáles son personajes reales y enriquezca sus
        descripciones, descartando los que son lugares/organizaciones.

        force=True salta la lógica de should_extract y extrae siempre.
        Úsarlo cuando hay candidatos nuevos que deben enriquecerse en este chunk.

        Devuelve None si decide no extraer en este chunk.
        Nunca lanza excepción — falla silenciosamente y loguea.
        """
        if not self.should_extract(chunk_index, notes, force=force):
            return None

        candidates_section = _build_candidates_section(character_candidates)

        prompt = _EXTRACTION_PROMPT.format(
            original           = original,
            translation        = translation,
            notes              = notes or "Sin notas.",
            candidates_section = candidates_section,
        )

        try:
            response = self._model.translate(prompt, system_prompt="")
            raw_text = response.translation  # el extractor reutiliza ModelResponse
            self._chunks_since_last_extract = 0
            return self._parse_update(raw_text)

        except Exception as e:
            logger.warning(
                "Extractor falló en chunk %d: %s — Bible sin cambios",
                chunk_index, e,
            )
            return None

    def _parse_update(self, raw_text: str) -> BibleUpdate:
        """
        Parsea la respuesta del modelo con la misma estrategia de degradación
        que el response_parser del router.
        """
        data = self._try_parse_json(raw_text.strip())

        if not data:
            logger.warning("Extractor: respuesta no parseable — Bible sin cambios")
            return BibleUpdate()

        return BibleUpdate(
            voice      = str(data.get("voice") or "").strip() or None,
            glossary   = self._safe_dict(data.get("glossary")),
            characters = self._safe_dict(data.get("characters")),
            decisions  = self._safe_list(data.get("decisions")),
            last_scene = str(data.get("last_scene") or "").strip() or None,
            rejected   = self._safe_list(data.get("rejected")),
        )

    @staticmethod
    def _try_parse_json(text: str) -> Optional[dict]:
        # Intento 1: JSON directo
        try:
            result = json.loads(text)
            if isinstance(result, dict):
                return result
        except (json.JSONDecodeError, ValueError):
            pass

        # Intento 2: dentro de bloque markdown
        match = _MARKDOWN_JSON_RE.search(text)
        if match:
            try:
                result = json.loads(match.group(1))
                if isinstance(result, dict):
                    return result
            except (json.JSONDecodeError, ValueError):
                pass

        # Intento 3: primer objeto JSON en el texto
        match = _BARE_JSON_RE.search(text)
        if match:
            try:
                result = json.loads(match.group(0))
                if isinstance(result, dict):
                    return result
            except (json.JSONDecodeError, ValueError):
                pass

        return None

    @staticmethod
    def _safe_dict(value) -> dict[str, str]:
        if not isinstance(value, dict):
            return {}
        return {str(k): str(v) for k, v in value.items() if k and v}

    @staticmethod
    def _safe_list(value) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if item]


def _build_candidates_section(candidates: Optional[dict[str, str]]) -> str:
    """
    Construye la sección de candidatos para el prompt de extracción.
    Devuelve cadena vacía si no hay candidatos.
    """
    if not candidates:
        return ""
    candidates_list = "\n".join(f"  - {name}" for name in candidates)
    return _CANDIDATES_SECTION.format(candidates_list=candidates_list)
