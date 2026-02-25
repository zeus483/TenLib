"""
Tests para el módulo de parsers.

Ejecutar:
    pytest tests/processor/parsers/ -v

Estructura:
    test_txt_parser.py   → TxtParser
    test_epub_parser.py  → EpubParser (con mock de ebooklib)
    test_factory.py      → ParserFactory

Este archivo agrupa los tres para simplicidad en el MVP.
Separarlos en archivos individuales es trivial si el suite crece.
"""

import os
import pytest
from unittest.mock import MagicMock, patch, mock_open
from tenlib.processor.models import RawBook


# ═══════════════════════════════════════════════════════════════════════════ #
#  TxtParser                                                                  #
# ═══════════════════════════════════════════════════════════════════════════ #

class TestTxtParser:
    """Tests unitarios e integración del parser de texto plano."""

    @pytest.fixture
    def parser(self):
        from tenlib.processor.parsers.txt_parser import TxtParser
        return TxtParser()

    # --- can_handle ---

    def test_handles_txt(self, parser):
        assert parser.can_handle("libro.txt") is True

    def test_handles_md(self, parser):
        assert parser.can_handle("notas.md") is True

    def test_rejects_epub(self, parser):
        assert parser.can_handle("libro.epub") is False

    def test_rejects_pdf(self, parser):
        assert parser.can_handle("libro.pdf") is False

    def test_case_insensitive_extension(self, parser):
        assert parser.can_handle("LIBRO.TXT") is True

    # --- extracción de título ---

    def test_title_from_first_line(self, parser, tmp_path):
        content = "El Nombre del Viento\n\nCapítulo 1\nHabía una vez..."
        f = tmp_path / "libro.txt"
        f.write_text(content, encoding='utf-8')
        book = parser.parse(str(f))
        assert book.title == "El Nombre del Viento"

    def test_title_fallback_to_filename(self, parser, tmp_path):
        # Primera línea larga → no es título
        content = "Esta es una línea muy larga que definitivamente no parece un título de libro.\n\nTexto..."
        f = tmp_path / "mi_libro_genial.txt"
        f.write_text(content, encoding='utf-8')
        book = parser.parse(str(f))
        assert book.title == "mi_libro_genial"

    def test_title_not_ending_with_period(self, parser, tmp_path):
        content = "Una frase completa que termina en punto.\n\nContenido del libro aquí presente para prueba."
        f = tmp_path / "libro.txt"
        f.write_text(content, encoding='utf-8')
        book = parser.parse(str(f))
        assert book.title == "libro"  # fallback al nombre de archivo

    # --- chunking con capítulos ---

    def test_splits_by_chapter_markers(self, parser, tmp_path):
        content = (
            "Mi Novela\n\n"
            "Chapter 1\nContenido del primer capítulo con suficiente texto para no ser descartado.\n\n"
            "Chapter 2\nContenido del segundo capítulo con suficiente texto para no ser descartado.\n\n"
            "Chapter 3\nContenido del tercer capítulo con suficiente texto para no ser descartado.\n"
        )
        f = tmp_path / "novela.txt"
        f.write_text(content, encoding='utf-8')
        book = parser.parse(str(f))
        # El parser genera una sección por cada bloque: pre-chapter ("Mi Novela") + 3 capítulos = 4
        assert len(book.sections) == 4

    def test_chapter_content_not_lost(self, parser, tmp_path):
        content = (
            "Chapter 1\nEste es el contenido importante del capítulo uno.\n\n"
            "Chapter 2\nEste es el contenido importante del capítulo dos.\n"
        )
        f = tmp_path / "libro.txt"
        f.write_text(content, encoding='utf-8')
        book = parser.parse(str(f))
        full = '\n'.join(book.sections)
        assert "contenido importante del capítulo uno" in full
        assert "contenido importante del capítulo dos" in full

    def test_splits_by_scene_separator(self, parser, tmp_path):
        # _has_chapter_markers requiere ≥ 2 líneas que hagan match para activar el modo capítulo.
        # Con dos separadores '***', ambas líneas hacen match y el split ocurre correctamente.
        content = (
            "Parte A del texto con suficiente contenido para que no sea descartado por ser muy corto.\n\n"
            "***\n\n"
            "Parte B del texto con suficiente contenido para que no sea descartado por ser muy corto.\n\n"
            "***\n\n"
            "Parte C del texto con suficiente contenido para que no sea descartado por ser muy corto.\n"
        )
        f = tmp_path / "escenas.txt"
        f.write_text(content, encoding='utf-8')
        book = parser.parse(str(f))
        assert len(book.sections) >= 2

    def test_fallback_paragraph_split(self, parser, tmp_path):
        """Sin marcadores de capítulo, debe dividir por párrafos y fusionar los pequeños."""
        paragraphs = [f"Párrafo {i}: " + "texto " * 20 for i in range(5)]
        content = "\n\n".join(paragraphs)
        f = tmp_path / "sin_capitulos.txt"
        f.write_text(content, encoding='utf-8')
        book = parser.parse(str(f))
        assert len(book.sections) >= 1
        # verificar 0% pérdida de contenido
        full_original = " ".join(paragraphs)
        full_parsed = " ".join(book.sections)
        for i in range(5):
            assert f"Párrafo {i}" in full_parsed

    def test_zero_content_loss(self, parser, tmp_path):
        """Garantía fundamental: toda palabra del original aparece en alguna sección."""
        content = "\n\n".join(["palabra_unica_" + str(i) + " " + "relleno " * 30 for i in range(10)])
        f = tmp_path / "libro.txt"
        f.write_text(content, encoding='utf-8')
        book = parser.parse(str(f))
        full_output = " ".join(book.sections)
        for i in range(10):
            assert f"palabra_unica_{i}" in full_output

    # --- raw book structure ---

    def test_returns_raw_book(self, parser, tmp_path):
        content = "Título\n\n" + "Contenido " * 50
        f = tmp_path / "libro.txt"
        f.write_text(content, encoding='utf-8')
        book = parser.parse(str(f))
        assert isinstance(book, RawBook)
        assert book.source_path == str(f)
        assert isinstance(book.sections, list)
        assert all(isinstance(s, str) for s in book.sections)

    def test_detected_language_is_none(self, parser, tmp_path):
        """TxtParser no detecta idioma — esa responsabilidad es del Orchestrator."""
        content = "Título\n\n" + "Contenido " * 50
        f = tmp_path / "libro.txt"
        f.write_text(content, encoding='utf-8')
        book = parser.parse(str(f))
        assert book.detected_language is None

    # --- encoding ---

    def test_reads_latin1_file(self, parser, tmp_path):
        content = "Título con ñ y acentos: café, niño\n\nContenido " * 20
        f = tmp_path / "latin.txt"
        f.write_bytes(content.encode('latin-1'))
        book = parser.parse(str(f))
        assert "café" in " ".join(book.sections)


# ═══════════════════════════════════════════════════════════════════════════ #
#  EpubParser                                                                 #
# ═══════════════════════════════════════════════════════════════════════════ #

class TestEpubParser:
    """Tests del parser EPUB usando mocks de ebooklib."""

    @pytest.fixture
    def parser(self):
        from tenlib.processor.parsers.epub_parser import EpubParser
        return EpubParser()

    def _make_mock_epub(self, title="Test Book", language="en", chapters=None):
        """Helper: construye un mock de ebooklib.epub.EpubBook."""
        if chapters is None:
            chapters = ["<p>Capítulo uno con bastante contenido para no ser descartado.</p>" * 5]

        mock_book = MagicMock()

        # metadata
        mock_book.get_metadata.side_effect = lambda ns, key: (
            [(title, {})] if key == 'title' else
            [(language, {})] if key == 'language' else
            []
        )

        # spine items
        mock_items = []
        for html_content in chapters:
            item = MagicMock()
            item.get_content.return_value = html_content.encode('utf-8')
            mock_items.append(item)

        mock_book.get_items_of_type.return_value = mock_items
        return mock_book

    # --- can_handle ---

    def test_handles_epub(self, parser):
        assert parser.can_handle("libro.epub") is True

    def test_rejects_txt(self, parser):
        assert parser.can_handle("libro.txt") is False

    def test_case_insensitive(self, parser):
        assert parser.can_handle("LIBRO.EPUB") is True

    # --- parseo con mock ---

    def test_extracts_title_from_metadata(self, parser, tmp_path):
        import ebooklib
        mock_epub_book = self._make_mock_epub(title="Cien años de soledad")
        dummy_file = tmp_path / "libro.epub"
        dummy_file.write_bytes(b"")

        with patch('ebooklib.epub.read_epub', return_value=mock_epub_book):
            book = parser.parse(str(dummy_file))

        assert book.title == "Cien años de soledad"

    def test_extracts_language_from_metadata(self, parser, tmp_path):
        import ebooklib
        mock_epub_book = self._make_mock_epub(language="es")
        dummy_file = tmp_path / "libro.epub"
        dummy_file.write_bytes(b"")

        with patch('ebooklib.epub.read_epub', return_value=mock_epub_book):
            book = parser.parse(str(dummy_file))

        assert book.detected_language == "es"

    def test_returns_one_section_per_chapter(self, parser, tmp_path):
        chapters = [
            "<p>" + "Contenido del capítulo uno. " * 20 + "</p>",
            "<p>" + "Contenido del capítulo dos. " * 20 + "</p>",
            "<p>" + "Contenido del capítulo tres. " * 20 + "</p>",
        ]
        mock_epub_book = self._make_mock_epub(chapters=chapters)
        dummy_file = tmp_path / "libro.epub"
        dummy_file.write_bytes(b"")

        with patch('ebooklib.epub.read_epub', return_value=mock_epub_book):
            book = parser.parse(str(dummy_file))

        assert len(book.sections) == 3

    def test_discards_short_items(self, parser, tmp_path):
        """Ítems con menos de 50 palabras (portadas, copyright) deben descartarse."""
        chapters = [
            "<p>Portada</p>",  # muy corto → descartado
            "<p>" + "Contenido real del capítulo. " * 20 + "</p>",
        ]
        mock_epub_book = self._make_mock_epub(chapters=chapters)
        dummy_file = tmp_path / "libro.epub"
        dummy_file.write_bytes(b"")

        with patch('ebooklib.epub.read_epub', return_value=mock_epub_book):
            book = parser.parse(str(dummy_file))

        assert len(book.sections) == 1

    def test_html_stripped_from_output(self, parser, tmp_path):
        # El EpubParser descarta ítems con < 50 palabras (portadas, copyright).
        # "Capítulo 1" aporta 2 palabras; necesitamos ≥ 48 repeticiones de "Contenido."
        chapters = ["<h1>Capítulo 1</h1><p>" + "Contenido. " * 50 + "</p>"]
        mock_epub_book = self._make_mock_epub(chapters=chapters)
        dummy_file = tmp_path / "libro.epub"
        dummy_file.write_bytes(b"")

        with patch('ebooklib.epub.read_epub', return_value=mock_epub_book):
            book = parser.parse(str(dummy_file))

        assert "<p>" not in book.sections[0]
        assert "<h1>" not in book.sections[0]
        assert "Capítulo 1" in book.sections[0]

    def test_html_entities_decoded(self, parser, tmp_path):
        chapters = ["<p>" + "Texto con &amp; y &quot;comillas&quot; y &nbsp; espacio. " * 15 + "</p>"]
        mock_epub_book = self._make_mock_epub(chapters=chapters)
        dummy_file = tmp_path / "libro.epub"
        dummy_file.write_bytes(b"")

        with patch('ebooklib.epub.read_epub', return_value=mock_epub_book):
            book = parser.parse(str(dummy_file))

        text = book.sections[0]
        assert "&amp;" not in text
        assert "&quot;" not in text
        assert '"comillas"' in text

    def test_missing_ebooklib_raises_import_error(self, parser, tmp_path):
        dummy_file = tmp_path / "libro.epub"
        dummy_file.write_bytes(b"")

        with patch.dict('sys.modules', {'ebooklib': None, 'ebooklib.epub': None}):
            with pytest.raises(ImportError, match="ebooklib"):
                parser.parse(str(dummy_file))


# ═══════════════════════════════════════════════════════════════════════════ #
#  ParserFactory                                                              #
# ═══════════════════════════════════════════════════════════════════════════ #

class TestParserFactory:

    @pytest.fixture
    def factory(self):
        from tenlib.processor.parsers.factory import ParserFactory
        return ParserFactory()

    def test_selects_txt_parser(self, factory, tmp_path):
        f = tmp_path / "libro.txt"
        f.write_text("Título\n\n" + "Contenido " * 60, encoding='utf-8')
        book = factory.parse(str(f))
        assert isinstance(book, RawBook)

    def test_raises_on_missing_file(self, factory):
        from tenlib.processor.parsers.factory import UnsupportedFormatError
        with pytest.raises(FileNotFoundError):
            factory.parse("/ruta/inexistente/libro.txt")

    def test_raises_on_unsupported_format(self, factory, tmp_path):
        from tenlib.processor.parsers.factory import UnsupportedFormatError
        f = tmp_path / "libro.pdf"
        f.write_bytes(b"%PDF-1.4")
        with pytest.raises(UnsupportedFormatError):
            factory.parse(str(f))

    def test_custom_parser_registered_first(self, factory, tmp_path):
        """Un parser registrado manualmente tiene prioridad sobre los defaults."""
        from tenlib.processor.parsers.base import BaseParser

        class FakeParser(BaseParser):
            def can_handle(self, path): return path.endswith('.fake')
            def parse(self, path): return RawBook("fake", path, ["sección fake"])

        factory.register(FakeParser())
        f = tmp_path / "libro.fake"
        f.write_text("algo")
        book = factory.parse(str(f))
        assert book.title == "fake"

    def test_parse_file_classmethod(self, tmp_path):
        from tenlib.processor.parsers.factory import ParserFactory
        f = tmp_path / "libro.txt"
        f.write_text("Mi Libro\n\n" + "Contenido " * 60, encoding='utf-8')
        book = ParserFactory.parse_file(str(f))
        assert isinstance(book, RawBook)
        assert book.title == "Mi Libro"