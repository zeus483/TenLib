# tests/storage/test_repository.py
import pytest
from tenlib.storage.repository import Repository
from tenlib.storage.models import BookMode, BookStatus, ChunkStatus
from unittest.mock import MagicMock


@pytest.fixture
def repo():
    """Cada test tiene su propia DB en memoria — aislada, sin cleanup."""
    r = Repository(db_path=":memory:")
    yield r
    r.close()


@pytest.fixture
def sample_book_id(repo):
    return repo.create_book(
        title="El nombre del viento",
        file_hash="abc123",
        mode=BookMode.TRANSLATE,
        source_lang="en",
        target_lang="es",
    )


def make_mock_chunks(n: int):
    """Genera chunks mock con la interfaz mínima que espera save_chunks."""
    chunks = []
    for i in range(n):
        c = MagicMock()
        c.index = i
        c.original = f"Texto del chunk {i}."
        c.token_estimate = 1000
        c.source_section = 0
        chunks.append(c)
    return chunks


# ------------------------------------------------------------------
# Books
# ------------------------------------------------------------------

class TestBooks:

    def test_create_book_returns_id(self, repo):
        book_id = repo.create_book("Título", "hash1")
        assert isinstance(book_id, int)
        assert book_id > 0

    def test_get_book_by_hash_existente(self, repo):
        repo.create_book("Título", "hash_x", source_lang="en")
        book = repo.get_book_by_hash("hash_x")
        assert book is not None
        assert book.title == "Título"
        assert book.source_lang == "en"
        assert book.status == BookStatus.IN_PROGRESS

    def test_get_book_by_hash_inexistente_devuelve_none(self, repo):
        assert repo.get_book_by_hash("no_existe") is None

    def test_hash_duplicado_lanza_error(self, repo):
        import sqlite3
        repo.create_book("Libro A", "mismo_hash")
        with pytest.raises(sqlite3.IntegrityError):
            repo.create_book("Libro B", "mismo_hash")

    def test_update_book_status(self, repo, sample_book_id):
        repo.update_book_status(sample_book_id, BookStatus.DONE)
        book = repo.get_book_by_id(sample_book_id)
        assert book.status == BookStatus.DONE


# ------------------------------------------------------------------
# Chunks
# ------------------------------------------------------------------

class TestChunks:

    def test_save_chunks_bulk(self, repo, sample_book_id):
        chunks = make_mock_chunks(5)
        repo.save_chunks(sample_book_id, chunks)
        stored = repo.get_all_chunks(sample_book_id)
        assert len(stored) == 5

    def test_chunks_guardados_en_status_pending(self, repo, sample_book_id):
        repo.save_chunks(sample_book_id, make_mock_chunks(3))
        stored = repo.get_all_chunks(sample_book_id)
        assert all(c.status == ChunkStatus.PENDING for c in stored)

    def test_reanudacion_get_pending(self, repo, sample_book_id):
        """Si 7 de 10 están DONE, get_pending devuelve exactamente 3."""
        repo.save_chunks(sample_book_id, make_mock_chunks(10))
        all_chunks = repo.get_all_chunks(sample_book_id)

        for chunk in all_chunks[:7]:
            repo.update_chunk_translation(
                chunk.id, "traducción", "claude", 0.95
            )

        pending = repo.get_pending_chunks(sample_book_id)
        assert len(pending) == 3

    def test_save_chunks_es_idempotente(self, repo, sample_book_id):
        """Guardar los mismos chunks dos veces no duplica ni explota."""
        chunks = make_mock_chunks(5)
        repo.save_chunks(sample_book_id, chunks)
        repo.save_chunks(sample_book_id, chunks)  # segunda vez
        stored = repo.get_all_chunks(sample_book_id)
        assert len(stored) == 5

    def test_update_chunk_translation_atomico(self, repo, sample_book_id):
        """Traducción y status se guardan juntos — no puede quedar a medias."""
        repo.save_chunks(sample_book_id, make_mock_chunks(1))
        chunk = repo.get_all_chunks(sample_book_id)[0]

        repo.update_chunk_translation(chunk.id, "texto traducido", "gpt", 0.88)

        updated = repo.get_all_chunks(sample_book_id)[0]
        assert updated.translated == "texto traducido"
        assert updated.model_used == "gpt"
        assert updated.confidence == 0.88
        assert updated.status == ChunkStatus.DONE

    def test_flag_chunk(self, repo, sample_book_id):
        repo.save_chunks(sample_book_id, make_mock_chunks(1))
        chunk = repo.get_all_chunks(sample_book_id)[0]

        repo.flag_chunk(chunk.id, ["término_sin_glosario", "baja_confianza"])

        updated = repo.get_all_chunks(sample_book_id)[0]
        assert updated.status == ChunkStatus.FLAGGED
        assert "término_sin_glosario" in updated.flags

    def test_unique_constraint_chunk_index(self, repo, sample_book_id):
        """book_id + chunk_index no puede repetirse — la DB lo garantiza."""
        import sqlite3
        repo.save_chunks(sample_book_id, make_mock_chunks(1))
        with pytest.raises(sqlite3.IntegrityError):
            repo._conn.execute(
                "INSERT INTO chunks (book_id, chunk_index, original, status) VALUES (?, ?, ?, ?)",
                (sample_book_id, 0, "duplicado", "pending"),
            )
            repo._conn.commit()

    def test_chunks_ordenados_por_index(self, repo, sample_book_id):
        repo.save_chunks(sample_book_id, make_mock_chunks(5))
        stored = repo.get_all_chunks(sample_book_id)
        indices = [c.chunk_index for c in stored]
        assert indices == sorted(indices)


# ------------------------------------------------------------------
# Quota
# ------------------------------------------------------------------

class TestQuota:

    def test_uso_inicial_es_cero(self, repo):
        assert repo.get_token_usage_today("claude") == 0

    def test_add_token_usage(self, repo):
        repo.add_token_usage("claude", 1500)
        assert repo.get_token_usage_today("claude") == 1500

    def test_add_token_usage_acumula(self, repo):
        repo.add_token_usage("claude", 1000)
        repo.add_token_usage("claude", 500)
        repo.add_token_usage("claude", 200)
        assert repo.get_token_usage_today("claude") == 1700

    def test_quota_separada_por_modelo(self, repo):
        repo.add_token_usage("claude", 1000)
        repo.add_token_usage("gpt", 2000)
        assert repo.get_token_usage_today("claude") == 1000
        assert repo.get_token_usage_today("gpt") == 2000