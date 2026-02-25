# TenLib — Estado Técnico del MVP

> Documento de referencia interno. Describe exactamente lo que está construido, cómo funciona y qué falta. Sin aspiracionalismo.

---

## Resumen ejecutivo

TenLib es un pipeline de traducción de libros completos con IA. El MVP actual cubre **Fase 1 + Fase 3** del roadmap original: el pipeline de extremo a extremo funciona, los dos modelos (Claude y Gemini) están integrados con failover automático y la reanudación ante interrupciones está garantizada por hash de archivo.

**Lo que puede hacer hoy:**
```bash
tenlib translate --book libro.epub --from en --to es
```
Toma un `.epub`, `.txt` o `.md`, lo divide en chunks semánticos, traduce cada uno con Claude o Gemini, y reconstruye el archivo de salida en `.txt` con reanudación automática.

**Lo que NO está construido todavía:** Book Bible / Context Engine, modo `fix`, modo `write`, UI Gradio, exportación a EPUB/DOCX, Quality Checker, reset de libro ya procesado.

---

## Stack técnico

| Componente       | Tecnología                          |
|------------------|-------------------------------------|
| Lenguaje         | Python 3.11+                        |
| CLI              | Click                               |
| Storage          | SQLite3 (stdlib)                    |
| Parse EPUB       | ebooklib                            |
| Claude           | anthropic SDK — `claude-haiku-4-5-20251001` |
| Gemini           | google-generativeai SDK — `gemini-2.0-flash` |
| Config           | PyYAML                              |
| Tests            | pytest                              |
| Build            | setuptools ≥ 61.0                   |
| Python mínimo    | 3.11                                |

**Dependencias de producción** (`requirements.txt`):
```
click
PyYAML
python-dotenv
anthropic
google-generativeai
ebooklib
pysqlite3
```

---

## Estructura de paquetes

```
tenlib/
├── config.example.yaml
├── pyproject.toml
├── requirements.txt
├── MVP.md                          ← este archivo
│
├── tenlib/                         # Paquete principal (import: tenlib.xxx)
│   ├── cli.py                      # Punto de entrada CLI
│   ├── factory.py                  # Ensamblador de dependencias (DI manual)
│   ├── orchestrator.py             # Coordinador del pipeline
│   ├── reconstructor.py            # Generador del archivo de salida
│   │
│   ├── processor/
│   │   ├── models.py               # RawBook, Chunk, ChunkStatus
│   │   ├── book_processor.py       # (archivo presente, no usado en el pipeline actual)
│   │   ├── parsers/
│   │   │   ├── base.py             # BaseParser (abstracto)
│   │   │   ├── factory.py          # ParserFactory
│   │   │   ├── txt_parser.py       # TXT y MD
│   │   │   └── epub_parser.py      # EPUB via ebooklib
│   │   └── chunker/
│   │       ├── models.py           # BoundaryType, ChunkConfig, TextSegment
│   │       ├── chunker.py          # Chunker — orquesta las dos pasadas
│   │       ├── detector.py         # BoundaryDetector — Pasada 1
│   │       ├── normalizer.py       # ChunkNormalizer — Pasada 2
│   │       └── token_estimator.py  # SimpleTokenEstimator, TikTokenEstimator
│   │
│   ├── router/
│   │   ├── base.py                 # BaseModel (abstracto)
│   │   ├── models.py               # ModelResponse, ModelConfig
│   │   ├── router.py               # Router — selección y failover
│   │   ├── claude.py               # ClaudeAdapter
│   │   ├── gemini.py               # GeminiAdapter
│   │   ├── prompt_builder.py       # build_translate_prompt()
│   │   ├── response_parser.py      # parse_model_response()
│   │   └── config_loader.py        # load_model_configs() desde YAML
│   │
│   └── storage/
│       ├── db.py                   # Conexión SQLite + schema
│       ├── models.py               # StoredBook, StoredChunk, enums
│       └── repository.py           # Repository — toda la capa de datos
│
└── tests/
    ├── test_cli.py                 # 18 tests — CLI
    ├── test_orchestrator.py        # 9 tests — pipeline + Reconstructor
    ├── processor/
    │   ├── parsers/
    │   │   └── test_parser.py      # 32 tests — TxtParser, EpubParser, Factory
    │   └── chunker/
    │       ├── test_detector.py    # 27 tests — detección de fronteras
    │       ├── test_normalizer.py  # 17 tests — normalización de tokens
    │       └── test_integration.py # 6 tests — pipeline completo del chunker
    ├── router/
    │   ├── test_router.py          # 7 tests — failover y selección
    │   ├── test_prompt_builder.py  # 8 tests — construcción del prompt
    │   └── test_response_parser.py # 7 tests — parseo resiliente de JSON
    └── storage/
        └── test_repository.py      # 17 tests — CRUD SQLite

# TOTAL: 147 tests — todos en verde
```

---

## Modelos de datos

### Enums

```python
# processor/models.py y storage/models.py
class ChunkStatus(str, Enum):
    PENDING  = "pending"    # esperando traducción
    DONE     = "done"       # confianza >= 0.75
    FLAGGED  = "flagged"    # confianza < 0.75 O error en traducción
    REVIEWED = "reviewed"   # revisión humana completada (futuro)

# processor/chunker/models.py
class BoundaryType(str, Enum):
    CHAPTER   = "chapter"   # prioridad más alta
    SCENE     = "scene"
    POV       = "pov"
    PARAGRAPH = "paragraph"
    SENTENCE  = "sentence"  # prioridad más baja

# storage/models.py
class BookMode(str, Enum):
    TRANSLATE = "translate"
    FIX       = "fix"       # futuro Fase 4
    WRITE     = "write"     # futuro Fase 4

class BookStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    REVIEW      = "review"      # futuro
    DONE        = "done"
```

### Dataclasses de dominio

```python
# processor/models.py
@dataclass
class RawBook:
    title: str
    source_path: str
    sections: list[str]              # una entrada por sección/capítulo
    detected_language: Optional[str]

@dataclass
class Chunk:
    index: int
    original: str
    token_estimated: int
    source_section: int              # índice en RawBook.sections
    translated:   Optional[str]  = None
    model_used:   Optional[str]  = None
    confidence:   Optional[float] = None
    status:       ChunkStatus    = ChunkStatus.PENDING
    flags:        list[str]      = field(default_factory=list)

# processor/chunker/models.py
@dataclass
class TextSegment:
    text: str
    boundary_type: BoundaryType
    source_section: int
    original_position: int           # posición en caracteres en el texto original
    token_estimated: int = 0

@dataclass
class ChunkConfig:
    min_tokens:    int = 800
    max_tokens:    int = 2000
    target_tokens: int = 1400
    chapter_patterns:   list[str]    # regexes de capítulo
    scene_patterns:     list[str]    # separadores de escena
    pov_patterns:       list[str]    # marcadores de POV
    paragraph_patterns: list[str]
    sentence_patterns:  list[str]

# router/models.py
@dataclass
class ModelResponse:
    translation:   str
    confidence:    float             # [0.0 – 1.0], clampeado
    notes:         str               # razonamiento del modelo
    model_used:    str
    tokens_input:  int
    tokens_output: int

@dataclass
class ModelConfig:
    name:               str
    priority:           int          # menor = mayor prioridad
    daily_token_limit:  int
    api_key:            Optional[str] = None
    timeout_seconds:    int   = 60
    temperature:        float = 0.3
    _unavailable_until: Optional[float] = None  # cooldown en tiempo UNIX

# storage/models.py
@dataclass
class StoredBook:
    id:          int
    title:       str
    file_hash:   str                 # SHA-256 del archivo
    mode:        BookMode
    status:      BookStatus
    created_at:  str                 # ISO timestamp
    source_lang: Optional[str]
    target_lang: Optional[str]

@dataclass
class StoredChunk:
    id:              int
    book_id:         int
    chunk_index:     int
    original:        str
    status:          ChunkStatus
    translated:      Optional[str]   = None
    model_used:      Optional[str]   = None
    confidence:      Optional[float] = None
    token_estimated: Optional[int]   = None
    source_section:  Optional[int]   = None
    flags:           list[str]       = field(default_factory=list)

# orchestrator.py
@dataclass
class PipelineResult:
    book_id:      int
    output_path:  Path
    total_chunks: int
    translated:   int                # chunks con status DONE
    flagged:      int                # chunks con status FLAGGED
    was_resumed:  bool
```

---

## Schema SQLite

Base de datos local en `~/.tenlib/tenlib.db`. Se inicializa automáticamente al primer uso.

```sql
CREATE TABLE IF NOT EXISTS books (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT,
    source_lang TEXT,
    target_lang TEXT,
    mode        TEXT,           -- 'translate' | 'fix' | 'write'
    status      TEXT,           -- 'in_progress' | 'review' | 'done'
    file_hash   TEXT UNIQUE,    -- SHA-256, garantiza idempotencia
    created_at  TEXT            -- ISO 8601
);

CREATE TABLE IF NOT EXISTS chunks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id         INTEGER NOT NULL,
    chunk_index     INTEGER NOT NULL,
    original        TEXT,
    translated      TEXT,
    token_estimated INTEGER,
    source_section  INTEGER,
    model_used      TEXT,
    confidence      REAL,
    status          TEXT DEFAULT 'pending',
    flags           TEXT DEFAULT '[]',   -- JSON array de strings
    UNIQUE (book_id, chunk_index),       -- idempotencia en save_chunks()
    FOREIGN KEY (book_id) REFERENCES books(id)
);

CREATE TABLE IF NOT EXISTS bible (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id      INTEGER NOT NULL,
    version      INTEGER,
    content_json TEXT,
    updated_at   TEXT,
    FOREIGN KEY (book_id) REFERENCES books(id)
);
-- Tabla reservada para Fase 2 (Context Engine). Existe en el schema pero no se escribe.

CREATE TABLE IF NOT EXISTS quota_usage (
    model       TEXT,
    date        TEXT,           -- 'YYYY-MM-DD'
    tokens_used INTEGER,
    PRIMARY KEY (model, date)
);
```

**Configuración de conexión:**
- `row_factory = sqlite3.Row` — acceso por nombre de columna
- `PRAGMA foreign_keys = ON`
- `PRAGMA journal_mode = WAL` — lecturas concurrentes seguras

---

## Flujo del pipeline

```
tenlib translate --book libro.epub --from en --to es
        │
        ▼ cli.py
  _validate_file()          → extensión en {.epub, .txt, .md} + existencia
  _validate_lang()          → no vacío, solo alfa+guión, máx 10 chars
  source_lang != target_lang
        │
        ▼ factory.py → build_orchestrator()
  load_model_configs()      → ~/.tenlib/config.yaml (o TENLIB_CONFIG_PATH)
  ClaudeAdapter + GeminiAdapter instanciados con config y repo
  Router([claude, gemini])  → ordenados por priority
  Orchestrator(repo, ParserFactory(), Chunker(), router, Reconstructor())
        │
        ▼ orchestrator.py → run()
  SHA-256 del archivo       → identidad del libro (no el nombre)
  repo.get_book_by_hash()
        │
        ├── Libro nuevo:
        │     repo.create_book()
        │     ParserFactory.get_parser() → TxtParser | EpubParser
        │     parser.parse()             → RawBook{sections}
        │     Chunker.chunk(raw_book)    → list[Chunk] (Pasada 1 + 2)
        │     repo.save_chunks()         → INSERT OR IGNORE (idempotente)
        │
        └── Libro existente:
              status == DONE → BookAlreadyDoneError
              status == IN_PROGRESS → was_resumed = True
        │
        ▼
  repo.get_pending_chunks()  → solo status='pending', ORDER BY chunk_index
        │
        ▼ _process_chunks() — loop principal
  Para cada chunk pendiente:
    ┌── try:
    │     Router.translate(chunk.original, system_prompt)
    │       → modelos en orden de priority
    │       → is_available() chequea cooldown + quota diaria
    │       → si falla retryable: cooldown 5min, siguiente modelo
    │       → si falla contenido (BadRequestError): re-raise sin failover
    │       → si todos agotados: AllModelsExhaustedError
    │     repo.update_chunk_translation(status=DONE si conf≥0.75, FLAGGED si <0.75)
    │
    ├── except AllModelsExhaustedError:
    │     break  ← sale del loop, chunks restantes quedan PENDING
    │
    └── except Exception:
          repo.flag_chunk(flags=["error: TipoError: mensaje"])
          pipeline CONTINÚA con el siguiente chunk
        │
        ▼
  Reconstructor.build()     → ~/.tenlib/output/{slug}_{target_lang}.txt
  repo.update_book_status(DONE)
        │
        ▼ cli.py → _print_summary()
  ─────────────────────────────────
  [tenlib] ✓ Proceso completado
  [tenlib]   Total chunks : 87
  [tenlib]   Traducidos   : 85
  [tenlib]   Flaggeados   : 2  (requieren revisión)   ← amarillo si > 0
  [tenlib]   Output       : ~/.tenlib/output/libro_es.txt
  ─────────────────────────────────
```

---

## Módulos en detalle

### CLI (`tenlib/cli.py`)

**Entry point:** `tenlib = tenlib.cli:main` (definido en `pyproject.toml`)

**Comandos implementados:**

| Comando     | Estado         | Descripción                          |
|-------------|----------------|--------------------------------------|
| `translate` | ✅ Funcional   | Pipeline completo de traducción      |
| `fix`       | 🔲 Stub        | Imprime "Fase 4" y sale              |
| `review`    | 🔲 Stub        | Imprime "Fase 4" y sale              |
| `write`     | 🔲 Stub        | Imprime "Fase 4" y sale              |

**Validaciones de `translate`:**
- Archivo existe y es fichero regular
- Extensión en `{.epub, .txt, .md}`
- `--from` y `--to`: no vacíos, sólo `[a-zA-Z-]`, máx 10 chars
- `source_lang.lower() != target_lang.lower()`
- Language codes normalizados a lowercase antes de pasar al orchestrator

**Exit codes:**
- `0` → éxito o KeyboardInterrupt
- `1` → error de validación o error inesperado
- `2` → AllModelsExhaustedError (quota agotada)

**`_handle_already_done`:** pregunta al usuario con `click.confirm()`. Si acepta, muestra mensaje de "reset no implementado todavía" — **el reset real es deuda técnica pendiente**.

---

### Orchestrator (`tenlib/orchestrator.py`)

```python
class Orchestrator:
    def __init__(self, repo, parser_factory, chunker, router, reconstructor)
    def run(self, file_path: str, source_lang: str, target_lang: str,
            mode: BookMode = BookMode.TRANSLATE) -> PipelineResult
```

**Invariantes de diseño:**
- Idempotente: llamarlo dos veces con el mismo archivo reanuda, no reprocesa
- No tiene lógica de negocio: sólo coordina módulos
- Toda excepción por chunk es capturada localmente — el pipeline nunca aborta por un chunk individual
- `AllModelsExhaustedError` hace `break` del loop (chunks restantes quedan PENDING para el siguiente run)

**`_resolve_status(confidence)`:**
```python
return ChunkStatus.DONE if confidence >= 0.75 else ChunkStatus.FLAGGED
```

**`_build_result()`:** cuenta estado directamente desde la BD (no del loop), asegurando consistencia entre runs.

**Funciones de módulo:**
```python
def _compute_hash(path: Path) -> str:
    # SHA-256 en bloques de 64KB — identifica el libro por contenido, no por nombre

def _slugify(title: str) -> str:
    # lowercase → remove non-word → spaces a underscores
    # Ejemplo: "El Nombre del Viento" → "el_nombre_del_viento"
```

**Excepciones propias:**
```python
class BookAlreadyDoneError(Exception): ...
```

---

### Reconstructor (`tenlib/reconstructor.py`)

```python
class Reconstructor:
    def __init__(self, repo: Repository, output_dir: Path | None = None)
    def build(self, book_id: int, output_filename: str) -> Path
```

- Output por defecto: `~/.tenlib/output/`
- Chunks ordenados por `chunk_index`
- Inserta `\n\n` entre chunks de distintas secciones (`source_section` diferente)
- Une todos los chunks con `\n\n`
- Para chunks FLAGGED sin traducción: antepone `[⚠ PENDIENTE DE REVISIÓN]\n`
- Para chunks DONE: usa `chunk.translated`
- Para chunks PENDING sin traducción: usa `chunk.original` (fallback de seguridad)

---

### Parsers (`tenlib/processor/parsers/`)

#### TxtParser

```python
class TxtParser(BaseParser):
    def can_handle(self, file_path: str) -> bool   # .txt, .md (case-insensitive)
    def parse(self, file_path: str) -> RawBook
```

**Lógica de título:**
1. Primera línea ≤ 10 palabras y sin punto al final → usarla como título
2. Fallback → `Path(file_path).stem`

**Lógica de secciones:**
1. Contar ocurrencias de patrones de capítulo en todo el texto
2. Si hay ≥ 2 coincidencias → dividir por capítulos (cada match abre nueva sección)
3. Si hay < 2 → dividir por párrafos (doble salto de línea)
4. Párrafos con < 40 palabras se fusionan con el siguiente (evita secciones diminutas)

**Patrones de capítulo detectados:**
```python
r"(?i)^(chapter|capítulo)\s+\d+"          # Chapter 1, Capítulo 12
r"(?i)^(chapter|capítulo)\s+\w+"          # Chapter One
r"^(i{1,3}|iv|vi{0,3}|ix|x)\.$"          # I. II. III. IV. ...
r"^\d{1,2}\.$"                             # 1. 2. 12.
r"^(\*\*\*|---)$"                          # *** ---
r"^#{1,3}\s+\S"                            # ## Título, # Cap
```

**Encoding:** UTF-8 primary, latin-1 fallback automático.

#### EpubParser

```python
class EpubParser(BaseParser):
    def can_handle(self, file_path: str) -> bool   # .epub (case-insensitive)
    def parse(self, file_path: str) -> RawBook
```

- `ebooklib` se importa lazy (dentro del método) → `ImportError` descriptivo si no está
- Extrae `title` y `language` de metadatos EPUB
- Itera ítems del spine (orden de lectura)
- Conversión HTML → texto plano: regex simple (no BeautifulSoup)
  - Tags de bloque (`<p>`, `<div>`, `<br>`, `<h1>`-`<h6>`) → `\n`
  - Todas las tags eliminadas
  - Entidades HTML decodificadas: `&amp;` `&lt;` `&gt;` `&quot;` `&#39;` `&nbsp;` `&mdash;` `&ndash;` `&hellip;`
- **Descarta ítems con < 50 palabras** (portadas, copyright, índices)

#### ParserFactory

```python
class ParserFactory:
    def __init__(self)                           # registra EpubParser, TxtParser
    def get_parser(self, file_path: str) -> BaseParser
    def register(self, parser: BaseParser)       # inserta al frente (mayor prioridad)
    @classmethod
    def parse_file(cls, file_path: str) -> RawBook
```

- `get_parser()` lanza `FileNotFoundError` si el archivo no existe
- `get_parser()` lanza `UnsupportedFormatError` si ningún parser acepta el archivo

---

### Chunker — Pasada 1: BoundaryDetector (`tenlib/processor/chunker/detector.py`)

```python
class BoundaryDetector:
    def detect(self, text: str, source_section: int = 0) -> list[TextSegment]
```

- `assert isinstance(text, str)` — falla explícita con bytes u otros tipos
- Texto vacío o sólo whitespace → `[]`
- Recorre línea a línea clasificando cada una según jerarquía
- Segmento actual acumula líneas hasta encontrar nueva frontera
- El último segmento siempre se incluye (no se pierde)

**Clasificación de líneas (jerarquía descendente):**
1. `BoundaryType.CHAPTER` — patrones de capítulo del `ChunkConfig`
2. `BoundaryType.SCENE` — separadores `***`, `---`, `•••`, `* * *`, `###`
3. `BoundaryType.POV` — líneas en MAYÚSCULAS o entre `*asteriscos*`
4. `BoundaryType.PARAGRAPH` — **patrón actualmente inoperativo** (requiere whitespace que `stripped` elimina)
5. `BoundaryType.SENTENCE` — **patrón actualmente inoperativo** (mismo motivo)

> **Nota técnica:** PARAGRAPH y SENTENCE son dead code en `_classify_line` porque la comparación se hace contra `line.strip()`. Los patrones de estas dos clases requieren whitespace inicial que no existe en texto stripeado. Solo operan CHAPTER, SCENE y POV.

**Doble línea vacía:** tres newlines consecutivos (`\n\n\n`) producen un `BoundaryType.SCENE`, no dos.

---

### Chunker — Pasada 2: ChunkNormalizer (`tenlib/processor/chunker/normalizer.py`)

```python
class ChunkNormalizer:
    def normalize(self, segments: list[TextSegment]) -> list[Chunk]
```

**Fase de expansión** (segmentos > max_tokens):
1. Dividir por párrafos (doble salto de línea)
2. Si un párrafo sigue siendo > max_tokens: dividir por oraciones (`. `, `? `, `! `)
3. Si una oración individual supera max_tokens: se mantiene como chunk único (sin romper)

**Fase de fusión** (segmentos < min_tokens):
- Condiciones para fusionar con el anterior:
  1. El segmento anterior tiene < min_tokens
  2. La suma no supera max_tokens
  3. Ninguno de los dos es CHAPTER
- Capítulos NUNCA se fusionan (preservan estructura del libro)

**Conversión a Chunk:**
- Índices secuenciales desde 0
- `status = ChunkStatus.PENDING`
- `source_section` propagado desde el TextSegment

---

### Chunker — Coordinador (`tenlib/processor/chunker/chunker.py`)

```python
class Chunker:
    def __init__(self, config: ChunkConfig | None = None,
                 estimator: TokenEstimator | None = None)
    def chunk(self, book: RawBook) -> list[Chunk]
```

- Instancia `BoundaryDetector` y `ChunkNormalizer` internamente
- Itera `book.sections`, llama `detector.detect(section, source_section=i)`
- Concatena todos los `TextSegment` de todas las secciones
- Llama `normalizer.normalize(all_segments)`
- Re-indexa los chunks globalmente desde 0

**TokenEstimator:**
```python
class SimpleTokenEstimator:
    def estimate(self, text: str) -> int:
        return int(len(text.split()) * 1.3)
    # ±10% para inglés/español — válido para el MVP
```

---

### Router (`tenlib/router/router.py`)

```python
class Router:
    def __init__(self, models: list[BaseModel])   # ValueError si lista vacía
    def translate(self, chunk: str, system_prompt: str) -> ModelResponse
    def available_models(self) -> list[str]
```

**Algoritmo de `translate()`:**
```
Para cada modelo en orden de priority:
    Si model.is_available() == False → skip
    try:
        return model.translate(chunk, system_prompt)
    except BadRequestError | InvalidArgument | ValueError:
        log "content error"
        re-raise                         ← sin failover
    except Exception:
        log "retryable error"
        continue al siguiente modelo

raise AllModelsExhaustedError
```

**`_is_content_error(e)`:** devuelve `True` para `anthropic.BadRequestError`, `google.api_core.exceptions.InvalidArgument`, `ValueError`. Estos no hacen failover porque el problema es el contenido, no el modelo.

```python
class AllModelsExhaustedError(Exception): ...
```

---

### Model Adapters

#### ClaudeAdapter (`tenlib/router/claude.py`)

```python
class ClaudeAdapter(BaseModel):
    def __init__(self, config: ModelConfig, repo: Repository)
```

- Modelo: `claude-haiku-4-5-20251001`
- `max_tokens`: 4096
- Envía: `system=system_prompt`, `messages=[{"role": "user", "content": chunk}]`
- Errors retryables → cooldown de 5min (`_config._unavailable_until = time.time() + 300`)
- Registra tokens en `repo.add_token_usage()` después de cada llamada exitosa

**`is_available()`:**
1. Si `_unavailable_until` está seteado y no ha pasado → False
2. Si ha pasado → limpiar `_unavailable_until`
3. `repo.get_token_usage_today(name) < config.daily_token_limit`

#### GeminiAdapter (`tenlib/router/gemini.py`)

- Modelo: `gemini-2.0-flash`
- Configura `response_mime_type: "application/json"` en `GenerationConfig` (formato nativo de Gemini)
- Extrae tokens de `response.usage_metadata.prompt_token_count` / `candidates_token_count`
- Misma lógica de cooldown y quota que Claude
- **FutureWarning activo**: `google-generativeai` está deprecado en favor de `google.genai`. No afecta funcionalidad pero es deuda técnica.

---

### Prompt Builder (`tenlib/router/prompt_builder.py`)

```python
def build_translate_prompt(
    source_lang: str,
    target_lang: str,
    voice:      str           = "narrador en tercera persona, tiempo pasado",
    decisions:  list[str]     = None,
    glossary:   dict          = None,
    characters: dict          = None,
    last_scene: Optional[str] = None,
) -> str
```

**El chunk viaja como mensaje de usuario, NO en el system prompt.** Esto mejora la adherencia a reglas en todos los modelos.

**Estructura del prompt:**
1. Rol del modelo (editor literario experto)
2. Contexto de obra: `source_lang`, `target_lang`, `voice`
3. Book Bible (actualmente placeholders con defaults):
   - Glosario: `término_origen → término_destino`
   - Decisiones de estilo: lista de strings
   - Personajes: `nombre: descripción de tono`
   - Continuidad: escena anterior
4. Instrucciones de salida: JSON obligatorio

**Schema JSON obligatorio para el modelo:**
```json
{
  "notes": "análisis de retos y decisiones (PRIMERO — CoT)",
  "confidence": 0.0,
  "translation": "texto traducido completo"
}
```
El orden `notes → confidence → translation` es intencional: fuerza razonamiento antes de traducir (Chain-of-Thought).

**Fallbacks cuando no se pasan parámetros opcionales:**
```python
_GLOSSARY_EMPTY   = "Sin glosario todavía — extrae términos relevantes que encuentres."
_DECISIONS_EMPTY  = "Ninguna todavía — este es el primer fragmento."
_CHARACTERS_EMPTY = "Sin perfiles definidos todavía — infiere el tono de cada personaje del texto."
_LAST_SCENE_EMPTY = "Inicio del libro — no hay contexto previo."
```

> **Limitación actual:** el prompt recibe siempre los mismos parámetros globales. La compresión de contexto por chunk (Book Bible selectiva) es Fase 2 y no está implementada.

---

### Response Parser (`tenlib/router/response_parser.py`)

```python
def parse_model_response(raw_text: str, model_name: str) -> dict
# Nunca lanza excepción. Siempre devuelve {"translation", "confidence", "notes"}
```

**Estrategia de degradación:**
1. Parse JSON directo → `json.loads(raw_text)`
2. Extraer de bloque markdown ` ```json ... ``` ` o ` ``` ... ``` `
3. Buscar cualquier `{...}` en el texto con regex
4. Modo emergencia: `translation = raw_text`, `confidence = 0.3`, `notes = "ADVERTENCIA: respuesta no parseable"`

**Normalización:**
- `confidence` clampeado a `[0.0, 1.0]`: `max(0.0, min(1.0, value))`
- Claves faltantes: `confidence` default `0.5`, `notes` default `"(sin notas)"`

---

### Repository (`tenlib/storage/repository.py`)

```python
class Repository:
    def __init__(self, db_path: str | None = None)

    # Books
    def create_book(title, file_hash, mode, source_lang, target_lang) -> int
    def get_book_by_hash(file_hash: str) -> StoredBook | None
    def get_book_by_id(book_id: int) -> StoredBook | None
    def update_book_status(book_id: int, status: BookStatus) -> None

    # Chunks
    def save_chunks(book_id: int, chunks: list) -> None          # INSERT OR IGNORE
    def get_pending_chunks(book_id: int) -> list[StoredChunk]    # ORDER BY chunk_index
    def get_all_chunks(book_id: int) -> list[StoredChunk]        # ORDER BY chunk_index
    def update_chunk_translation(chunk_id, translated, model_used,
                                  confidence, status) -> None    # atómico
    def flag_chunk(chunk_id: int, flags: list[str]) -> None      # → FLAGGED + JSON flags

    # Quota
    def add_token_usage(model: str, tokens: int) -> None         # UPSERT por (model, date)
    def get_token_usage_today(model: str) -> int

    def close(self) -> None
```

**Idempotencia de `save_chunks`:** `INSERT OR IGNORE` con `UNIQUE(book_id, chunk_index)` — reanudaciones no duplican datos.

---

### Config Loader (`tenlib/router/config_loader.py`)

```python
def load_model_configs(config_path: Optional[str] = None) -> list[ModelConfig]
```

**Orden de búsqueda del config:**
1. `config_path` explícito
2. Variable de entorno `TENLIB_CONFIG_PATH`
3. `~/.tenlib/config.yaml`

**Resolución de API keys:** `${VAR_NAME}` → `os.environ.get("VAR_NAME")`

**Config YAML completo:**
```yaml
models:
  - name: gemini
    priority: 1
    daily_token_limit: 1000000
    api_key: ${GEMINI_API_KEY}
    timeout_seconds: 60
    temperature: 0.3

  - name: claude
    priority: 2
    daily_token_limit: 100000
    api_key: ${ANTHROPIC_API_KEY}
    timeout_seconds: 60
    temperature: 0.3
```

---

## Suite de tests — 147 tests

| Archivo                              | Tests | Qué cubre                                      |
|--------------------------------------|-------|------------------------------------------------|
| `test_cli.py`                        | 18    | Validaciones CLI, flujo feliz, errores, stubs  |
| `test_orchestrator.py`               | 9     | Pipeline E2E, reanudación, errores, confianza  |
| `processor/parsers/test_parser.py`   | 32    | TxtParser, EpubParser, ParserFactory           |
| `processor/chunker/test_detector.py` | 27    | Detección de fronteras, patrones, edge cases   |
| `processor/chunker/test_normalizer.py`| 17   | Expansión, fusión, casos límite de tokens      |
| `processor/chunker/test_integration.py`| 6   | Chunker E2E, sin pérdida de contenido          |
| `router/test_router.py`              | 7     | Failover, selección, AllModelsExhaustedError   |
| `router/test_prompt_builder.py`      | 8     | Prompt, CoT, fallbacks, glosario, personajes   |
| `router/test_response_parser.py`     | 7     | Degradación JSON, clamping, markdown blocks    |
| `storage/test_repository.py`         | 17    | CRUD, idempotencia, quota, ordenamiento        |
| **TOTAL**                            | **147** | **100% green**                               |

---

## Directorios en tiempo de ejecución

```
~/.tenlib/
├── config.yaml          # configuración de modelos (copiar de config.example.yaml)
├── tenlib.db            # base de datos SQLite
└── output/              # archivos traducidos
    ├── el_nombre_del_viento_es.txt
    └── ...
```

---

## Deuda técnica y gaps

### Funcionalidad faltante (Fase 2)

| Ítem                          | Impacto                                                  |
|-------------------------------|----------------------------------------------------------|
| Book Bible / Context Engine   | Sin él, cada chunk se traduce sin memoria del libro      |
| Reset de libro ya procesado   | `BookAlreadyDoneError` muestra mensaje pero no resetea   |
| Actualización automática de glosario | El prompt acepta glosario pero nadie lo llena    |
| Compresión de contexto        | Siempre se envía la Bible completa (cuando exista)       |

### Deuda técnica menor

| Ítem                          | Archivo                    | Nota                                              |
|-------------------------------|----------------------------|---------------------------------------------------|
| `PARAGRAPH` / `SENTENCE` en detector | `detector.py:_classify_line` | Dead code: `stripped` elimina el whitespace que necesitan |
| `book_processor.py`           | `processor/book_processor.py` | Archivo presente pero no usado en el pipeline  |
| `google-generativeai` deprecado | `gemini.py:6`            | FutureWarning en runtime, migrar a `google.genai` |
| `ChunkStatus.REVIEWED`        | `storage/models.py`        | Enum definido pero nunca se asigna en el pipeline |
| `BookMode.FIX` / `WRITE`      | `storage/models.py`        | Enums definidos pero los comandos son stubs       |
| tabla `bible` en schema       | `db.py`                    | Creada pero nunca se escribe                     |

### Lo que NO hay

- UI (Gradio o cualquier otra)
- Exportación a EPUB / DOCX
- Quality Checker / cola de revisión
- Adaptador GPT/OpenAI (solo Claude y Gemini)
- Soporte para `.docx` (mencionado en README pero no implementado)
- Soporte para `.pdf`
- Soporte para planes "Pro" sin API key
- Versionado de Book Bible

---

## Instalación y primer uso

```bash
git clone https://github.com/zeus483/TenLib.git
cd tenlib
python -m venv venv
source venv/bin/activate

pip install -r requirements.txt
pip install -e .       # instala el comando `tenlib` en el entorno

# Configurar modelos
mkdir -p ~/.tenlib
cp config.example.yaml ~/.tenlib/config.yaml
# Editar config.yaml con las API keys

# Variables de entorno (o definirlas en el config directamente)
export ANTHROPIC_API_KEY="sk-ant-..."
export GEMINI_API_KEY="AIza..."

# Ejecutar
tenlib translate --book mi_libro.epub --from en --to es

# Correr los tests
pytest tests/ -v
```
