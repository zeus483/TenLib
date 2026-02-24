import pytest

from tenlib.processor.chunker.detector import BoundaryDetector
from tenlib.processor.chunker.models import BoundaryType, ChunkConfig
from tenlib.processor.chunker.token_estimator import SimpleTokenEstimator

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def config():
    return ChunkConfig()


@pytest.fixture
def estimator():
    return SimpleTokenEstimator()


@pytest.fixture
def detector(config, estimator):
    return BoundaryDetector(config, estimator)


# ---------------------------------------------------------------------------
# Happy path — fronteras principales
# ---------------------------------------------------------------------------


def test_detecta_capitulo_en_espanol(detector):
    """El patrón 'Capítulo N' debe iniciar un segmento de tipo CHAPTER."""
    # Arrange
    text = "Capítulo 1\nEl inicio de todo."

    # Act
    segments = detector.detect(text)

    # Assert
    assert len(segments) == 1
    assert segments[0].boundary_type == BoundaryType.CHAPTER
    assert segments[0].text == "Capítulo 1\nEl inicio de todo."
    assert segments[0].source_section == 0
    assert segments[0].original_position == 0
    assert segments[0].token_estimated > 0


def test_detecta_escena_con_asteriscos(detector):
    """El separador '***' debe crear una nueva frontera de tipo SCENE."""
    # Arrange
    text = "La charla terminó pacíficamente.\n***\nDe repente, una explosión."

    # Act
    segments = detector.detect(text)

    # Assert
    assert len(segments) == 2

    primer_segmento = segments[0]
    assert primer_segmento.text == "La charla terminó pacíficamente."
    assert primer_segmento.boundary_type == BoundaryType.PARAGRAPH

    segundo_segmento = segments[1]
    assert segundo_segmento.text == "***\nDe repente, una explosión."
    assert segundo_segmento.boundary_type == BoundaryType.SCENE


def test_texto_sin_marcadores_produce_un_solo_segmento_de_tipo_paragraph(detector):
    """Texto sin separadores explícitos se trata como un único bloque PARAGRAPH."""
    # Arrange
    text = "Párrafo 1.\n\nPárrafo 2.\n\nPárrafo 3."

    # Act
    segments = detector.detect(text)

    # Assert
    assert len(segments) == 1
    assert segments[0].boundary_type == BoundaryType.PARAGRAPH
    assert segments[0].text == "Párrafo 1.\n\nPárrafo 2.\n\nPárrafo 3."


def test_no_pierde_el_ultimo_segmento(detector):
    """El último segmento del texto siempre debe capturarse, independientemente de si le sigue un marcador.

    Nota: 'Capítulo único' no coincide con ningún patrón de capítulo (que requieren
    dígito o numeral romano), por lo que el primer segmento queda como PARAGRAPH.
    El objetivo del test es verificar el cierre del bucle, no la clasificación.
    """
    # Arrange
    text = "Capítulo único\nPárrafo inicial.\n***\nÚltimo párrafo sin marcador después."

    # Act
    segments = detector.detect(text)

    # Assert
    assert len(segments) == 2
    assert segments[0].boundary_type == BoundaryType.PARAGRAPH  # "único" no es dígito ni numeral romano
    assert segments[1].boundary_type == BoundaryType.SCENE
    assert "Último párrafo" in segments[1].text


# ---------------------------------------------------------------------------
# B-01 / B-03 — Entradas vacías y solo whitespace
# ---------------------------------------------------------------------------


def test_texto_vacio_retorna_lista_vacia(detector):
    """detect('') debe retornar [] sin errores."""
    # Arrange / Act / Assert
    assert detector.detect("") == []


def test_solo_whitespace_retorna_lista_vacia(detector):
    """Texto con únicamente espacios y saltos de línea debe producir []."""
    # Arrange / Act / Assert
    assert detector.detect("   \n\n   \n   ") == []


# ---------------------------------------------------------------------------
# B-02 — Entradas de tipo incorrecto
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "entrada_invalida",
    [
        None,
        b"texto en bytes",
        123,
        ["lista", "de", "strings"],
    ],
)
def test_entrada_no_string_lanza_assertion_error(detector, entrada_invalida):
    """detect() debe levantar AssertionError si la entrada no es str."""
    # Arrange / Act / Assert
    with pytest.raises(AssertionError):
        detector.detect(entrada_invalida)


# ---------------------------------------------------------------------------
# B-04 — Detección de POV
# ---------------------------------------------------------------------------


def test_detecta_pov_con_asteriscos(detector):
    """Una línea con formato '*Nombre*' debe reconocerse como frontera POV."""
    # Arrange
    text = "Narración previa.\n*Elena*\nTexto desde el punto de vista de Elena."

    # Act
    segments = detector.detect(text)

    # Assert
    assert len(segments) == 2
    assert segments[1].boundary_type == BoundaryType.POV
    assert "Elena" in segments[1].text


def test_detecta_pov_en_mayusculas(detector):
    """Una línea con el nombre del personaje en MAYÚSCULAS debe reconocerse como POV."""
    # Arrange
    text = "Escena anterior terminó.\nELENA\nContemplaba el horizonte en silencio."

    # Act
    segments = detector.detect(text)

    # Assert
    assert len(segments) == 2
    assert segments[1].boundary_type == BoundaryType.POV


# ---------------------------------------------------------------------------
# B-05 — Doble línea vacía como SCENE
# ---------------------------------------------------------------------------


def test_doble_linea_vacia_crea_frontera_de_escena(detector):
    """Dos saltos de línea consecutivos (línea en blanco seguida de otra vacía)
    deben disparar una frontera de tipo SCENE en el segundo segmento."""
    # Arrange — tres '\n' = dos líneas vacías consecutivas entre contenido
    text = "Primer bloque.\n\n\nSegundo bloque."

    # Act
    segments = detector.detect(text)

    # Assert
    assert len(segments) == 2
    assert segments[0].text == "Primer bloque."
    assert segments[0].boundary_type == BoundaryType.PARAGRAPH
    assert segments[1].text == "Segundo bloque."
    assert segments[1].boundary_type == BoundaryType.SCENE


# ---------------------------------------------------------------------------
# B-06 — Patrones de capítulo alternativos
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "chapter_line,description",
    [
        ("Chapter 1", "inglés estándar"),
        ("IV.", "numeral romano con punto, solo en línea"),
        ("## Título del capítulo", "markdown nivel 2"),
        ("第一章", "japonés/chino"),
        ("PART I", "parte en inglés con numeral romano"),
    ],
)
def test_detecta_patron_de_capitulo_alternativo(detector, chapter_line, description):
    """Cada uno de los patrones de capítulo configurados debe reconocerse como CHAPTER."""
    # Arrange
    text = f"{chapter_line}\nContenido que pertenece a este capítulo."

    # Act
    segments = detector.detect(text)

    # Assert
    assert len(segments) >= 1, f"Sin segmentos para: {description}"
    assert segments[0].boundary_type == BoundaryType.CHAPTER, (
        f"Se esperaba CHAPTER para '{chapter_line}' ({description}), "
        f"se obtuvo {segments[0].boundary_type}"
    )


# ---------------------------------------------------------------------------
# B-07 — Múltiples capítulos consecutivos
# ---------------------------------------------------------------------------


def test_multiples_capitulos_producen_segmentos_separados(detector):
    """Cada cabecera de capítulo debe iniciar su propio segmento independiente."""
    # Arrange
    text = (
        "Capítulo 1\nContenido del primero.\n"
        "Capítulo 2\nContenido del segundo.\n"
        "Capítulo 3\nContenido del tercero."
    )

    # Act
    segments = detector.detect(text)

    # Assert
    assert len(segments) == 3
    assert all(s.boundary_type == BoundaryType.CHAPTER for s in segments)
    assert "Capítulo 1" in segments[0].text
    assert "Capítulo 2" in segments[1].text
    assert "Capítulo 3" in segments[2].text


# ---------------------------------------------------------------------------
# B-08 — Propagación de source_section
# ---------------------------------------------------------------------------


def test_source_section_se_propaga_a_todos_los_segmentos(config, estimator):
    """El parámetro source_section debe aparecer en cada segmento producido."""
    # Arrange
    detector = BoundaryDetector(config, estimator)
    text = "Capítulo 1\nContenido.\n***\nEscena siguiente."
    seccion = 5

    # Act
    segments = detector.detect(text, source_section=seccion)

    # Assert
    assert len(segments) > 1
    assert all(s.source_section == seccion for s in segments)


# ---------------------------------------------------------------------------
# B-09 — original_position
# ---------------------------------------------------------------------------


def test_original_position_refleja_posicion_en_texto_original(detector):
    """El primer segmento empieza en posición 0; el siguiente, en el carácter
    exacto donde arranca su sección dentro del texto original."""
    # Arrange — "Capítulo 1\n" ocupa 11 caracteres, luego empieza "***"
    text = "Capítulo 1\n***\nContenido"
    longitud_primera_linea = len("Capítulo 1\n")  # 11

    # Act
    segments = detector.detect(text)

    # Assert
    assert len(segments) == 2
    assert segments[0].original_position == 0
    assert segments[1].original_position == longitud_primera_linea


# ---------------------------------------------------------------------------
# B-10 — token_estimated > 0
# ---------------------------------------------------------------------------


def test_token_estimated_mayor_a_cero_para_segmentos_con_texto(detector):
    """Todos los segmentos con contenido deben tener token_estimated > 0."""
    # Arrange
    text = "Capítulo 1\nTexto con varias palabras.\n***\nMás palabras aquí."

    # Act
    segments = detector.detect(text)

    # Assert
    assert len(segments) > 0
    assert all(s.token_estimated > 0 for s in segments)


# ---------------------------------------------------------------------------
# B-11 — Separadores de escena alternativos
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "separator,description",
    [
        ("---", "guiones"),
        ("* * *", "asteriscos con espacios"),
        ("·····", "puntos centrados"),
        ("###", "almohadillas sin texto"),
    ],
)
def test_detecta_separador_de_escena_alternativo(detector, separator, description):
    """Cada variante de separador de escena debe crear una frontera SCENE."""
    # Arrange
    text = f"Texto anterior.\n{separator}\nTexto posterior."

    # Act
    segments = detector.detect(text)

    # Assert
    assert len(segments) == 2, (
        f"Se esperaban 2 segmentos para el separador '{separator}' ({description}), "
        f"se obtuvieron {len(segments)}"
    )
    assert segments[1].boundary_type == BoundaryType.SCENE, (
        f"Se esperaba SCENE para '{separator}' ({description}), "
        f"se obtuvo {segments[1].boundary_type}"
    )


# ---------------------------------------------------------------------------
# B-12 — Texto de una sola línea (sin saltos de línea)
# ---------------------------------------------------------------------------


def test_texto_de_una_sola_linea_produce_un_segmento(detector):
    """Una línea sin saltos de línea debe producir exactamente 1 segmento."""
    # Arrange
    text = "Esta es la única oración del texto."

    # Act
    segments = detector.detect(text)

    # Assert
    assert len(segments) == 1
    assert segments[0].text == text
    assert segments[0].original_position == 0
