# tenlib/reconstructor.py
import logging
from pathlib import Path
from tenlib.storage.repository import Repository
from tenlib.storage.models import ChunkStatus

logger = logging.getLogger(__name__)

_REVIEW_MARKER = "[⚠ PENDIENTE DE REVISIÓN]\n"
_OUTPUT_DIR    = Path.home() / ".tenlib" / "output"


class Reconstructor:
    """
    Responsabilidad única: tomar los chunks almacenados de un libro
    y escribir el archivo de salida en TXT.

    No sabe nada de modelos, parsers ni lógica de traducción.
    Recibe el book_id y produce un archivo.
    """

    def __init__(self, repo: Repository, output_dir: Path | None = None):
        self._repo       = repo
        self._output_dir = output_dir or _OUTPUT_DIR

    def build(self, book_id: int, output_filename: str, source_path: str | None = None) -> Path:
        """
        Construye el archivo de salida y devuelve la ruta.
        Si un chunk está FLAGGED sin traducción, inserta el original
        con una marca visible para revisión manual.
        """
        chunks = self._repo.get_all_chunks(book_id)

        if not chunks:
            raise ValueError(f"No hay chunks para el libro {book_id}")

        self._output_dir.mkdir(parents=True, exist_ok=True)
        output_path = self._output_dir / output_filename

        parts: list[str] = []
        prev_section: int | None = None

        for chunk in chunks:  # ya vienen ordenados por chunk_index
            # Insertar salto entre secciones para preservar estructura
            if prev_section is not None and chunk.source_section != prev_section:
                parts.append("\n\n")

            text = self._resolve_chunk_text(chunk)
            parts.append(text)
            prev_section = chunk.source_section

        output_path.write_text("\n\n".join(parts), encoding="utf-8")
        logger.info("Output escrito en: %s", output_path)
        return output_path

    @staticmethod
    def _resolve_chunk_text(chunk) -> str:
        """
        Decide qué texto usar para cada chunk.
        Orden de preferencia:
        1. translated (el camino feliz)
        2. original con marca de revisión (chunk flaggeado sin traducción)
        """
        if chunk.translated:
            return chunk.translated

        if chunk.status == ChunkStatus.FLAGGED:
            return f"{_REVIEW_MARKER}{chunk.original}"

        # PENDING o DONE sin traducción — no debería ocurrir, pero es seguro
        return chunk.original