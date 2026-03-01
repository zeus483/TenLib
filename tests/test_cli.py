# tests/test_cli.py
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from click.testing import CliRunner

from tenlib.cli import main
from tenlib.orchestrator import BookAlreadyDoneError, PipelineResult
from tenlib.router.router import AllModelsExhaustedError


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def book_file(tmp_path) -> Path:
    """Archivo .txt válido para los tests."""
    f = tmp_path / "libro.txt"
    f.write_text("Contenido de prueba para el libro.")
    return f


@pytest.fixture
def original_file(tmp_path) -> Path:
    f = tmp_path / "original.txt"
    f.write_text("Original de prueba.")
    return f


@pytest.fixture
def translation_file(tmp_path) -> Path:
    f = tmp_path / "traduccion.txt"
    f.write_text("Traducción previa de prueba.")
    return f


def make_pipeline_result(flagged: int = 0) -> PipelineResult:
    return PipelineResult(
        book_id      = 1,
        output_path  = Path("/tmp/libro_es.txt"),
        total_chunks = 10,
        translated   = 10 - flagged,
        flagged      = flagged,
        was_resumed  = False,
    )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def run_translate(runner, book, source="en", target="es"):
    """Shortcut para invocar el comando translate."""
    return runner.invoke(main, [
        "translate",
        "--book", str(book),
        "--from", source,
        "--to",   target,
    ])


def run_fix(runner, translation, original=None, target="es", source="auto"):
    """Shortcut para invocar el comando fix."""
    args = [
        "fix",
        "--translation", str(translation),
        "--from",        source,
        "--to",          target,
    ]
    if original is not None:
        args.extend(["--original", str(original)])
    return runner.invoke(main, args)


# ------------------------------------------------------------------
# Validaciones de entrada
# ------------------------------------------------------------------

class TestValidaciones:

    def test_archivo_inexistente(self, runner, tmp_path):
        result = run_translate(runner, tmp_path / "no_existe.txt")
        assert result.exit_code == 1
        assert "no encontrado" in result.output.lower()

    def test_formato_no_soportado(self, runner, tmp_path):
        f = tmp_path / "libro.docx"
        f.write_text("contenido")
        result = run_translate(runner, f)
        assert result.exit_code == 1
        assert "no soportado" in result.output.lower()

    def test_lang_vacio_rechazado(self, runner, book_file):
        result = runner.invoke(main, [
            "translate", "--book", str(book_file),
            "--from", "", "--to", "es",
        ])
        assert result.exit_code == 1
        assert "vacío" in result.output.lower()

    def test_mismo_idioma_rechazado(self, runner, book_file):
        result = run_translate(runner, book_file, source="es", target="es")
        assert result.exit_code == 1
        assert "mismo" in result.output.lower()

    def test_lang_con_caracteres_invalidos(self, runner, book_file):
        result = run_translate(runner, book_file, source="e$n", target="es")
        assert result.exit_code == 1

    def test_formatos_soportados_aceptados(self, runner, tmp_path):
        """Los tres formatos del MVP pasan la validación de extensión."""
        for ext in [".txt", ".epub", ".md"]:
            f = tmp_path / f"libro{ext}"
            f.write_bytes(b"contenido")

            with patch("tenlib.cli.build_orchestrator") as mock_factory:
                mock_orch = MagicMock()
                mock_orch.run.return_value = make_pipeline_result()
                mock_factory.return_value = mock_orch

                result = run_translate(runner, f)
                # No debe fallar por extensión
                assert "no soportado" not in result.output.lower(), \
                    f"Extensión {ext} rechazada incorrectamente"


# ------------------------------------------------------------------
# Flujo feliz
# ------------------------------------------------------------------

class TestFlujoFeliz:

    def test_llamada_valida_invoca_orchestrator_con_parametros_correctos(
        self, runner, book_file
    ):
        with patch("tenlib.cli.build_orchestrator") as mock_factory:
            mock_orch = MagicMock()
            mock_orch.run.return_value = make_pipeline_result()
            mock_factory.return_value = mock_orch

            result = run_translate(runner, book_file, source="en", target="es")

            assert result.exit_code == 0
            mock_orch.run.assert_called_once_with(
                file_path   = str(book_file),
                source_lang = "en",
                target_lang = "es",
            )

    def test_output_muestra_resumen(self, runner, book_file):
        with patch("tenlib.cli.build_orchestrator") as mock_factory:
            mock_orch = MagicMock()
            mock_orch.run.return_value = make_pipeline_result()
            mock_factory.return_value = mock_orch

            result = run_translate(runner, book_file)

            assert "completado" in result.output.lower()
            assert "10" in result.output     # total_chunks

    def test_chunks_flaggeados_aparecen_en_resumen(self, runner, book_file):
        with patch("tenlib.cli.build_orchestrator") as mock_factory:
            mock_orch = MagicMock()
            mock_orch.run.return_value = make_pipeline_result(flagged=3)
            mock_factory.return_value = mock_orch

            result = run_translate(runner, book_file)

            assert "3" in result.output
            assert "revisión" in result.output.lower()

    def test_resumen_muestra_pausado_si_hay_pending(self, runner, book_file):
        paused_result = PipelineResult(
            book_id=1,
            output_path=Path("/tmp/libro_es.txt"),
            total_chunks=10,
            translated=2,
            flagged=1,
            was_resumed=False,
        )
        with patch("tenlib.cli.build_orchestrator") as mock_factory:
            mock_orch = MagicMock()
            mock_orch.run.return_value = paused_result
            mock_factory.return_value = mock_orch

            result = run_translate(runner, book_file)

            assert "pausado" in result.output.lower()
            assert "pendientes" in result.output.lower()

    def test_lang_codes_se_normalizan_a_lowercase(self, runner, book_file):
        with patch("tenlib.cli.build_orchestrator") as mock_factory:
            mock_orch = MagicMock()
            mock_orch.run.return_value = make_pipeline_result()
            mock_factory.return_value = mock_orch

            runner.invoke(main, [
                "translate", "--book", str(book_file),
                "--from", "EN", "--to", "ES",     # mayúsculas
            ])

            call_kwargs = mock_orch.run.call_args.kwargs
            assert call_kwargs["source_lang"] == "en"
            assert call_kwargs["target_lang"] == "es"


class TestFixCommand:

    def test_fix_invoca_orchestrator_con_parametros_correctos(
        self, runner, translation_file, original_file
    ):
        with patch("tenlib.cli.build_orchestrator") as mock_factory:
            mock_orch = MagicMock()
            mock_orch.run_fix.return_value = make_pipeline_result()
            mock_factory.return_value = mock_orch

            result = run_fix(runner, translation_file, original_file, target="es")

            assert result.exit_code == 0
            mock_orch.run_fix.assert_called_once_with(
                original_path    = str(original_file),
                translation_path = str(translation_file),
                source_lang      = "auto",
                target_lang      = "es",
            )

    def test_fix_sin_original_invoca_fix_style(
        self, runner, translation_file
    ):
        with patch("tenlib.cli.build_orchestrator") as mock_factory:
            mock_orch = MagicMock()
            mock_orch.run_fix_style.return_value = make_pipeline_result()
            mock_factory.return_value = mock_orch

            result = run_fix(runner, translation_file, original=None, target="es")

            assert result.exit_code == 0
            mock_orch.run_fix_style.assert_called_once_with(
                translation_path = str(translation_file),
                source_lang      = "auto",
                target_lang      = "es",
            )

    def test_fix_muestra_resumen(self, runner, translation_file, original_file):
        with patch("tenlib.cli.build_orchestrator") as mock_factory:
            mock_orch = MagicMock()
            mock_orch.run_fix.return_value = make_pipeline_result(flagged=2)
            mock_factory.return_value = mock_orch

            result = run_fix(runner, translation_file, original_file)

            assert "completado" in result.output.lower()
            assert "revisión" in result.output.lower()

    def test_fix_valida_archivos(self, runner, tmp_path):
        missing = tmp_path / "missing.txt"
        existing = tmp_path / "ok.txt"
        existing.write_text("ok")

        result = run_fix(runner, missing, original=existing)
        assert result.exit_code == 1
        assert "no encontrado" in result.output.lower()

    def test_fix_sin_original_solo_valida_translation(self, runner, tmp_path):
        missing = tmp_path / "missing.txt"
        result = run_fix(runner, missing, original=None)
        assert result.exit_code == 1
        assert "no encontrado" in result.output.lower()


# ------------------------------------------------------------------
# Manejo de errores conocidos
# ------------------------------------------------------------------

class TestManejoErrores:

    def test_book_already_done_muestra_confirmacion(self, runner, book_file):
        with patch("tenlib.cli.build_orchestrator") as mock_factory:
            mock_orch = MagicMock()
            mock_orch.run.side_effect = BookAlreadyDoneError("Ya procesado")
            mock_factory.return_value = mock_orch

            # Responde "N" a la confirmación
            result = runner.invoke(
                main,
                ["translate", "--book", str(book_file), "--from", "en", "--to", "es"],
                input="N\n",
            )

            assert "ya fue traducido" in result.output.lower()

    def test_all_models_exhausted_muestra_mensaje_claro(self, runner, book_file):
        with patch("tenlib.cli.build_orchestrator") as mock_factory:
            mock_orch = MagicMock()
            mock_orch.run.side_effect = AllModelsExhaustedError("Sin quota")
            mock_factory.return_value = mock_orch

            result = run_translate(runner, book_file)

            assert result.exit_code == 2
            assert "sin modelos" in result.output.lower()

    def test_keyboard_interrupt_mensaje_amigable(self, runner, book_file):
        with patch("tenlib.cli.build_orchestrator") as mock_factory:
            mock_orch = MagicMock()
            mock_orch.run.side_effect = KeyboardInterrupt()
            mock_factory.return_value = mock_orch

            result = run_translate(runner, book_file)

            assert result.exit_code == 0
            assert "interrumpido" in result.output.lower()
            assert "reanudarlo" in result.output.lower()

    def test_error_inesperado_sugiere_issue(self, runner, book_file):
        with patch("tenlib.cli.build_orchestrator") as mock_factory:
            mock_orch = MagicMock()
            mock_orch.run.side_effect = RuntimeError("error desconocido")
            mock_factory.return_value = mock_orch

            result = run_translate(runner, book_file)

            assert result.exit_code == 1
            assert "issue" in result.output.lower()

    def test_fix_book_already_done_muestra_confirmacion(
        self, runner, translation_file, original_file
    ):
        with patch("tenlib.cli.build_orchestrator") as mock_factory:
            mock_orch = MagicMock()
            mock_orch.run_fix.side_effect = BookAlreadyDoneError("Ya procesado")
            mock_factory.return_value = mock_orch

            result = runner.invoke(
                main,
                [
                    "fix",
                    "--translation", str(translation_file),
                    "--original", str(original_file),
                    "--to", "es",
                ],
                input="N\n",
            )

            assert "ya fue corregido" in result.output.lower()


# ------------------------------------------------------------------
# Stubs
# ------------------------------------------------------------------

class TestStubs:

    def test_review_imprime_proximamente(self, runner, tmp_path):
        result = runner.invoke(main, ["review", "--book", str(tmp_path / "a.txt")])
        assert "próximamente" in result.output.lower() or "fase" in result.output.lower()

    def test_write_imprime_proximamente(self, runner, tmp_path):
        result = runner.invoke(main, ["write", "--outline", str(tmp_path / "idea.txt")])
        assert "próximamente" in result.output.lower() or "fase" in result.output.lower()

    def test_help_muestra_todos_los_comandos(self, runner):
        result = runner.invoke(main, ["--help"])
        for cmd in ["translate", "fix", "review", "write"]:
            assert cmd in result.output
