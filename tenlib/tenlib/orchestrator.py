# tenlib/orchestrator.py
import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from tenlib.processor.parsers.factory import ParserFactory
from tenlib.processor.chunker.chunker import Chunker
from tenlib.reconstructor import Reconstructor
from tenlib.router.router import Router, AllModelsExhaustedError
from tenlib.router.prompt_builder import build_translate_prompt
from tenlib.storage.repository import Repository
from tenlib.storage.models import BookMode, BookStatus, ChunkStatus

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Resultado del pipeline — lo que el CLI consume
# ------------------------------------------------------------------

@dataclass
class PipelineResult:
    book_id:        int
    output_path:    Path
    total_chunks:   int
    translated:     int
    flagged:        int
    was_resumed:    bool


# ------------------------------------------------------------------
# Errores propios del Orchestrator
# ------------------------------------------------------------------

class BookAlreadyDoneError(Exception):
    """El libro ya fue procesado completamente."""
    pass


# ------------------------------------------------------------------
# Orchestrator
# ------------------------------------------------------------------

class Orchestrator:
    """
    Dirige el pipeline completo de extremo a extremo.
    No tiene lógica de negocio propia — coordina módulos.

    Responsabilidades:
    - Decidir si es un libro nuevo o una reanudación
    - Iterar chunks pendientes y procesar cada uno
    - Manejar errores por chunk sin detener el pipeline
    - Delegar la reconstrucción al Reconstructor
    """

    def __init__(
        self,
        repo:         Repository,
        parser_factory: ParserFactory,
        chunker:      Chunker,
        router:       Router,
        reconstructor: Reconstructor,
    ):
        self._repo          = repo
        self._parser_factory = parser_factory
        self._chunker       = chunker
        self._router        = router
        self._reconstructor = reconstructor

    def run(
        self,
        file_path:   str,
        source_lang: str,
        target_lang: str,
        mode:        BookMode = BookMode.TRANSLATE,
    ) -> PipelineResult:
        """
        Punto de entrada principal. Idempotente:
        llamarlo dos veces con el mismo archivo reanuda desde donde quedó.
        """
        path = Path(file_path).resolve()
        self._assert_file_exists(path)

        # ── Paso 1: identidad del libro por hash ──────────────────────
        file_hash = _compute_hash(path)
        book      = self._repo.get_book_by_hash(file_hash)
        was_resumed = False

        if book:
            if book.status == BookStatus.DONE:
                raise BookAlreadyDoneError(
                    f"'{book.title}' ya está completamente procesado. "
                    f"book_id={book.id}"
                )
            was_resumed = True
            book_id     = book.id
            title       = book.title
            self._log(f"Reanudando '{title}' (book_id={book_id})")

        else:
            # ── Paso 2: libro nuevo — parsear y chunkear ──────────────
            title   = path.stem
            book_id = self._repo.create_book(
                title       = title,
                file_hash   = file_hash,
                mode        = mode,
                source_lang = source_lang,
                target_lang = target_lang,
            )
            self._log(f"Nuevo libro: '{title}' (book_id={book_id})")
            self._parse_and_store(path, book_id)

        # ── Paso 3: obtener chunks pendientes ─────────────────────────
        pending = self._repo.get_pending_chunks(book_id)

        if not pending:
            self._log("No hay chunks pendientes — nada que procesar")
            output_path = self._reconstruct(book_id, title, target_lang)
            return self._build_result(
                book_id, output_path, was_resumed, flagged_ids=[]
            )

        total_chunks = len(self._repo.get_all_chunks(book_id))
        done_so_far  = total_chunks - len(pending)

        self._log(f"'{title}' — {total_chunks} chunks totales")
        if was_resumed:
            self._log(f"Reanudando desde chunk {done_so_far}...")

        # ── Paso 4: procesar cada chunk pendiente ─────────────────────
        flagged_ids = self._process_chunks(
            pending     = pending,
            book_id     = book_id,
            source_lang = source_lang,
            target_lang = target_lang,
            total       = total_chunks,
            offset      = done_so_far,
        )

        # ── Paso 5: reconstruir y marcar DONE ─────────────────────────
        output_path = self._reconstruct(book_id, title, target_lang)
        self._repo.update_book_status(book_id, BookStatus.DONE)

        translated = total_chunks - len(flagged_ids)
        self._log(
            f"Completado: {translated} traducidos, {len(flagged_ids)} flaggeados"
        )
        self._log(f"Output: {output_path}")

        return self._build_result(book_id, output_path, was_resumed, flagged_ids)

    # ------------------------------------------------------------------
    # Pasos internos
    # ------------------------------------------------------------------

    def _parse_and_store(self, path: Path, book_id: int) -> None:
        """Parsea el archivo, chunkea y guarda todos en PENDING."""
        parser   = self._parser_factory.get_parser(str(path))
        raw_book = parser.parse(str(path))
        chunks   = self._chunker.chunk(raw_book)
        self._repo.save_chunks(book_id, chunks)
        self._log(f"{len(chunks)} chunks creados y guardados")

    def _process_chunks(
        self,
        pending:     list,
        book_id:     int,
        source_lang: str,
        target_lang: str,
        total:       int,
        offset:      int,
    ) -> list[int]:
        """
        Itera los chunks pendientes.
        Cada chunk tiene su propio try/except — un fallo no detiene el pipeline.
        Devuelve la lista de chunk_ids que quedaron FLAGGED.
        """
        flagged_ids: list[int] = []

        system_prompt = build_translate_prompt(
            source_lang = source_lang,
            target_lang = target_lang,
        )

        for i, chunk in enumerate(pending):
            current = offset + i + 1
            percent = int(current / total * 100)

            try:
                response = self._router.translate(chunk.original, system_prompt)

                self._repo.update_chunk_translation(
                    chunk_id   = chunk.id,
                    translated = response.translation,
                    model_used = response.model_used,
                    confidence = response.confidence,
                    status     = self._resolve_status(response.confidence),
                )

                print(
                    f"[tenlib] Traduciendo... {current}/{total} ({percent}%)"
                    f" — modelo: {response.model_used}"
                    f" — confianza: {response.confidence:.2f}"
                )

            except AllModelsExhaustedError as e:
                # Todos los modelos agotados — no tiene sentido continuar
                # Los chunks que faltan quedan PENDING para la próxima ejecución
                logger.error("Todos los modelos agotados: %s", e)
                self._log(
                    f"⚠ Pipeline pausado en chunk {current}/{total}. "
                    f"Reejecutar cuando haya quota disponible."
                )
                break

            except Exception as e:
                # Error en un chunk individual — marcar y continuar
                logger.warning("Error en chunk %d: %s", chunk.chunk_index, e)
                self._repo.flag_chunk(
                    chunk_id = chunk.id,
                    flags    = [f"error: {type(e).__name__}: {e}"],
                )
                flagged_ids.append(chunk.id)
                print(
                    f"[tenlib] ⚠ Chunk {current}/{total} flaggeado ({type(e).__name__})"
                    f" — continuando"
                )

        return flagged_ids

    def _reconstruct(self, book_id: int, title: str, target_lang: str) -> Path:
        filename = f"{_slugify(title)}_{target_lang}.txt"
        return self._reconstructor.build(book_id, filename)

    def _build_result(
        self,
        book_id:     int,
        output_path: Path,
        was_resumed: bool,
        flagged_ids: list[int],
    ) -> PipelineResult:
        all_chunks = self._repo.get_all_chunks(book_id)
        return PipelineResult(
            book_id      = book_id,
            output_path  = output_path,
            total_chunks = len(all_chunks),
            translated   = sum(1 for c in all_chunks if c.status == ChunkStatus.DONE),
            flagged      = sum(1 for c in all_chunks if c.status == ChunkStatus.FLAGGED),
            was_resumed  = was_resumed,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _assert_file_exists(path: Path) -> None:
        if not path.exists():
            raise FileNotFoundError(f"Archivo no encontrado: {path}")

    @staticmethod
    def _resolve_status(confidence: float) -> ChunkStatus:
        """Chunks con baja confianza van a FLAGGED para revisión humana."""
        return ChunkStatus.DONE if confidence >= 0.75 else ChunkStatus.FLAGGED

    @staticmethod
    def _log(message: str) -> None:
        print(f"[tenlib] {message}")


# ------------------------------------------------------------------
# Funciones de módulo (helpers privados)
# ------------------------------------------------------------------

def _compute_hash(path: Path) -> str:
    """SHA-256 del archivo — identifica el libro independientemente del nombre."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def _slugify(title: str) -> str:
    """Convierte el título en un nombre de archivo seguro."""
    import re
    slug = title.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s]+", "_", slug)
    return slug