import os
import re
from tenlib.processor.models import RawBook
from .base import BaseParser

_SUPPORTED_EXTENSIONS = {'.epub'}


class EpubParser(BaseParser):
    """
    Parser para archivos .epub.

    Estrategia de sección:
      - Cada ítem del spine del EPUB = una sección (así lo estructura el autor).
      - Se limpia el HTML de cada ítem dejando solo texto plano.
      - Ítems con menos de 50 palabras (portadas, páginas de copyright,
        índices) se descartan silenciosamente.

    Dependencia: ebooklib  →  pip install ebooklib
    La importación es lazy para no romper el resto del sistema si no está
    instalada y el usuario solo trabaja con TXT.
    """

    def can_handle(self, file_path: str) -> bool:
        _, ext = os.path.splitext(file_path)
        return ext.lower() in _SUPPORTED_EXTENSIONS

    def parse(self, file_path: str) -> RawBook:
        try:
            import ebooklib
            from ebooklib import epub
        except ImportError:
            raise ImportError(
                "ebooklib no está instalado. "
                "Ejecuta: pip install ebooklib"
            )

        book = epub.read_epub(file_path, options={'ignore_ncx': True})

        title = self._extract_title(book, file_path)
        sections = self._extract_sections(book)

        return RawBook(
            title=title,
            source_path=file_path,
            sections=sections,
            detected_language=self._extract_language(book),
        )

    # ------------------------------------------------------------------ #
    #  Helpers privados                                                    #
    # ------------------------------------------------------------------ #

    def _extract_title(self, book, file_path: str) -> str:
        try:
            import ebooklib
            titles = book.get_metadata('DC', 'title')
            if titles:
                return str(titles[0][0]).strip()
        except Exception:
            pass
        return os.path.splitext(os.path.basename(file_path))[0]

    def _extract_language(self, book) -> str | None:
        try:
            langs = book.get_metadata('DC', 'language')
            if langs:
                return str(langs[0][0]).strip().lower()
        except Exception:
            pass
        return None

    def _extract_sections(self, book) -> list[str]:
        import ebooklib
        from ebooklib import epub

        sections: list[str] = []

        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            text = self._html_to_text(item.get_content())
            text = text.strip()

            # descartar páginas de relleno (portadas, copyright, índices vacíos)
            if len(text.split()) < 50:
                continue

            sections.append(text)

        return sections if sections else []

    def _html_to_text(self, html_bytes: bytes) -> str:
        """
        Convierte HTML de un capítulo EPUB a texto plano limpio.

        Estrategia deliberadamente simple — sin BeautifulSoup para minimizar
        dependencias en el MVP. Suficiente para el 95% de EPUBs bien formados.
        """
        try:
            html = html_bytes.decode('utf-8')
        except UnicodeDecodeError:
            html = html_bytes.decode('latin-1')

        # Convertir etiquetas de bloque en saltos de línea antes de limpiar
        block_tags = re.compile(
            r'<(p|br|div|h[1-6]|li|tr|blockquote)[^>]*>',
            re.IGNORECASE
        )
        html = block_tags.sub('\n', html)

        # Eliminar todas las etiquetas restantes
        html = re.sub(r'<[^>]+>', '', html)

        # Decodificar entidades HTML básicas
        html = (html
                .replace('&amp;', '&')
                .replace('&lt;', '<')
                .replace('&gt;', '>')
                .replace('&quot;', '"')
                .replace('&#39;', "'")
                .replace('&nbsp;', ' ')
                .replace('&mdash;', '—')
                .replace('&ndash;', '–')
                .replace('&hellip;', '…'))

        # Normalizar espacios y saltos de línea excesivos
        html = re.sub(r'[ \t]+', ' ', html)
        html = re.sub(r'\n{3,}', '\n\n', html)

        return html.strip()