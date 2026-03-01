# tenlib/reconstructor_pdf.py
import logging
from pathlib import Path

from tenlib.storage.repository import Repository
from tenlib.storage.models import ChunkStatus

logger = logging.getLogger(__name__)

_REVIEW_MARKER = "[⚠ PENDIENTE DE REVISIÓN]\n"
_OUTPUT_DIR    = Path.home() / ".tenlib" / "output"


class PdfReconstructor:
    """
    Reconstruye un PDF traducido a partir del original, reemplazando solo
    el texto y preservando imágenes e ilustraciones.

    Requiere la biblioteca pymupdf (pip install pymupdf).
    """

    def __init__(self, repo: Repository, output_dir: Path | None = None):
        self._repo       = repo
        self._output_dir = output_dir or _OUTPUT_DIR

    def build(self, book_id: int, output_filename: str, source_path: str | None = None) -> Path:
        """
        Construye el PDF de salida y devuelve la ruta.

        Si source_path es un PDF, abre el original con PyMuPDF y reemplaza
        el texto de cada bloque con la traducción correspondiente, ajustando
        el tamaño de fuente automáticamente para que quepa en el mismo espacio.

        Si source_path no se proporciona o no es PDF, cae back a salida TXT.
        """
        chunks = self._repo.get_all_chunks(book_id)
        if not chunks:
            raise ValueError(f"No hay chunks para el libro {book_id}")

        self._output_dir.mkdir(parents=True, exist_ok=True)

        # Si el archivo fuente es PDF e importa pymupdf → reconstruir PDF
        if source_path and source_path.lower().endswith(".pdf"):
            try:
                return self._build_pdf(chunks, book_id, output_filename, source_path)
            except ImportError:
                logger.warning(
                    "pymupdf no está instalado (pip install pymupdf). "
                    "Generando output TXT como alternativa."
                )

        # Fallback: output TXT (mismo comportamiento que Reconstructor)
        return self._build_txt(chunks, output_filename)

    def _build_pdf(self, chunks, book_id: int, output_filename: str, source_path: str) -> Path:
        import fitz  # pymupdf

        # Construir mapa: source_section → lista de textos traducidos (en orden)
        section_texts: dict[int, list[str]] = {}
        for chunk in sorted(chunks, key=lambda c: c.index):
            text = self._resolve_chunk_text(chunk)
            section = chunk.source_section
            section_texts.setdefault(section, []).append(text)

        doc = fitz.open(source_path)
        output_path = self._output_dir / output_filename.replace(".txt", ".pdf")

        for page_idx, page in enumerate(doc):
            if page_idx not in section_texts:
                continue

            translated_parts = section_texts[page_idx]
            translated_full  = "\n\n".join(translated_parts)

            # Obtener bloques de texto de la página
            blocks = page.get_text("blocks")
            text_blocks = [b for b in blocks if b[6] == 0]  # type 0 = texto

            if not text_blocks:
                continue

            # Calcular bounding box que engloba todo el texto de la página
            x0 = min(b[0] for b in text_blocks)
            y0 = min(b[1] for b in text_blocks)
            x1 = max(b[2] for b in text_blocks)
            y1 = max(b[3] for b in text_blocks)
            text_rect = fitz.Rect(x0, y0, x1, y1)

            # Estimar tamaño de fuente original del primer bloque
            original_fontsize = _estimate_fontsize(text_blocks[0][4])

            # Redactar todo el texto existente
            page.add_redact_annot(text_rect)
            page.apply_redactions()

            # Insertar texto traducido ajustando fuente si no cabe
            _insert_text_fitting(page, text_rect, translated_full, original_fontsize)

        doc.save(str(output_path))
        doc.close()
        logger.info("PDF output escrito en: %s", output_path)
        return output_path

    def _build_txt(self, chunks, output_filename: str) -> Path:
        output_path = self._output_dir / output_filename
        parts: list[str] = []
        prev_section: int | None = None
        for chunk in chunks:
            if prev_section is not None and chunk.source_section != prev_section:
                parts.append("\n\n")
            parts.append(self._resolve_chunk_text(chunk))
            prev_section = chunk.source_section
        output_path.write_text("\n\n".join(parts), encoding="utf-8")
        logger.info("Output TXT escrito en: %s", output_path)
        return output_path

    @staticmethod
    def _resolve_chunk_text(chunk) -> str:
        if chunk.translated:
            return chunk.translated
        if chunk.status == ChunkStatus.FLAGGED:
            return f"{_REVIEW_MARKER}{chunk.original}"
        return chunk.original


# ── Helpers PDF ───────────────────────────────────────────────────────────────

def _estimate_fontsize(block_text: str, default: float = 11.0) -> float:
    """
    Intenta estimar el tamaño de fuente dominante del bloque.
    PyMuPDF no expone fontsize directamente en bloques básicos;
    usamos el tamaño por defecto como punto de partida conservador.
    """
    return default


def _insert_text_fitting(page, rect, text: str, original_fontsize: float) -> None:
    """
    Inserta texto en el rect dado, reduciendo el tamaño de fuente
    en pasos de 0.5pt hasta que quepa (mínimo 6pt).
    """
    import fitz

    fontsize = original_fontsize
    while fontsize >= 6:
        result = page.insert_textbox(
            rect,
            text,
            fontsize  = fontsize,
            fontname  = "helv",
            align     = fitz.TEXT_ALIGN_LEFT,
        )
        if result >= 0:  # >= 0 significa que el texto cupó
            return
        fontsize -= 0.5

    # Last resort: insertar con fuente mínima aunque se corte
    page.insert_textbox(
        rect,
        text,
        fontsize = 6,
        fontname = "helv",
        align    = fitz.TEXT_ALIGN_LEFT,
    )
