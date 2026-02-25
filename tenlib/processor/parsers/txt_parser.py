import os
import re
from tenlib.processor.models import RawBook
from .base import BaseParser

# Patrones que indican el inicio de un nuevo capítulo en texto plano.
# Orden de prioridad: el primero que haga match en una línea gana.
_CHAPTER_PATTERNS: list[re.Pattern] = [
    re.compile(r'^\s*(chapter|capítulo|capítulo|chapitre|kapitel)\s+[\divxlc]+', re.IGNORECASE),
    re.compile(r'^\s*(chapter|capítulo)\s+\w+', re.IGNORECASE),  # "Chapter One"
    re.compile(r'^\s*[\divxlc]{1,6}[\.\-\)]\s', re.IGNORECASE),  # "IV. ", "3. ", "ii) "
    re.compile(r'^\s*\*{3,}\s*$'),   # separador *** (escena)
    re.compile(r'^\s*-{3,}\s*$'),    # separador --- (escena)
    re.compile(r'^\s*#{1,3}\s+\w'),  # Markdown headings # ## ###
]

_SUPPORTED_EXTENSIONS = {'.txt', '.md'}


class TxtParser(BaseParser):
    """
    Parser para archivos .txt y .md.

    Estrategia de sección:
      1. Si el texto tiene marcadores de capítulo reconocibles → split por capítulos.
      2. Si no → split por bloques separados por línea(s) en blanco.
         Bloques muy pequeños (<40 palabras) se fusionan con el siguiente.

    El título se extrae, en orden de prioridad:
      - Primera línea si parece un título (≤10 palabras, sin punto final)
      - Nombre del archivo sin extensión
    """

    def can_handle(self, file_path: str) -> bool:
        _, ext = os.path.splitext(file_path)
        return ext.lower() in _SUPPORTED_EXTENSIONS

    def parse(self, file_path: str) -> RawBook:
        raw = self._read_file(file_path)
        title = self._extract_title(raw, file_path)
        sections = self._split_sections(raw)

        return RawBook(
            title=title,
            source_path=file_path,
            sections=sections,
            detected_language=None,  # detección de idioma: responsabilidad del Orchestrator
        )

    # ------------------------------------------------------------------ #
    #  Helpers privados                                                    #
    # ------------------------------------------------------------------ #

    def _read_file(self, file_path: str) -> str:
        """Lee el archivo intentando UTF-8 primero, latin-1 como fallback."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except UnicodeDecodeError:
            with open(file_path, 'r', encoding='latin-1') as f:
                return f.read()

    def _extract_title(self, text: str, file_path: str) -> str:
        first_line = text.strip().split('\n')[0].strip().lstrip('#').strip()
        words = first_line.split()
        if words and len(words) <= 10 and not first_line.endswith('.'):
            return first_line
        return os.path.splitext(os.path.basename(file_path))[0]

    def _split_sections(self, text: str) -> list[str]:
        if self._has_chapter_markers(text):
            return self._split_by_chapters(text)
        return self._split_by_paragraphs(text)

    def _has_chapter_markers(self, text: str) -> bool:
        """Devuelve True si al menos 2 líneas hacen match con patrones de capítulo."""
        matches = 0
        for line in text.split('\n'):
            if any(p.match(line) for p in _CHAPTER_PATTERNS):
                matches += 1
                if matches >= 2:
                    return True
        return False

    def _split_by_chapters(self, text: str) -> list[str]:
        """
        Divide el texto en capítulos usando los patrones detectados.
        La línea que marca el capítulo se incluye al inicio de su sección.
        """
        lines = text.split('\n')
        sections: list[str] = []
        current_lines: list[str] = []

        for line in lines:
            is_boundary = any(p.match(line) for p in _CHAPTER_PATTERNS)
            if is_boundary and current_lines:
                section = '\n'.join(current_lines).strip()
                if section:
                    sections.append(section)
                current_lines = [line]
            else:
                current_lines.append(line)

        # último capítulo
        if current_lines:
            section = '\n'.join(current_lines).strip()
            if section:
                sections.append(section)

        return sections if sections else [text.strip()]

    def _split_by_paragraphs(self, text: str) -> list[str]:
        """
        Fallback: divide por bloques separados por línea(s) en blanco.
        Fusiona bloques demasiado pequeños (<40 palabras) con el siguiente.
        """
        raw_blocks = re.split(r'\n{2,}', text)
        blocks = [b.strip() for b in raw_blocks if b.strip()]

        merged: list[str] = []
        buffer = ''

        for block in blocks:
            buffer = (buffer + '\n\n' + block).strip() if buffer else block
            if len(buffer.split()) >= 40:
                merged.append(buffer)
                buffer = ''

        if buffer:  # último bloque aunque sea pequeño
            if merged:
                merged[-1] += '\n\n' + buffer  # fusionar con el anterior
            else:
                merged.append(buffer)

        return merged if merged else [text.strip()]