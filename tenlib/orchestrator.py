# tenlib/orchestrator.py
import hashlib
import logging
from dataclasses import dataclass
from numbers import Integral
from pathlib import Path
from typing import Optional

from tenlib.processor.parsers.factory import ParserFactory
from tenlib.processor.chunker.chunker import Chunker
from tenlib.reconstructor import Reconstructor
from tenlib.router.router import Router, AllModelsExhaustedError
from tenlib.router.prompt_builder import (
    build_translate_prompt,
    build_fix_prompt,
    build_polish_prompt,
)
from tenlib.context.bible import BookBible, BibleUpdate, _GENERIC_CHARACTER_DESCRIPTION as _GENERIC_DESC
from tenlib.context.character_detector import extract_character_mentions
from tenlib.context.compressor import BibleCompressor
from tenlib.context.extractor import BibleExtractor
from tenlib.storage.repository import Repository
from tenlib.storage.models import BookMode, BookStatus, ChunkStatus

logger = logging.getLogger(__name__)


class _NoopBibleExtractor:
    """Compatibilidad para tests/llamadores que no usan contexto todavía."""

    def extract(
        self,
        original:             str,
        translation:          str,
        notes:                str,
        chunk_index:          int,
        character_candidates: Optional[dict] = None,
        force:                bool           = False,
    ):
        return None


@dataclass
class _PreparedFixChunk:
    """
    Chunk transitorio para persistir en modo fix.
    - original: texto de la traducción existente (a corregir)
    """
    index: int
    original: str
    token_estimated: int
    source_section: int


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
        extractor:    Optional[BibleExtractor] = None,
        compressor:   Optional[BibleCompressor] = None,
    ):
        self._repo          = repo
        self._parser_factory = parser_factory
        self._chunker       = chunker
        self._router        = router
        self._reconstructor = reconstructor
        self._extractor     = extractor or _NoopBibleExtractor()
        self._compressor    = compressor or BibleCompressor()

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
            self._assert_book_can_run(book)
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
            output_path = self._reconstruct(book_id, title, target_lang, str(path))
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

        # ── Paso 5: reconstruir y actualizar estado ───────────────────
        output_path = self._reconstruct(book_id, title, target_lang, str(path))
        result = self._build_result(book_id, output_path, was_resumed, flagged_ids)
        pending_after = result.total_chunks - result.translated - result.flagged

        if pending_after > 0:
            self._repo.update_book_status(book_id, BookStatus.IN_PROGRESS)
            self._log(
                f"Pausado: {result.translated} traducidos, {result.flagged} flaggeados, "
                f"{pending_after} pendientes"
            )
        else:
            self._repo.update_book_status(book_id, BookStatus.DONE)
            self._log(
                f"Completado: {result.translated} traducidos, {result.flagged} flaggeados"
            )

        self._log(f"Output: {output_path}")
        return result

    def run_fix(
        self,
        original_path: str,
        translation_path: str,
        target_lang: str,
        source_lang: str = "auto",
    ) -> PipelineResult:
        """
        Corrige una traducción existente usando el texto original como referencia.
        Idempotente por hash combinado (original + traducción + modo fix).
        """
        source_path = Path(original_path).resolve()
        draft_path  = Path(translation_path).resolve()
        self._assert_file_exists(source_path)
        self._assert_file_exists(draft_path)

        file_hash = _compute_fix_hash(source_path, draft_path)
        book      = self._repo.get_book_by_hash(file_hash)
        was_resumed = False

        source_chunks = self._parse_source_chunks(source_path)

        if book:
            self._assert_book_can_run(book)
            was_resumed = True
            book_id     = book.id
            title       = book.title
            self._log(f"Reanudando fix de '{title}' (book_id={book_id})")
        else:
            title   = draft_path.stem
            book_id = self._repo.create_book(
                title       = title,
                file_hash   = file_hash,
                mode        = BookMode.FIX,
                source_lang = source_lang,
                target_lang = target_lang,
            )
            self._log(f"Nuevo trabajo fix: '{title}' (book_id={book_id})")
            self._parse_and_store_fix(
                source_chunks    = source_chunks,
                translation_path = draft_path,
                book_id          = book_id,
            )

        pending = self._repo.get_pending_chunks(book_id)
        if not pending:
            self._log("No hay chunks pendientes — nada que corregir")
            output_path = self._reconstruct(book_id, title, target_lang, str(draft_path))
            return self._build_result(book_id, output_path, was_resumed, flagged_ids=[])

        total_chunks = len(self._repo.get_all_chunks(book_id))
        done_so_far  = total_chunks - len(pending)

        self._log(f"'{title}' (fix) — {total_chunks} chunks totales")
        if was_resumed:
            self._log(f"Reanudando corrección desde chunk {done_so_far}...")

        source_by_index = {chunk.index: chunk.original for chunk in source_chunks}
        flagged_ids = self._process_chunks_fix(
            pending         = pending,
            book_id         = book_id,
            source_by_index = source_by_index,
            source_lang     = source_lang,
            target_lang     = target_lang,
            total           = total_chunks,
            offset          = done_so_far,
        )

        output_path = self._reconstruct(book_id, title, target_lang, str(draft_path))
        result = self._build_result(book_id, output_path, was_resumed, flagged_ids)
        pending_after = result.total_chunks - result.translated - result.flagged

        if pending_after > 0:
            self._repo.update_book_status(book_id, BookStatus.IN_PROGRESS)
            self._log(
                f"Fix pausado: {result.translated} corregidos, {result.flagged} flaggeados, "
                f"{pending_after} pendientes"
            )
        else:
            self._repo.update_book_status(book_id, BookStatus.DONE)
            self._log(
                f"Fix completado: {result.translated} corregidos, {result.flagged} flaggeados"
            )

        self._log(f"Output: {output_path}")
        return result

    def run_fix_style(
        self,
        translation_path: str,
        target_lang: str,
        source_lang: str = "auto",
    ) -> PipelineResult:
        """
        Corrige estilo/fluidez de una traducción existente sin original de referencia.
        """
        draft_path = Path(translation_path).resolve()
        self._assert_file_exists(draft_path)

        file_hash = _compute_fix_style_hash(draft_path, target_lang)
        book      = self._repo.get_book_by_hash(file_hash)
        was_resumed = False

        if book:
            self._assert_book_can_run(book)
            was_resumed = True
            book_id     = book.id
            title       = book.title
            self._log(f"Reanudando fix-style de '{title}' (book_id={book_id})")
        else:
            title   = draft_path.stem
            book_id = self._repo.create_book(
                title       = title,
                file_hash   = file_hash,
                mode        = BookMode.FIX,
                source_lang = source_lang,
                target_lang = target_lang,
            )
            self._log(f"Nuevo trabajo fix-style: '{title}' (book_id={book_id})")
            self._parse_and_store(draft_path, book_id)

        pending = self._repo.get_pending_chunks(book_id)
        if not pending:
            self._log("No hay chunks pendientes — nada que corregir")
            output_path = self._reconstruct(book_id, title, target_lang, str(draft_path))
            return self._build_result(book_id, output_path, was_resumed, flagged_ids=[])

        total_chunks = len(self._repo.get_all_chunks(book_id))
        done_so_far  = total_chunks - len(pending)

        self._log(f"'{title}' (fix-style) — {total_chunks} chunks totales")
        if was_resumed:
            self._log(f"Reanudando corrección desde chunk {done_so_far}...")

        flagged_ids = self._process_chunks_polish(
            pending     = pending,
            book_id     = book_id,
            target_lang = target_lang,
            total       = total_chunks,
            offset      = done_so_far,
        )

        output_path = self._reconstruct(book_id, title, target_lang, str(draft_path))
        result = self._build_result(book_id, output_path, was_resumed, flagged_ids)
        pending_after = result.total_chunks - result.translated - result.flagged

        if pending_after > 0:
            self._repo.update_book_status(book_id, BookStatus.IN_PROGRESS)
            self._log(
                f"Fix-style pausado: {result.translated} corregidos, {result.flagged} flaggeados, "
                f"{pending_after} pendientes"
            )
        else:
            self._repo.update_book_status(book_id, BookStatus.DONE)
            self._log(
                f"Fix-style completado: {result.translated} corregidos, {result.flagged} flaggeados"
            )

        self._log(f"Output: {output_path}")
        return result

    # ------------------------------------------------------------------
    # Pasos internos
    # ------------------------------------------------------------------

    def _parse_and_store(self, path: Path, book_id: int) -> None:
        """Parsea el archivo, chunkea y guarda todos en PENDING."""
        raw_book = self._parser_factory.parse(str(path))
        chunks   = self._chunker.chunk(raw_book)
        self._repo.save_chunks(book_id, chunks)
        self._log(f"{len(chunks)} chunks creados y guardados")

    def _parse_source_chunks(self, source_path: Path) -> list:
        """Parsea y chunkea el texto original usado como referencia en modo fix."""
        source_book = self._parser_factory.parse(str(source_path))
        return self._chunker.chunk(source_book)

    def _parse_and_store_fix(
        self,
        source_chunks: list,
        translation_path: Path,
        book_id: int,
    ) -> None:
        """
        Crea chunks para el modo fix:
        - límites del original (source_chunks)
        - contenido de cada chunk = traducción existente alineada por proporción
        """
        translation_book = self._parser_factory.parse(str(translation_path))
        aligned_translation = _align_translation_by_reference_chunks(
            source_chunks,
            translation_book.sections,
        )

        staged_chunks: list[_PreparedFixChunk] = []
        for i, source_chunk in enumerate(source_chunks):
            staged_chunks.append(
                _PreparedFixChunk(
                    index           = source_chunk.index,
                    original        = aligned_translation[i],
                    token_estimated = _as_int(getattr(source_chunk, "token_estimated", 0)),
                    source_section  = _as_int(getattr(source_chunk, "source_section", 0)),
                )
            )

        self._repo.save_chunks(book_id, staged_chunks)
        self._log(
            f"{len(staged_chunks)} chunks fix creados y guardados "
            f"(alineados desde traducción existente)"
        )

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

        bible = self._load_or_init_bible(book_id)

        for i, chunk in enumerate(pending):
            current = offset + i + 1
            percent = int(current / total * 100)

            try:
                # ── ANTES: comprimir Bible al contexto del chunk ──────
                compressed = self._compressor.compress(bible, chunk.original)
                ratio      = self._compressor.compression_ratio(bible, compressed)

                if ratio < 1.0:
                    logger.debug(
                        "Bible comprimida: %.0f%% de entradas relevantes para chunk %d",
                        ratio * 100, chunk.chunk_index,
                    )

                system_prompt = build_translate_prompt(
                    source_lang = source_lang,
                    target_lang = target_lang,
                    voice       = compressed.voice,
                    decisions   = compressed.decisions,
                    glossary    = compressed.glossary,
                    characters  = compressed.characters,
                    last_scene  = compressed.last_scene,
                )

                # ── Traducir ──────────────────────────────────────────
                response = self._router.translate(chunk.original, system_prompt)

                self._repo.update_chunk_translation(
                    chunk_id   = chunk.id,
                    translated = response.translation,
                    model_used = response.model_used,
                    confidence = response.confidence,
                    status     = self._resolve_status(response.confidence),
                )

                # ── DESPUÉS: actualizar Bible con lo aprendido ────────
                # 1. Detectar candidatos una sola vez (detector local rápido)
                local_characters = extract_character_mentions(
                    source_text         = chunk.original,
                    translated_text     = response.translation,
                    existing_characters = bible.characters,
                )

                # 2. Extractor IA valida/enriquece los candidatos locales.
                # Forzar extracción si hay candidatos nuevos o sin enriquecer
                # para que el AI los enriquezca en el mismo chunk donde aparecen.
                extracted_update = self._extractor.extract(
                    original             = chunk.original,
                    translation          = response.translation,
                    notes                = response.notes,
                    chunk_index          = chunk.chunk_index,
                    character_candidates = local_characters,
                    force                = _has_unenriched_candidates(local_characters, bible),
                )

                # 3. Update local: voz, decisiones, last_scene + candidatos como fallback
                local_update = _build_local_bible_update(
                    source_text         = chunk.original,
                    translated_text     = response.translation,
                    notes               = response.notes,
                    existing_voice      = bible.voice,
                    detected_characters = local_characters,
                )
                merged_update = _merge_bible_updates(local_update, extracted_update)
                bible.apply(merged_update)
                version = self._repo.save_bible(book_id, bible)
                logger.debug("Bible actualizada a versión %d", version)

                print(
                    f"[tenlib] Traduciendo... {current}/{total} ({percent}%)"
                    f" — modelo: {response.model_used}"
                    f" — confianza: {response.confidence:.2f}"
                )

            except AllModelsExhaustedError as e:
                logger.error("Todos los modelos agotados: %s", e)
                self._log(
                    f"⚠ Pipeline pausado en chunk {current}/{total}. "
                    f"Reejecutar cuando haya quota disponible."
                )
                break

            except Exception as e:
                logger.warning("Error en chunk %d: %s", chunk.chunk_index, e)
                self._repo.flag_chunk(
                    chunk_id = chunk.id,
                    flags    = [f"error: {type(e).__name__}: {e}"],
                )
                flagged_ids.append(chunk.id)
                print(
                    f"[tenlib] ⚠ Chunk {current}/{total} flaggeado"
                    f" ({type(e).__name__}) — continuando"
                )

        return flagged_ids

    def _process_chunks_fix(
        self,
        pending: list,
        book_id: int,
        source_by_index: dict[int, str],
        source_lang: str,
        target_lang: str,
        total: int,
        offset: int,
    ) -> list[int]:
        """
        Itera chunks pendientes del modo fix.
        - chunk.original: traducción existente a corregir
        - source_by_index[idx]: original de referencia
        """
        flagged_ids: list[int] = []
        bible = self._load_or_init_bible(book_id)

        for i, chunk in enumerate(pending):
            current = offset + i + 1
            percent = int(current / total * 100)

            source_chunk = source_by_index.get(chunk.chunk_index, "")
            draft_chunk  = chunk.original

            if not source_chunk:
                logger.warning(
                    "Fix: chunk %d sin referencia del original; se usa solo borrador",
                    chunk.chunk_index,
                )

            try:
                compressed = self._compressor.compress(
                    bible,
                    source_chunk or draft_chunk,
                )
                ratio = self._compressor.compression_ratio(bible, compressed)

                if ratio < 1.0:
                    logger.debug(
                        "Bible comprimida (fix): %.0f%% para chunk %d",
                        ratio * 100, chunk.chunk_index,
                    )

                system_prompt = build_fix_prompt(
                    source_lang = source_lang,
                    target_lang = target_lang,
                    voice       = compressed.voice,
                    decisions   = compressed.decisions,
                    glossary    = compressed.glossary,
                    characters  = compressed.characters,
                    last_scene  = compressed.last_scene,
                )

                user_chunk = _build_fix_chunk_payload(
                    source_chunk   = source_chunk,
                    draft_chunk    = draft_chunk,
                    source_lang    = source_lang,
                    target_lang    = target_lang,
                )

                response = self._router.translate(user_chunk, system_prompt)

                self._repo.update_chunk_translation(
                    chunk_id   = chunk.id,
                    translated = response.translation,
                    model_used = response.model_used,
                    confidence = response.confidence,
                    status     = self._resolve_status(response.confidence),
                )

                local_characters = extract_character_mentions(
                    source_text         = source_chunk or draft_chunk,
                    translated_text     = response.translation,
                    existing_characters = bible.characters,
                )

                extracted_update = self._extractor.extract(
                    original             = source_chunk or draft_chunk,
                    translation          = response.translation,
                    notes                = response.notes,
                    chunk_index          = chunk.chunk_index,
                    character_candidates = local_characters,
                    force                = _has_unenriched_candidates(local_characters, bible),
                )

                local_update = _build_local_bible_update(
                    source_text         = source_chunk or draft_chunk,
                    translated_text     = response.translation,
                    notes               = response.notes,
                    existing_voice      = bible.voice,
                    detected_characters = local_characters,
                )
                merged_update = _merge_bible_updates(local_update, extracted_update)
                bible.apply(merged_update)
                version = self._repo.save_bible(book_id, bible)
                logger.debug("Bible actualizada (fix) a versión %d", version)

                print(
                    f"[tenlib] Corrigiendo... {current}/{total} ({percent}%)"
                    f" — modelo: {response.model_used}"
                    f" — confianza: {response.confidence:.2f}"
                )

            except AllModelsExhaustedError as e:
                logger.error("Todos los modelos agotados en fix: %s", e)
                self._log(
                    f"⚠ Pipeline fix pausado en chunk {current}/{total}. "
                    f"Reejecutar cuando haya quota disponible."
                )
                break

            except Exception as e:
                logger.warning("Error en chunk fix %d: %s", chunk.chunk_index, e)
                self._repo.flag_chunk(
                    chunk_id = chunk.id,
                    flags    = [f"error: {type(e).__name__}: {e}"],
                )
                flagged_ids.append(chunk.id)
                print(
                    f"[tenlib] ⚠ Chunk {current}/{total} flaggeado"
                    f" ({type(e).__name__}) — continuando"
                )

        return flagged_ids

    def _process_chunks_polish(
        self,
        pending: list,
        book_id: int,
        target_lang: str,
        total: int,
        offset: int,
    ) -> list[int]:
        """
        Itera chunks pendientes del modo fix-style (sin original).
        """
        flagged_ids: list[int] = []
        bible = self._load_or_init_bible(book_id)

        for i, chunk in enumerate(pending):
            current = offset + i + 1
            percent = int(current / total * 100)

            try:
                compressed = self._compressor.compress(bible, chunk.original)
                ratio = self._compressor.compression_ratio(bible, compressed)

                if ratio < 1.0:
                    logger.debug(
                        "Bible comprimida (fix-style): %.0f%% para chunk %d",
                        ratio * 100, chunk.chunk_index,
                    )

                system_prompt = build_polish_prompt(
                    target_lang = target_lang,
                    voice       = compressed.voice,
                    decisions   = compressed.decisions,
                    glossary    = compressed.glossary,
                    characters  = compressed.characters,
                    last_scene  = compressed.last_scene,
                )

                user_chunk = _build_polish_chunk_payload(
                    draft_chunk = chunk.original,
                    target_lang = target_lang,
                )

                response = self._router.translate(user_chunk, system_prompt)

                self._repo.update_chunk_translation(
                    chunk_id   = chunk.id,
                    translated = response.translation,
                    model_used = response.model_used,
                    confidence = response.confidence,
                    status     = self._resolve_status(response.confidence),
                )

                local_characters = extract_character_mentions(
                    source_text         = chunk.original,
                    translated_text     = response.translation,
                    existing_characters = bible.characters,
                )

                # En fix-style llamamos al extractor para el primer chunk y
                # cada N chunks para capturar voz narrativa y decisiones de estilo.
                extracted_update = self._extractor.extract(
                    original             = chunk.original,
                    translation          = response.translation,
                    notes                = response.notes,
                    chunk_index          = chunk.chunk_index,
                    character_candidates = local_characters,
                    force                = _has_unenriched_candidates(local_characters, bible),
                )
                local_update = _build_local_bible_update(
                    source_text         = chunk.original,
                    translated_text     = response.translation,
                    notes               = response.notes,
                    existing_voice      = bible.voice,
                    detected_characters = local_characters,
                )
                merged_update = _merge_bible_updates(local_update, extracted_update)
                bible.apply(merged_update)
                version = self._repo.save_bible(book_id, bible)
                logger.debug("Bible actualizada (fix-style) a versión %d", version)

                print(
                    f"[tenlib] Corrigiendo estilo... {current}/{total} ({percent}%)"
                    f" — modelo: {response.model_used}"
                    f" — confianza: {response.confidence:.2f}"
                )

            except AllModelsExhaustedError as e:
                logger.error("Todos los modelos agotados en fix-style: %s", e)
                self._log(
                    f"⚠ Pipeline fix-style pausado en chunk {current}/{total}. "
                    f"Reejecutar cuando haya quota disponible."
                )
                break

            except Exception as e:
                logger.warning("Error en chunk fix-style %d: %s", chunk.chunk_index, e)
                self._repo.flag_chunk(
                    chunk_id = chunk.id,
                    flags    = [f"error: {type(e).__name__}: {e}"],
                )
                flagged_ids.append(chunk.id)
                print(
                    f"[tenlib] ⚠ Chunk {current}/{total} flaggeado"
                    f" ({type(e).__name__}) — continuando"
                )

        return flagged_ids

    def _reconstruct(self, book_id: int, title: str, target_lang: str, source_path: str | None = None) -> Path:
        filename = f"{_slugify(title)}_{target_lang}.txt"
        return self._reconstructor.build(book_id, filename, source_path)

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

    def _load_or_init_bible(self, book_id: int) -> BookBible:
        """
        Garantiza que exista al menos una versión de Bible por libro.
        Evita libros procesados sin rastro de Bible cuando el extractor falla.
        """
        bible = self._repo.get_latest_bible(book_id)
        if bible is not None:
            return bible

        bible = BookBible.empty()
        version = self._repo.save_bible(book_id, bible)
        logger.debug("Bible inicial creada para book_id=%d (version=%d)", book_id, version)
        return bible

    def _assert_book_can_run(self, book) -> None:
        """
        Compatibilidad: si un libro quedó DONE pero tiene PENDING (estado legacy
        inconsistente), lo forzamos a IN_PROGRESS para permitir reanudación.
        """
        if book.status != BookStatus.DONE:
            return

        pending = self._repo.get_pending_chunks(book.id)
        if pending:
            logger.warning(
                "book_id=%d estaba DONE con %d pendientes; se fuerza reanudación",
                book.id,
                len(pending),
            )
            self._repo.update_book_status(book.id, BookStatus.IN_PROGRESS)
            return

        raise BookAlreadyDoneError(
            f"'{book.title}' ya está completamente procesado. "
            f"book_id={book.id}"
        )

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


def _compute_fix_hash(original_path: Path, translation_path: Path) -> str:
    """
    Hash estable para modo fix usando ambos archivos.
    Evita colisiones entre trabajos translate vs fix.
    """
    combined = (
        f"fix|{_compute_hash(original_path)}|{_compute_hash(translation_path)}"
    )
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def _compute_fix_style_hash(translation_path: Path, target_lang: str) -> str:
    """
    Hash estable para modo fix-style (sin original).
    """
    combined = f"fix_style|{target_lang.lower()}|{_compute_hash(translation_path)}"
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def _as_int(value, default: int = 0) -> int:
    if isinstance(value, Integral) and not isinstance(value, bool):
        return int(value)
    return default


def _align_translation_by_reference_chunks(
    reference_chunks: list,
    translation_sections: list[str],
) -> list[str]:
    """
    Alinea la traducción a los límites del original.
    Estrategia MVP: split proporcional por longitud de los chunks de referencia.
    """
    if not reference_chunks:
        return []

    chunk_lengths = [
        max(len(getattr(chunk, "original", "") or ""), 1)
        for chunk in reference_chunks
    ]
    translation_text = "\n\n".join(translation_sections or [])
    return _split_text_by_reference_lengths(translation_text, chunk_lengths)


def _split_text_by_reference_lengths(text: str, reference_lengths: list[int]) -> list[str]:
    if not reference_lengths:
        return []

    if not text:
        return ["" for _ in reference_lengths]

    safe_lengths = [max(length, 1) for length in reference_lengths]
    total_reference = sum(safe_lengths)
    total_chars = len(text)

    segments: list[str] = []
    start = 0
    consumed_reference = 0

    for length in safe_lengths[:-1]:
        consumed_reference += length
        target = round(consumed_reference / total_reference * total_chars)
        split_idx = _snap_split_index(text, target, start)
        segments.append(text[start:split_idx].strip())
        start = split_idx

    segments.append(text[start:].strip())
    return segments


def _snap_split_index(text: str, target: int, start: int) -> int:
    """
    Ajusta el corte a un límite natural cercano (salto de línea o puntuación).
    """
    if start >= len(text):
        return len(text)

    min_idx = start + 1
    max_idx = len(text) - 1

    if min_idx > max_idx:
        return len(text)

    target = max(min_idx, min(target, max_idx))
    window = 120

    for radius in range(window + 1):
        left = target - radius
        right = target + radius

        if left >= min_idx and _is_natural_break(text, left):
            return left
        if right <= max_idx and _is_natural_break(text, right):
            return right

    return target


def _is_natural_break(text: str, idx: int) -> bool:
    prev_char = text[idx - 1] if idx > 0 else ""
    curr_char = text[idx] if idx < len(text) else ""

    if prev_char == "\n":
        return True

    if prev_char in ".?!;:" and (curr_char.isspace() or curr_char == "\n"):
        return True

    return False


def _build_fix_chunk_payload(
    source_chunk: str,
    draft_chunk: str,
    source_lang: str,
    target_lang: str,
) -> str:
    """
    Payload de usuario para modo fix.
    Separa explícitamente original vs traducción existente para cualquier LLM.
    """
    source_text = (source_chunk or "").strip() or "[VACÍO]"
    draft_text  = (draft_chunk or "").strip() or "[VACÍO]"

    return (
        f"TEXTO ORIGINAL ({source_lang}):\n"
        f"<original>\n{source_text}\n</original>\n\n"
        f"TRADUCCIÓN EXISTENTE ({target_lang}):\n"
        f"<traduccion_existente>\n{draft_text}\n</traduccion_existente>"
    )


def _build_polish_chunk_payload(draft_chunk: str, target_lang: str) -> str:
    """
    Payload de usuario para fix-style.
    """
    draft_text = (draft_chunk or "").strip() or "[VACÍO]"
    return (
        f"TRADUCCIÓN EXISTENTE ({target_lang}):\n"
        f"<traduccion_existente>\n{draft_text}\n</traduccion_existente>"
    )


def _scene_digest(text: str, max_chars: int = 280) -> str:
    """
    Resumen corto y determinístico para continuidad cuando no se usa extractor IA.
    """
    import re

    clean = " ".join((text or "").split()).strip()
    if not clean:
        return "Sin contenido suficiente para resumir la escena."

    sentences = re.split(r"(?<=[.!?])\s+", clean)
    summary = " ".join(s for s in sentences[:2] if s).strip()

    if not summary:
        summary = clean

    if len(summary) > max_chars:
        summary = summary[: max_chars - 1].rstrip() + "…"

    return summary


def _has_unenriched_candidates(
    candidates: dict[str, str],
    bible: BookBible,
) -> bool:
    """
    Retorna True si hay candidatos nuevos (no en Bible) o con descripción
    genérica (añadidos por el detector local pero sin enriquecer por IA).
    Garantiza que el extractor IA enriquezca personajes en el mismo chunk
    donde aparecen por primera vez, no varios chunks después.
    """
    if not candidates:
        return False
    return any(
        name not in bible.characters
        or bible.characters[name] == _GENERIC_DESC
        for name in candidates
    )


_DEFAULT_VOICE = "narrador en tercera persona, tiempo pasado"


def _build_local_bible_update(
    source_text: str,
    translated_text: str,
    notes: str,
    existing_voice: str,
    detected_characters: Optional[dict[str, str]] = None,
) -> BibleUpdate:
    """
    Update determinístico de Bible para garantizar continuidad y progreso
    aunque el extractor IA no responda.

    Los personajes se reciben ya detectados (detected_characters) para evitar
    llamar a extract_character_mentions dos veces por chunk. Cuando el extractor
    IA corre, sus personajes validados/enriquecidos sobreescribirán estos en el merge.

    La voz solo se infiere localmente mientras no haya una voz enriquecida por IA.
    Una vez el AI establece una voz con detalle de tono, no se sobreescribe con
    la inferencia local (que siempre devuelve el formato simple).
    """
    # Bootstrap de voz: solo cuando no hay voz o es la genérica inicial.
    # Evita que la heurística local destruya la voz enriquecida que el AI establece.
    voice = (
        _infer_narrative_voice(translated_text, existing_voice)
        if not existing_voice or existing_voice == _DEFAULT_VOICE
        else None
    )
    return BibleUpdate(
        voice      = voice,
        characters = detected_characters or {},
        decisions  = _extract_style_decisions(notes),
        last_scene = _scene_digest(translated_text),
    )


def _merge_bible_updates(
    local_update: BibleUpdate,
    extracted_update: Optional[BibleUpdate],
) -> BibleUpdate:
    if extracted_update is None:
        return local_update

    merged_glossary = dict(local_update.glossary)
    merged_glossary.update(extracted_update.glossary)

    merged_characters = dict(local_update.characters)
    merged_characters.update(extracted_update.characters)

    # Eliminar del merge los nombres que la IA rechazó explícitamente
    for rejected_name in extracted_update.rejected:
        merged_characters.pop(rejected_name, None)

    merged_decisions: list[str] = []
    for decision in local_update.decisions + extracted_update.decisions:
        if decision and decision not in merged_decisions:
            merged_decisions.append(decision)

    # Priorizamos IA cuando exista, manteniendo fallback local.
    return BibleUpdate(
        voice      = extracted_update.voice or local_update.voice,
        glossary   = merged_glossary,
        characters = merged_characters,
        decisions  = merged_decisions,
        last_scene = extracted_update.last_scene or local_update.last_scene,
        rejected   = extracted_update.rejected,
    )

def _infer_narrative_voice(text: str, fallback: str) -> str:
    """
    Infiere voz narrativa de forma aproximada para mantener consistencia.
    """
    import re

    lowered = f" {text.lower()} "
    first_person_hits = sum(
        1 for token in [" yo ", " me ", " mi ", " mí ", " conmigo ", " nosotros ", " nos "]
        if token in lowered
    )
    third_person_hits = sum(
        1 for token in [" él ", " ella ", " ellos ", " ellas ", " le ", " les ", " su ", " sus "]
        if token in lowered
    )

    person = "primera persona" if first_person_hits >= max(2, third_person_hits + 1) else "tercera persona"

    past_hits = len(re.findall(r"\b(fue|era|estaba|había|dijo|pensó|miró|entró)\b", lowered))
    present_hits = len(re.findall(r"\b(es|está|dice|piensa|mira|entra|hay)\b", lowered))

    tense = "tiempo pasado" if past_hits >= present_hits else "tiempo presente"

    inferred = f"narrador en {person}, {tense}"
    return inferred if text.strip() else fallback


_DECISION_KEYWORDS = {
    "mantener", "preservar", "adaptar", "traducir", "estilo", "tono",
    "registro", "consistencia", "voz", "narrador", "tiempo verbal",
    "perspectiva", "tutear", "ustedear", "nombre propio", "término",
}


def _extract_style_decisions(notes: str, max_items: int = 5) -> list[str]:
    """
    Extrae decisiones de estilo breves desde notes cuando existan pistas explícitas.
    Reconoce una lista más amplia de señales de decisiones de traducción.
    """
    if not notes:
        return []

    decisions: list[str] = []
    for sentence in notes.split("."):
        fragment = sentence.strip()
        if not fragment:
            continue
        lowered = fragment.lower()
        if any(k in lowered for k in _DECISION_KEYWORDS):
            decisions.append(fragment)
        if len(decisions) >= max_items:
            break

    return decisions


def _slugify(title: str) -> str:
    """Convierte el título en un nombre de archivo seguro."""
    import re
    slug = title.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s]+", "_", slug)
    return slug
