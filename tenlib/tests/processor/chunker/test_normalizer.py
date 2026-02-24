import pytest

from tenlib.processor.chunker.models import BoundaryType, ChunkConfig, TextSegment
from tenlib.processor.chunker.normalizer import ChunkNormalizer
from tenlib.processor.chunker.token_estimator import SimpleTokenEstimator
from tenlib.processor.models import ChunkStatus

# ---------------------------------------------------------------------------
# Fixtures y helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def config():
    # Umbrales reducidos para hacer los tests rápidos y legibles
    return ChunkConfig(min_tokens=100, max_tokens=200, target_tokens=150)


@pytest.fixture
def estimator():
    return SimpleTokenEstimator()


@pytest.fixture
def normalizer(config, estimator):
    return ChunkNormalizer(config, estimator)


def _make_segment(
    text: str,
    boundary: BoundaryType = BoundaryType.PARAGRAPH,
    source_section: int = 0,
) -> TextSegment:
    """Crea un TextSegment con token_estimated calculado automáticamente."""
    est = SimpleTokenEstimator()
    return TextSegment(
        text=text,
        boundary_type=boundary,
        source_section=source_section,
        original_position=0,
        token_estimated=est.estimate(text),
    )


def _words(n: int, word: str = "Palabra") -> str:
    """Genera una cadena de exactamente N palabras."""
    return " ".join([word] * n)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_segmento_dentro_de_rango_pasa_sin_cambios(normalizer):
    """Un segmento dentro de [min, max] tokens debe producir un único chunk idéntico."""
    # Arrange — 100 palabras → int(100*1.3)=130 tokens ∈ [100, 200]
    text = _words(100)
    seg = _make_segment(text)

    # Act
    chunks = normalizer.normalize([seg])

    # Assert
    assert len(chunks) == 1
    assert chunks[0].original == text
    assert normalizer._config.min_tokens <= chunks[0].token_estimated <= normalizer._config.max_tokens


def test_segmento_grande_se_divide_por_parrafos(normalizer):
    """Un segmento con varios párrafos que supera max_tokens debe dividirse en chunks separados."""
    # Arrange — p1: ~130t, p2: ~130t; juntos ~260 > max=200
    p1 = _words(100)
    p2 = _words(100, word="Fragmento")
    seg = _make_segment(f"{p1}\n\n{p2}")

    # Act
    chunks = normalizer.normalize([seg])

    # Assert
    assert len(chunks) == 2
    assert p1 in chunks[0].original
    assert p2 in chunks[1].original
    assert all(c.token_estimated <= normalizer._config.max_tokens for c in chunks)


def test_segmento_grande_sin_parrafos_se_divide_por_oraciones(normalizer):
    """Un bloque sin párrafos que supera max_tokens debe dividirse a nivel de oraciones."""
    # Arrange — dos bloques de ~150 tokens cada uno, sin saltos de párrafo
    s1 = "Oracion muy extensa para el normalizador blablabla. " * 20
    s2 = "Segunda oracion larga extensa de testing blablabla. " * 20
    seg = _make_segment(f"{s1.strip()} {s2.strip()}")

    # Act
    chunks = normalizer.normalize([seg])

    # Assert
    assert len(chunks) == 2
    assert all(c.token_estimated <= normalizer._config.max_tokens for c in chunks)


def test_segmentos_pequenos_se_fusionan(normalizer):
    """Dos segmentos por debajo de min_tokens deben combinarse en un único chunk."""
    # Arrange — ~5 y ~7 tokens respectivamente, ambos muy por debajo de min=100
    s1 = _make_segment("Párrafo muy corto el primero.")
    s2 = _make_segment("El segundo tampoco alcanza el mínimo de tokens.")

    # Act
    chunks = normalizer.normalize([s1, s2])

    # Assert
    assert len(chunks) == 1
    assert "el primero" in chunks[0].original
    assert "tampoco alcanza" in chunks[0].original
    assert chunks[0].token_estimated <= normalizer._config.max_tokens


def test_capitulos_nunca_se_fusionan_aunque_sean_pequenos(normalizer):
    """Fronteras de tipo CHAPTER son sagradas: nunca se fusionan con segmentos adyacentes."""
    # Arrange
    capitulo = _make_segment("Capítulo 1", boundary=BoundaryType.CHAPTER)
    parrafo = _make_segment("Párrafo igualmente pequeño, pero está debajo.")

    # Act
    chunks = normalizer.normalize([capitulo, parrafo])

    # Assert
    assert len(chunks) == 2
    assert chunks[0].original == "Capítulo 1"


def test_parrafo_enorme_unico_no_rompe_el_pipeline(normalizer):
    """Un bloque indivisible (sin puntuación ni párrafos) que supera max_tokens debe
    sobrevivir como un único chunk sin lanzar excepciones."""
    # Arrange — sin separadores de ningún tipo, >650 tokens
    seg = _make_segment(_words(500))

    # Act
    chunks = normalizer.normalize([seg])

    # Assert
    assert len(chunks) == 1
    assert chunks[0].token_estimated > normalizer._config.max_tokens


# ---------------------------------------------------------------------------
# N-01 — Lista vacía
# ---------------------------------------------------------------------------


def test_lista_vacia_retorna_lista_vacia(normalizer):
    """normalize([]) debe retornar [] sin errores."""
    # Arrange / Act / Assert
    assert normalizer.normalize([]) == []


# ---------------------------------------------------------------------------
# N-02 — Exactamente en max_tokens (NO debe dividirse)
# ---------------------------------------------------------------------------


def test_segmento_exactamente_en_max_tokens_no_se_divide(normalizer):
    """token_estimated == max_tokens satisface la condición '<= max', por lo que
    el segmento pasa sin expansión."""
    # Arrange — 154 palabras → int(154*1.3) = int(200.2) = 200 == max_tokens
    text = _words(154)
    seg = _make_segment(text)

    assert seg.token_estimated == normalizer._config.max_tokens  # pre-condición

    # Act
    chunks = normalizer.normalize([seg])

    # Assert
    assert len(chunks) == 1
    assert chunks[0].original == text


# ---------------------------------------------------------------------------
# N-03 — Un token sobre max_tokens (SÍ debe dividirse)
# ---------------------------------------------------------------------------


def test_segmento_sobre_max_tokens_activa_expansion_por_parrafos(normalizer):
    """Un segmento que supera max_tokens en al menos un token debe generar múltiples chunks."""
    # Arrange — p1: ~130t, p2: ~78t → total ~208 > max=200
    p1 = _words(100)
    p2 = _words(60, word="Fragmento")
    text = f"{p1}\n\n{p2}"
    seg = _make_segment(text)

    assert seg.token_estimated > normalizer._config.max_tokens  # pre-condición

    # Act
    chunks = normalizer.normalize([seg])

    # Assert
    assert len(chunks) == 2
    assert all(c.token_estimated <= normalizer._config.max_tokens for c in chunks)


# ---------------------------------------------------------------------------
# N-04 — Exactamente en min_tokens (NO debe activar fusión)
# ---------------------------------------------------------------------------


def test_segmento_exactamente_en_min_tokens_no_activa_fusion(normalizer):
    """La condición de fusión es estricta (< min_tokens), por lo que un segmento con
    token_estimated == min_tokens NO debe fusionarse con el siguiente."""
    # Arrange — 77 palabras → int(77*1.3) = int(100.1) = 100 == min_tokens
    seg_en_minimo = _make_segment(_words(77))
    seg_pequeno = _make_segment(_words(20, word="Corto"))

    assert seg_en_minimo.token_estimated == normalizer._config.min_tokens  # pre-condición

    # Act
    chunks = normalizer.normalize([seg_en_minimo, seg_pequeno])

    # Assert — el segmento en el límite exacto NO es candidato a fusión
    assert len(chunks) == 2


# ---------------------------------------------------------------------------
# N-05 — Varios segmentos pequeños que juntos superarían max_tokens
# ---------------------------------------------------------------------------


def test_varios_segmentos_pequeños_no_superan_max_tokens_al_fusionar(normalizer):
    """El merge debe detenerse cuando añadir el siguiente segmento superaría max_tokens."""
    # Arrange — cada segmento: 62 palabras → ~80 tokens < min=100
    #   seg1+seg2 fusionados: ~161 tokens ≤ 200 → se fusionan
    #   fusionado (161) ≥ min(100) → seg3 NO se fusiona → queda solo
    segs = [_make_segment(_words(62)) for _ in range(3)]

    # Act
    chunks = normalizer.normalize(segs)

    # Assert
    assert len(chunks) == 2
    assert all(c.token_estimated <= normalizer._config.max_tokens for c in chunks)


# ---------------------------------------------------------------------------
# N-06 — ChunkStatus y índices secuenciales
# ---------------------------------------------------------------------------


def test_chunks_tienen_estado_pending_e_indices_secuenciales(normalizer):
    """Todos los chunks deben nacer con status=PENDING e índices 0, 1, 2, … sin saltos."""
    # Arrange — tres segmentos en rango para garantizar 1-a-1 (sin splits ni merges)
    segs = [_make_segment(_words(100, word=f"Palabra{i}")) for i in range(3)]

    # Act
    chunks = normalizer.normalize(segs)

    # Assert
    assert len(chunks) > 0
    for i, chunk in enumerate(chunks):
        assert chunk.status == ChunkStatus.PENDING, f"Chunk {i} no tiene status PENDING"
        assert chunk.index == i, f"Se esperaba index={i}, se obtuvo {chunk.index}"


# ---------------------------------------------------------------------------
# N-07 — Propagación de source_section al Chunk
# ---------------------------------------------------------------------------


def test_source_section_se_propaga_al_chunk_final(normalizer):
    """El source_section del TextSegment de entrada debe aparecer en el Chunk de salida."""
    # Arrange
    seg = _make_segment(_words(100), source_section=7)

    # Act
    chunks = normalizer.normalize([seg])

    # Assert
    assert len(chunks) == 1
    assert chunks[0].source_section == 7


# ---------------------------------------------------------------------------
# N-08 — Fronteras POV y SCENE no bloquean la fusión
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "boundary_type",
    [BoundaryType.SCENE, BoundaryType.POV],
)
def test_fronteras_no_chapter_no_bloquean_fusion(normalizer, boundary_type):
    """Solo CHAPTER bloquea la fusión. SCENE y POV deben permitir que segmentos
    pequeños se unan al anterior cuando las condiciones de tokens lo permiten."""
    # Arrange — ambos segmentos muy por debajo de min=100
    seg_anterior = _make_segment("Muy corto.", boundary=BoundaryType.PARAGRAPH)
    seg_actual = _make_segment("También muy corto.", boundary=boundary_type)

    # Act
    chunks = normalizer.normalize([seg_anterior, seg_actual])

    # Assert — se fusionan en un único chunk
    assert len(chunks) == 1


# ---------------------------------------------------------------------------
# N-09 — Oración individual que supera max_tokens
# ---------------------------------------------------------------------------


def test_oracion_individual_mayor_que_max_tokens_sobrevive_como_chunk_unico(normalizer):
    """Una oración que sola supera max_tokens (sin puntuación ni saltos) debe
    preservarse como chunk único sin lanzar excepciones."""
    # Arrange — sin puntuación que permita división, >250 tokens
    seg = _make_segment(_words(200))

    # Act
    chunks = normalizer.normalize([seg])

    # Assert
    assert len(chunks) == 1
    assert chunks[0].token_estimated > normalizer._config.max_tokens


# ---------------------------------------------------------------------------
# N-10 — Segmento pequeño al final de la lista sin vecino para fusionar
# ---------------------------------------------------------------------------


def test_segmento_pequeño_al_final_sobrevive_sin_vecino_que_fusionar(normalizer):
    """Cuando el segmento anterior supera min_tokens, el último segmento pequeño
    no encuentra candidato de fusión y debe preservarse como chunk independiente."""
    # Arrange
    seg_en_rango = _make_segment(_words(100))        # ~130 tokens ≥ min=100
    seg_pequeno = _make_segment(_words(20, word="Corto"))  # ~26 tokens < min=100

    assert seg_en_rango.token_estimated >= normalizer._config.min_tokens  # pre-condición

    # Act
    chunks = normalizer.normalize([seg_en_rango, seg_pequeno])

    # Assert — el segmento pequeño sobrevive solo; no se pierde
    assert len(chunks) == 2
    assert "Corto" in chunks[1].original
