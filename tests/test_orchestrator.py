# tests/test_orchestrator.py
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, call
from tenlib.orchestrator import Orchestrator, BookAlreadyDoneError
from tenlib.reconstructor import Reconstructor
from tenlib.storage.repository import Repository
from tenlib.storage.models import BookMode, BookStatus, ChunkStatus, StoredBook, StoredChunk
from tenlib.router.models import ModelResponse
from tenlib.router.router import AllModelsExhaustedError


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture
def repo():
    r = Repository(db_path=":memory:")
    yield r
    r.close()


def make_mock_router(translation="Texto traducido", confidence=0.95):
    router = MagicMock()
    router.translate.return_value = ModelResponse(
        translation   = translation,
        confidence    = confidence,
        notes         = "ok",
        model_used    = "gemini",
        tokens_input  = 100,
        tokens_output = 120,
    )
    return router


def make_mock_chunk(index: int, book_id: int = 1) -> StoredChunk:
    return StoredChunk(
        id              = index + 1,
        book_id         = book_id,
        chunk_index     = index,
        original        = f"Original text {index}",
        status          = ChunkStatus.PENDING,
        source_section  = 0,
        token_estimated = 500,
    )


def make_orchestrator(repo, router, tmp_path):
    """Ensambla un Orchestrator con todos los mocks necesarios."""

    # Mock del parser_factory
    mock_raw_book = MagicMock()
    mock_raw_book.sections = ["Sección uno", "Sección dos"]

    mock_parser = MagicMock()
    mock_parser.parse.return_value = mock_raw_book

    mock_factory = MagicMock()
    mock_factory.get_parser.return_value = mock_parser
    mock_factory.parse.return_value = mock_raw_book

    # Mock del chunker
    mock_chunks = [MagicMock() for _ in range(10)]
    for i, c in enumerate(mock_chunks):
        c.index         = i
        c.original      = f"Chunk original {i}"
        c.token_estimated = 900
        c.token_estimate = 900
        c.source_section = 0

    mock_chunker = MagicMock()
    mock_chunker.chunk.return_value = mock_chunks

    return Orchestrator(
        repo            = repo,
        parser_factory  = mock_factory,
        chunker         = mock_chunker,
        router          = router,
        reconstructor   = Reconstructor(repo, output_dir=tmp_path),
    )


def make_orchestrator_fix(repo, router, tmp_path, chunks: int = 6):
    """Orchestrator para modo fix con parser/chunker deterministas."""
    source_raw = MagicMock()
    source_raw.sections = ["Source section one", "Source section two"]

    draft_raw = MagicMock()
    draft_raw.sections = ["Draft section one", "Draft section two"]

    source_chunks = [MagicMock() for _ in range(chunks)]
    for i, c in enumerate(source_chunks):
        c.index = i
        c.original = f"Source chunk {i}"
        c.token_estimated = 700
        c.source_section = 0 if i < (chunks // 2) else 1

    def parse_side_effect(path: str):
        if path.endswith("original.txt"):
            return source_raw
        if path.endswith("traduccion.txt"):
            return draft_raw
        raise AssertionError(f"Ruta inesperada para parse: {path}")

    mock_factory = MagicMock()
    mock_factory.parse.side_effect = parse_side_effect

    mock_chunker = MagicMock()
    mock_chunker.chunk.return_value = source_chunks

    return Orchestrator(
        repo            = repo,
        parser_factory  = mock_factory,
        chunker         = mock_chunker,
        router          = router,
        reconstructor   = Reconstructor(repo, output_dir=tmp_path),
    )


# ------------------------------------------------------------------
# Tests principales
# ------------------------------------------------------------------

class TestOrchestrator:

    def test_pipeline_completo_libro_nuevo(self, repo, tmp_path):
        """Pipeline de punta a punta con libro nuevo."""
        router = make_mock_router()
        orch   = make_orchestrator(repo, router, tmp_path)

        # Necesitamos un archivo real (el hash se calcula del archivo)
        book_file = tmp_path / "libro.txt"
        book_file.write_text("Contenido de prueba")

        result = orch.run(str(book_file), "en", "es")

        assert result.total_chunks == 10
        assert result.translated   == 10
        assert result.flagged      == 0
        assert result.was_resumed  is False
        assert result.output_path.exists()

    def test_reanudacion_no_reprocesa_chunks_done(self, repo, tmp_path):
        """
        El test más importante del MVP:
        si 5 chunks ya están DONE, el router solo es llamado 5 veces.

        Nota: el orchestrator captura todas las excepciones por chunk y nunca
        aborta el pipeline. Para simular una reanudación realizamos una primera
        ejecución completa y luego reseteamos 5 chunks a PENDING directamente
        en la BD, emulando lo que ocurriría si el proceso se interrumpiera.
        """
        router = make_mock_router()
        orch   = make_orchestrator(repo, router, tmp_path)

        book_file = tmp_path / "libro.txt"
        book_file.write_text("Contenido de prueba")

        # Primera ejecución completa (10 chunks → DONE)
        orch.run(str(book_file), "en", "es")

        # Simulamos interrupción: resetear 5 chunks a PENDING
        all_chunks = repo.get_all_chunks(1)
        with repo._conn:
            for c in all_chunks[:5]:
                repo._conn.execute(
                    "UPDATE chunks SET status='pending', translated=NULL WHERE id=?",
                    (c.id,),
                )
        repo.update_book_status(1, BookStatus.IN_PROGRESS)

        router.translate.reset_mock()

        # Segunda ejecución — solo se deben procesar los 5 pendientes
        result = orch.run(str(book_file), "en", "es")

        assert router.translate.call_count == 5
        assert result.translated == 10
        assert result.was_resumed is True

    def test_libro_ya_done_lanza_error(self, repo, tmp_path):
        router = make_mock_router()
        orch   = make_orchestrator(repo, router, tmp_path)

        book_file = tmp_path / "libro.txt"
        book_file.write_text("Contenido")

        orch.run(str(book_file), "en", "es")

        with pytest.raises(BookAlreadyDoneError):
            orch.run(str(book_file), "en", "es")

    def test_error_en_chunk_individual_no_detiene_pipeline(self, repo, tmp_path):
        """Un fallo en un chunk lo flaggea y el pipeline continúa."""
        router = make_mock_router()

        # El chunk 3 falla, el resto pasa
        def translate_side_effect(*args, **kwargs):
            call_count = router.translate.call_count
            if call_count == 4:   # 4ta llamada (chunk index 3)
                raise ConnectionError("Error de red simulado")
            return ModelResponse(
                translation   = "Traducido",
                confidence    = 0.95,
                notes         = "ok",
                model_used    = "gemini",
                tokens_input  = 100,
                tokens_output = 120,
            )

        router.translate.side_effect = translate_side_effect

        orch = make_orchestrator(repo, router, tmp_path)
        book_file = tmp_path / "libro.txt"
        book_file.write_text("Contenido")

        result = orch.run(str(book_file), "en", "es")

        assert result.flagged    == 1
        assert result.translated == 9

    def test_all_models_exhausted_pausa_pipeline(self, repo, tmp_path):
        """Si todos los modelos se agotan, el pipeline se pausa (no explota)."""
        router = MagicMock()
        router.translate.side_effect = AllModelsExhaustedError("Sin quota")

        orch = make_orchestrator(repo, router, tmp_path)
        book_file = tmp_path / "libro.txt"
        book_file.write_text("Contenido")

        # No lanza excepción — termina gracefully con chunks en PENDING
        result = orch.run(str(book_file), "en", "es")

        pending = repo.get_pending_chunks(result.book_id)
        # AllModelsExhaustedError hace break sin flaggear el chunk → todos quedan PENDING
        assert len(pending) == 10
        book = repo.get_book_by_id(result.book_id)
        assert book.status == BookStatus.IN_PROGRESS

    def test_archivo_no_encontrado(self, repo, tmp_path):
        router = make_mock_router()
        orch   = make_orchestrator(repo, router, tmp_path)

        with pytest.raises(FileNotFoundError):
            orch.run("/no/existe.txt", "en", "es")

    def test_confianza_baja_produce_chunk_flaggeado(self, repo, tmp_path):
        """Chunks con confidence < 0.75 quedan FLAGGED para revisión."""
        router = make_mock_router(confidence=0.60)   # bajo el umbral
        orch   = make_orchestrator(repo, router, tmp_path)

        book_file = tmp_path / "libro.txt"
        book_file.write_text("Contenido")

        result = orch.run(str(book_file), "en", "es")

        # Todos traducidos pero flaggeados por baja confianza
        assert result.flagged == 10
        all_chunks = repo.get_all_chunks(result.book_id)
        assert all(c.status == ChunkStatus.FLAGGED for c in all_chunks)

    def test_translate_actualiza_bible_en_cada_chunk(self, repo, tmp_path):
        router = make_mock_router(translation="María habló. Yo recordé.", confidence=0.9)
        orch = make_orchestrator(repo, router, tmp_path)

        book_file = tmp_path / "libro.txt"
        book_file.write_text("Contenido")

        result = orch.run(str(book_file), "en", "es")

        row = repo._conn.execute(
            "SELECT COUNT(*) as c FROM bible WHERE book_id = ?",
            (result.book_id,),
        ).fetchone()
        assert row["c"] >= 11  # 1 inicial + al menos 10 updates


class TestOrchestratorFix:

    def test_fix_pipeline_completo(self, repo, tmp_path):
        router = make_mock_router(translation="Texto corregido", confidence=0.93)
        orch = make_orchestrator_fix(repo, router, tmp_path, chunks=6)

        original = tmp_path / "original.txt"
        draft = tmp_path / "traduccion.txt"
        original.write_text("Texto original")
        draft.write_text("Texto traducido previo")

        result = orch.run_fix(
            original_path=str(original),
            translation_path=str(draft),
            source_lang="en",
            target_lang="es",
        )

        assert result.total_chunks == 6
        assert result.translated == 6
        assert result.flagged == 0
        assert result.was_resumed is False
        assert result.output_path.exists()

    def test_fix_payload_incluye_original_y_borrador(self, repo, tmp_path):
        router = make_mock_router(translation="Texto corregido", confidence=0.93)
        orch = make_orchestrator_fix(repo, router, tmp_path, chunks=2)

        original = tmp_path / "original.txt"
        draft = tmp_path / "traduccion.txt"
        original.write_text("Texto original")
        draft.write_text("Texto traducido previo")

        orch.run_fix(
            original_path=str(original),
            translation_path=str(draft),
            source_lang="en",
            target_lang="es",
        )

        first_payload = router.translate.call_args_list[0].args[0]
        assert "TEXTO ORIGINAL (en)" in first_payload
        assert "TRADUCCIÓN EXISTENTE (es)" in first_payload

    def test_fix_reanudacion_no_reprocesa_chunks_done(self, repo, tmp_path):
        router = make_mock_router(translation="Texto corregido", confidence=0.93)
        orch = make_orchestrator_fix(repo, router, tmp_path, chunks=6)

        original = tmp_path / "original.txt"
        draft = tmp_path / "traduccion.txt"
        original.write_text("Texto original")
        draft.write_text("Texto traducido previo")

        orch.run_fix(
            original_path=str(original),
            translation_path=str(draft),
            source_lang="en",
            target_lang="es",
        )

        all_chunks = repo.get_all_chunks(1)
        with repo._conn:
            for c in all_chunks[:2]:
                repo._conn.execute(
                    "UPDATE chunks SET status='pending', translated=NULL WHERE id=?",
                    (c.id,),
                )
        repo.update_book_status(1, BookStatus.IN_PROGRESS)

        router.translate.reset_mock()
        result = orch.run_fix(
            original_path=str(original),
            translation_path=str(draft),
            source_lang="en",
            target_lang="es",
        )

        assert router.translate.call_count == 2
        assert result.was_resumed is True


class TestOrchestratorFixStyle:

    def test_fix_style_pipeline_completo(self, repo, tmp_path):
        router = make_mock_router(translation="Texto pulido", confidence=0.91)
        orch = make_orchestrator(repo, router, tmp_path)

        draft = tmp_path / "traduccion.txt"
        draft.write_text("Texto traducido previo")

        result = orch.run_fix_style(
            translation_path=str(draft),
            source_lang="auto",
            target_lang="es",
        )

        assert result.total_chunks == 10
        assert result.translated == 10
        assert result.flagged == 0
        assert result.was_resumed is False

    def test_fix_style_payload_no_requiere_original(self, repo, tmp_path):
        router = make_mock_router(translation="Texto pulido", confidence=0.91)
        orch = make_orchestrator(repo, router, tmp_path)

        draft = tmp_path / "traduccion.txt"
        draft.write_text("Texto traducido previo")

        orch.run_fix_style(
            translation_path=str(draft),
            source_lang="auto",
            target_lang="es",
        )

        first_payload = router.translate.call_args_list[0].args[0]
        assert "TRADUCCIÓN EXISTENTE (es)" in first_payload
        assert "TEXTO ORIGINAL" not in first_payload

    def test_fix_style_actualiza_bible_en_cada_chunk(self, repo, tmp_path):
        router = make_mock_router(translation="Primera frase. Segunda frase.", confidence=0.91)
        orch = make_orchestrator(repo, router, tmp_path)

        draft = tmp_path / "traduccion.txt"
        draft.write_text("Texto traducido previo")

        result = orch.run_fix_style(
            translation_path=str(draft),
            source_lang="auto",
            target_lang="es",
        )

        row = repo._conn.execute(
            "SELECT COUNT(*) as c FROM bible WHERE book_id = ?",
            (result.book_id,),
        ).fetchone()
        assert row["c"] >= 11  # 1 inicial + al menos 10 updates

    def test_fix_style_puebla_personajes_y_voz_narrativa(self, repo, tmp_path):
        router = make_mock_router(
            translation=(
                "María miró a Diego. Yo me quedé en silencio. "
                "María volvió a mirar a Diego."
            ),
            confidence=0.91,
        )
        # notes vienen de make_mock_router como "ok"; forzamos pistas de estilo
        router.translate.return_value.notes = "mantener tono íntimo y estilo confesional"
        orch = make_orchestrator(repo, router, tmp_path)

        draft = tmp_path / "traduccion.txt"
        draft.write_text("Texto traducido previo")

        result = orch.run_fix_style(
            translation_path=str(draft),
            source_lang="auto",
            target_lang="es",
        )

        bible = repo.get_latest_bible(result.book_id)
        assert bible is not None
        assert "María" in bible.characters
        assert "Diego" in bible.characters
        assert "primera persona" in bible.voice
        assert any("tono" in d.lower() for d in bible.decisions)

    def test_fix_style_no_agrega_ruido_como_personajes(self, repo, tmp_path):
        router = make_mock_router(
            translation=(
                "Estaba oscuro. Eso fue todo. "
                "Rimuru avanzó. Rimuru respiró hondo."
            ),
            confidence=0.91,
        )
        orch = make_orchestrator(repo, router, tmp_path)

        draft = tmp_path / "traduccion.txt"
        draft.write_text("Texto traducido previo")

        result = orch.run_fix_style(
            translation_path=str(draft),
            source_lang="auto",
            target_lang="es",
        )
        bible = repo.get_latest_bible(result.book_id)
        assert bible is not None
        assert "Rimuru" in bible.characters
        assert "Estaba" not in bible.characters
        assert "Eso" not in bible.characters

    def test_fix_style_permite_personaje_ultima_si_hay_contexto(self, repo, tmp_path):
        router = make_mock_router(
            translation=(
                "Ultima atacó primero. "
                "Luego Ultima dijo que no retrocedería."
            ),
            confidence=0.91,
        )
        orch = make_orchestrator(repo, router, tmp_path)

        draft = tmp_path / "traduccion.txt"
        draft.write_text("Texto traducido previo")

        result = orch.run_fix_style(
            translation_path=str(draft),
            source_lang="auto",
            target_lang="es",
        )
        bible = repo.get_latest_bible(result.book_id)
        assert bible is not None
        assert "Ultima" in bible.characters

    def test_fix_style_crea_bible_base_aun_si_falla_por_quota(self, repo, tmp_path):
        router = MagicMock()
        router.translate.side_effect = AllModelsExhaustedError("Sin quota")
        orch = make_orchestrator(repo, router, tmp_path)

        draft = tmp_path / "traduccion.txt"
        draft.write_text("Texto traducido previo")

        result = orch.run_fix_style(
            translation_path=str(draft),
            source_lang="auto",
            target_lang="es",
        )

        book = repo.get_book_by_id(result.book_id)
        assert book.status == BookStatus.IN_PROGRESS
        assert repo.get_latest_bible(result.book_id) is not None

    def test_fix_style_reanuda_si_status_done_quedo_inconsistente(self, repo, tmp_path):
        router_pause = MagicMock()
        router_pause.translate.side_effect = AllModelsExhaustedError("Sin quota")
        orch_pause = make_orchestrator(repo, router_pause, tmp_path)

        draft = tmp_path / "traduccion.txt"
        draft.write_text("Texto traducido previo")

        first = orch_pause.run_fix_style(
            translation_path=str(draft),
            source_lang="auto",
            target_lang="es",
        )
        repo.update_book_status(first.book_id, BookStatus.DONE)  # legacy inconsistente

        router_resume = make_mock_router(translation="Texto pulido", confidence=0.91)
        orch_resume = make_orchestrator(repo, router_resume, tmp_path)

        resumed = orch_resume.run_fix_style(
            translation_path=str(draft),
            source_lang="auto",
            target_lang="es",
        )

        assert resumed.was_resumed is True
        assert resumed.translated > 0


# ------------------------------------------------------------------
# Tests del Reconstructor
# ------------------------------------------------------------------

class TestReconstructor:

    def test_output_contiene_todas_las_traducciones(self, repo, tmp_path):
        book_id = repo.create_book("Test", "hash_rec", source_lang="en", target_lang="es")
        chunks  = [MagicMock() for _ in range(3)]
        for i, c in enumerate(chunks):
            c.index = i; c.original = f"orig {i}"; c.token_estimate = 500
            c.source_section = 0
        repo.save_chunks(book_id, chunks)

        stored = repo.get_all_chunks(book_id)
        for c in stored:
            repo.update_chunk_translation(c.id, f"traducción {c.chunk_index}", "gemini", 0.9)

        rec    = Reconstructor(repo, output_dir=tmp_path)
        output = rec.build(book_id, "output.txt")

        content = output.read_text(encoding="utf-8")
        for i in range(3):
            assert f"traducción {i}" in content

    def test_chunk_flaggeado_usa_original_con_marcador(self, repo, tmp_path):
        book_id = repo.create_book("Test", "hash_flag", source_lang="en", target_lang="es")
        chunks  = [MagicMock()]
        chunks[0].index = 0; chunks[0].original = "texto sin traducir"
        chunks[0].token_estimate = 500; chunks[0].source_section = 0
        repo.save_chunks(book_id, chunks)

        stored = repo.get_all_chunks(book_id)
        repo.flag_chunk(stored[0].id, ["error de red"])

        rec     = Reconstructor(repo, output_dir=tmp_path)
        output  = rec.build(book_id, "output.txt")
        content = output.read_text(encoding="utf-8")

        assert "PENDIENTE DE REVISIÓN" in content
        assert "texto sin traducir"    in content
