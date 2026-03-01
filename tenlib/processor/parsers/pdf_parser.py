# tenlib/processor/parsers/pdf_parser.py
import os
import re
from tenlib.processor.models import RawBook
from .base import BaseParser

_CHAPTER_RE = re.compile(
    r'^\s*(cap[ií]tulo|chapter|parte|part|prologue|pr[oó]logo)\s*[\divxlc]*',
    re.IGNORECASE,
)
_MIN_SECTION_WORDS = 40


class PdfParser(BaseParser):
    """
    Parser para archivos .pdf.

    Extrae el texto de cada página usando PyMuPDF (fitz).
    Agrupa páginas en secciones detectando encabezados de capítulo.
    Si no hay capítulos, cada página es una sección.

    Requiere: pip install pymupdf
    """

    def can_handle(self, file_path: str) -> bool:
        return file_path.lower().endswith(".pdf")

    def parse(self, file_path: str) -> RawBook:
        try:
            import fitz  # pymupdf
        except ImportError:
            raise ImportError(
                "El soporte PDF requiere pymupdf. Instálalo con: pip install pymupdf"
            )

        doc   = fitz.open(file_path)
        pages = [page.get_text("text").strip() for page in doc]
        doc.close()

        # Filtrar páginas vacías o casi vacías (portada, índice con solo números)
        pages = [p for p in pages if len(p.split()) >= 5]

        title    = self._extract_title(pages, file_path)
        sections = self._group_sections(pages)

        return RawBook(
            title            = title,
            source_path      = file_path,
            sections         = sections,
            detected_language = None,
        )

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _extract_title(self, pages: list[str], file_path: str) -> str:
        """Usa la primera línea no vacía de la primera página, o el nombre del archivo."""
        if pages:
            first_line = pages[0].split("\n")[0].strip()
            words = first_line.split()
            if words and len(words) <= 12 and not first_line.endswith("."):
                return first_line
        return os.path.splitext(os.path.basename(file_path))[0]

    def _group_sections(self, pages: list[str]) -> list[str]:
        """
        Agrupa páginas en secciones semánticas.
        Si detecta al menos 2 marcadores de capítulo → split por capítulos.
        En caso contrario → cada página es una sección.
        """
        if self._has_chapter_markers(pages):
            return self._split_by_chapters(pages)
        return self._merge_short_pages(pages)

    def _has_chapter_markers(self, pages: list[str]) -> bool:
        matches = sum(
            1 for p in pages
            if any(_CHAPTER_RE.match(line) for line in p.split("\n"))
        )
        return matches >= 2

    def _split_by_chapters(self, pages: list[str]) -> list[str]:
        sections: list[str] = []
        current: list[str] = []

        for page in pages:
            first_line = page.split("\n")[0].strip()
            is_chapter = bool(_CHAPTER_RE.match(first_line))
            if is_chapter and current:
                section = "\n\n".join(current).strip()
                if section:
                    sections.append(section)
                current = [page]
            else:
                current.append(page)

        if current:
            section = "\n\n".join(current).strip()
            if section:
                sections.append(section)

        return sections if sections else ["\n\n".join(pages)]

    def _merge_short_pages(self, pages: list[str]) -> list[str]:
        """Fusiona páginas muy cortas con la siguiente para evitar chunks demasiado pequeños."""
        sections: list[str] = []
        buffer = ""

        for page in pages:
            buffer = (buffer + "\n\n" + page).strip() if buffer else page
            if len(buffer.split()) >= _MIN_SECTION_WORDS:
                sections.append(buffer)
                buffer = ""

        if buffer:
            if sections:
                sections[-1] += "\n\n" + buffer
            else:
                sections.append(buffer)

        return sections if sections else pages
