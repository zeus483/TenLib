from collections import Counter

import pytest

from tenlib.processor.chunker.chunker import Chunker
from tenlib.processor.chunker.detector import BoundaryDetector
from tenlib.processor.chunker.models import ChunkConfig
from tenlib.processor.chunker.normalizer import ChunkNormalizer
from tenlib.processor.chunker.token_estimator import SimpleTokenEstimator
from tenlib.processor.models import RawBook

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def config():
    return ChunkConfig(min_tokens=100, max_tokens=200, target_tokens=150)


@pytest.fixture
def estimator():
    return SimpleTokenEstimator()


@pytest.fixture
def detector(config, estimator):
    return BoundaryDetector(config, estimator)


@pytest.fixture
def normalizer(config, estimator):
    return ChunkNormalizer(config, estimator)


@pytest.fixture
def chunker(config, estimator):
    return Chunker(config=config, estimator=estimator)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _generate_mock_book() -> str:
    """Genera un texto de libro sintético con capítulo, párrafos y escena final."""
    return (
        "Capítulo 1\n\n"
        + ("Oración cualquiera de relleno. " * 15 + "\n\n") * 6
        + "***\n\n"
        + ("Final cortito. " * 5 + "\n") * 15
    )


# ---------------------------------------------------------------------------
# Happy path (mejorados)
# ---------------------------------------------------------------------------


def test_libro_completo_produce_chunks_dentro_del_rango(detector, normalizer, config):
    """Los chunks intermedios (ni capítulo ni último fragmento) deben respetar [min, max] tokens."""
    # Arrange
    text = _generate_mock_book()

    # Act
    segments = detector.detect(text)
    chunks = normalizer.normalize(segments)

    # Assert
    assert len(chunks) > 0
    for i, chunk in enumerate(chunks):
        es_capitulo = "Capítulo" in chunk.original
        es_ultimo = i == len(chunks) - 1
        if not es_capitulo and not es_ultimo:
            assert chunk.token_estimated >= config.min_tokens, (
                f"Chunk {i} tiene {chunk.token_estimated} tokens < min={config.min_tokens}"
            )
        assert chunk.token_estimated <= config.max_tokens, (
            f"Chunk {i} supera max_tokens: {chunk.token_estimated}"
        )


def test_todos_los_chunks_tienen_texto_no_vacio(detector, normalizer):
    """Ningún chunk producido por el pipeline debe tener texto vacío o solo whitespace."""
    # Arrange
    text = _generate_mock_book()

    # Act
    segments = detector.detect(text)
    chunks = normalizer.normalize(segments)

    # Assert
    for i, chunk in enumerate(chunks):
        assert chunk.original.strip() != "", f"Chunk {i} contiene texto vacío"


def test_sin_perdida_de_contenido(detector, normalizer):
    """El pipeline no debe perder ni duplicar palabras del texto original.

    Corrección sobre la versión anterior: se compara la lista de palabras en
    orden (no una cadena sin separadores), lo que detecta también reordenamientos.
    El separador ' ' al reconstruir garantiza límites de palabra correctos.
    """
    # Arrange
    text = _generate_mock_book()

    # Act
    segments = detector.detect(text)
    chunks = normalizer.normalize(segments)

    # Reconstruct with space separator to preserve word boundaries
    reconstruido = " ".join(chunk.original for chunk in chunks)

    # Assert — comparación por palabras, preservando orden y multiplicidad
    palabras_originales = text.split()
    palabras_reconstruidas = reconstruido.split()
    assert palabras_originales == palabras_reconstruidas, (
        f"Palabras perdidas o duplicadas. "
        f"Original: {len(palabras_originales)}, Reconstruido: {len(palabras_reconstruidas)}"
    )


# ---------------------------------------------------------------------------
# I-02 — Libro de un solo párrafo masivo (sin separadores)
# ---------------------------------------------------------------------------


def test_libro_de_un_solo_parrafo_masivo_se_procesa_sin_errores(detector, normalizer):
    """Un texto sin ningún separador semántico debe procesarse sin excepciones
    y producir al menos un chunk con contenido no vacío."""
    # Arrange — ~650 tokens en un único bloque continuo
    text = "Una palabra. " * 500

    # Act
    segments = detector.detect(text)
    chunks = normalizer.normalize(segments)

    # Assert
    assert len(chunks) > 0
    assert all(chunk.original.strip() != "" for chunk in chunks)


# ---------------------------------------------------------------------------
# I-03 — Propagación de source_section a través del Chunker
# ---------------------------------------------------------------------------


def test_source_section_se_propaga_correctamente_a_los_chunks(chunker):
    """Cada chunk debe llevar el índice de sección del RawBook al que pertenece."""
    # Arrange
    book = RawBook(
        title="Test Book",
        source_path="/fake/path.txt",
        sections=[
            "Capítulo 1\nContenido de la primera sección.",
            "Capítulo 2\nContenido de la segunda sección.",
        ],
    )

    # Act
    chunks = chunker.chunk(book)

    # Assert
    secciones_presentes = {chunk.source_section for chunk in chunks}
    assert 0 in secciones_presentes, "Ningún chunk apunta a la sección 0"
    assert 1 in secciones_presentes, "Ningún chunk apunta a la sección 1"


# ---------------------------------------------------------------------------
# I-04 — Texto mixto español/inglés (sin pérdida de contenido)
# ---------------------------------------------------------------------------


def test_texto_mixto_espanol_ingles_no_pierde_contenido(detector, normalizer):
    """El pipeline debe procesar texto bilingüe sin perder ni duplicar palabras,
    independientemente del idioma de inicio de oración."""
    # Arrange
    text = (
        "Capítulo 1\n\n"
        + "This is an English sentence. And here is another one. " * 10
        + "\n\n"
        + "Esta es una oración en español. Y aquí hay otra más. " * 10
    )

    # Act
    segments = detector.detect(text)
    chunks = normalizer.normalize(segments)

    reconstruido = " ".join(chunk.original for chunk in chunks)

    # Assert — Counter: verifica que cada palabra aparece el mismo número de veces
    assert Counter(text.split()) == Counter(reconstruido.split()), (
        "El pipeline perdió o duplicó palabras en texto bilingüe"
    )
