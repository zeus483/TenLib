# storage/repository.py
import json
import logging
import sqlite3
from datetime import date, datetime, timezone
from numbers import Integral
from typing import Optional

from tenlib.storage.db import get_connection, init_schema
from tenlib.storage.models import (
    BookMode, BookStatus, ChunkStatus,
    StoredBook, StoredChunk,
)

logger = logging.getLogger(__name__)


class Repository:
    """
    Única interfaz entre el resto de la aplicación y SQLite.
    Recibe un db_path para facilitar el testing con :memory:.
    """

    def __init__(self, db_path: str | None = None):
        self._conn = get_connection(db_path)
        init_schema(self._conn)

    # ------------------------------------------------------------------
    # Books
    # ------------------------------------------------------------------

    def create_book(
        self,
        title:       str,
        file_hash:   str,
        mode:        BookMode = BookMode.TRANSLATE,
        source_lang: str | None = None,
        target_lang: str | None = None,
    ) -> int:
        """
        Inserta un libro nuevo y devuelve su id.
        Si el hash ya existe lanza IntegrityError — el caller decide qué hacer.
        """
        created_at = datetime.now(timezone.utc).isoformat()
        with self._conn:
            cursor = self._conn.execute(
                """
                INSERT INTO books (title, source_lang, target_lang, mode, status, file_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (title, source_lang, target_lang, mode.value,
                 BookStatus.IN_PROGRESS.value, file_hash, created_at),
            )
        return cursor.lastrowid  # type: ignore[return-value]

    def get_book_by_hash(self, file_hash: str) -> StoredBook | None:
        row = self._conn.execute(
            "SELECT * FROM books WHERE file_hash = ?", (file_hash,)
        ).fetchone()
        return self._row_to_book(row) if row else None

    def get_book_by_id(self, book_id: int) -> StoredBook | None:
        row = self._conn.execute(
            "SELECT * FROM books WHERE id = ?", (book_id,)
        ).fetchone()
        return self._row_to_book(row) if row else None

    def update_book_status(self, book_id: int, status: BookStatus) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE books SET status = ? WHERE id = ?",
                (status.value, book_id),
            )

    # ------------------------------------------------------------------
    # Chunks
    # ------------------------------------------------------------------

    def save_chunks(self, book_id: int, chunks: list) -> None:
        """
        Bulk insert de chunks. Usa INSERT OR IGNORE para ser idempotente:
        si el proceso se interrumpe y se relanza, no explota por el UNIQUE.
        """
        def _as_int(value) -> int | None:
            if isinstance(value, Integral) and not isinstance(value, bool):
                return int(value)
            return None

        rows = [
            (
                book_id,
                chunk.index,
                chunk.original,
                _as_int(getattr(chunk, "token_estimated", None))
                or _as_int(getattr(chunk, "token_estimate", None)),
                chunk.source_section,
                ChunkStatus.PENDING.value,
                "[]",
            )
            for chunk in chunks
        ]
        with self._conn:
            self._conn.executemany(
                """
                INSERT OR IGNORE INTO chunks
                    (book_id, chunk_index, original, token_estimated,
                     source_section, status, flags)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def get_pending_chunks(self, book_id: int) -> list[StoredChunk]:
        rows = self._conn.execute(
            """
            SELECT * FROM chunks
            WHERE book_id = ? AND status = ?
            ORDER BY chunk_index ASC
            """,
            (book_id, ChunkStatus.PENDING.value),
        ).fetchall()
        return [self._row_to_chunk(r) for r in rows]

    def get_all_chunks(self, book_id: int) -> list[StoredChunk]:
        rows = self._conn.execute(
            "SELECT * FROM chunks WHERE book_id = ? ORDER BY chunk_index ASC",
            (book_id,),
        ).fetchall()
        return [self._row_to_chunk(r) for r in rows]

    def update_chunk_translation(
        self,
        chunk_id:   int,
        translated: str,
        model_used: str,
        confidence: float,
        status:     ChunkStatus = ChunkStatus.DONE,
    ) -> None:
        """
        Actualiza traducción + status en una sola transacción.
        Atómico: o se guarda todo o no se guarda nada.
        """
        with self._conn:
            self._conn.execute(
                """
                UPDATE chunks
                SET translated = ?, model_used = ?, confidence = ?, status = ?
                WHERE id = ?
                """,
                (translated, model_used, confidence, status.value, chunk_id),
            )

    def flag_chunk(self, chunk_id: int, flags: list[str]) -> None:
        """Marca un chunk con flags y lo pone en FLAGGED."""
        with self._conn:
            self._conn.execute(
                "UPDATE chunks SET flags = ?, status = ? WHERE id = ?",
                (json.dumps(flags), ChunkStatus.FLAGGED.value, chunk_id),
            )

    # ------------------------------------------------------------------
    # Quota
    # ------------------------------------------------------------------

    def add_token_usage(self, model: str, tokens: int) -> None:
        """
        Upsert: si ya existe el registro de hoy lo incrementa,
        si no existe lo crea.
        """
        today = date.today().isoformat()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO quota_usage (model, date, tokens_used)
                VALUES (?, ?, ?)
                ON CONFLICT (model, date)
                DO UPDATE SET tokens_used = tokens_used + excluded.tokens_used
                """,
                (model, today, tokens),
            )

    def get_token_usage_today(self, model: str) -> int:
        today = date.today().isoformat()
        row = self._conn.execute(
            "SELECT tokens_used FROM quota_usage WHERE model = ? AND date = ?",
            (model, today),
        ).fetchone()
        return row["tokens_used"] if row else 0

    # ------------------------------------------------------------------
    # Bible
    # ------------------------------------------------------------------

    def save_bible(self, book_id: int, bible: "BookBible") -> int:
        """
        Guarda una nueva versión de la Bible.
        Siempre inserta una fila nueva (versionado inmutable).
        Retorna el número de versión asignado.
        """
        from datetime import datetime, timezone
        updated_at = datetime.now(timezone.utc).isoformat()

        # Obtener versión actual para incrementar
        row = self._conn.execute(
            "SELECT MAX(version) as max_v FROM bible WHERE book_id = ?",
            (book_id,),
        ).fetchone()

        next_version = (row["max_v"] or 0) + 1

        with self._conn:
            self._conn.execute(
                """
                INSERT INTO bible (book_id, version, content_json, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (book_id, next_version, bible.to_json(), updated_at),
            )

        return next_version

    def get_latest_bible(self, book_id: int) -> Optional["BookBible"]:
        """
        Carga la versión más reciente de la Bible para un libro.
        Devuelve None si todavía no existe (libro nuevo sin Bible).
        """
        from tenlib.context.bible import BookBible

        row = self._conn.execute(
            """
            SELECT content_json FROM bible
            WHERE book_id = ?
            ORDER BY version DESC
            LIMIT 1
            """,
            (book_id,),
        ).fetchone()

        if not row:
            return None

        try:
            return BookBible.from_json(row["content_json"])
        except Exception as e:
            logger.warning("Error deserializando Bible del libro %d: %s", book_id, e)
            return None

    # ------------------------------------------------------------------
    # Mapeo de rows a dataclasses
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_book(row: sqlite3.Row) -> StoredBook:
        return StoredBook(
            id=row["id"],
            title=row["title"],
            file_hash=row["file_hash"],
            mode=BookMode(row["mode"]),
            status=BookStatus(row["status"]),
            created_at=row["created_at"],
            source_lang=row["source_lang"],
            target_lang=row["target_lang"],
        )

    @staticmethod
    def _row_to_chunk(row: sqlite3.Row) -> StoredChunk:
        return StoredChunk(
            id=row["id"],
            book_id=row["book_id"],
            chunk_index=row["chunk_index"],
            original=row["original"],
            translated=row["translated"],
            model_used=row["model_used"],
            confidence=row["confidence"],
            token_estimated=row["token_estimated"],
            source_section=row["source_section"],
            status=ChunkStatus(row["status"]),
            flags=json.loads(row["flags"] or "[]"),
        )

    # ------------------------------------------------------------------
    # Cleanup (para tests)
    # ------------------------------------------------------------------

    def close(self) -> None:
        self._conn.close()
