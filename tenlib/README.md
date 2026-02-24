# TenLib
Es un proyecto open Source en donde busco crear un agente editorial con IA para hacer traducciones, mejorar traducciones, ser copiloto al escribir un libro entre otras cosas, esto nace de mi gusto por la lectura japonesa y las pocas traducciones a novelas ligeras que encuentro y ademas mi gusto por la literatura, ahora si el README hecho por IA.
## Notas del Autor:

No se bien ingles pero lo estoy practicando por lo que si ven errores semanticos en el codigo o en los commits una disculpa de antemano.

# 📚 TenLib

> Un editor literario agéntico de código abierto. Traduce, corrige y escribe libros completos con IA, preservando coherencia y optimizando el uso de tokens.

---

## ¿Por qué existe esto?

Los libros tienen entre 80.000 y 150.000 palabras. Ningún modelo de IA cabe eso en contexto de una sola vez. Si lo partes sin criterio, pierdes coherencia: los personajes cambian de nombre entre capítulos, el tono varía, los modismos se traducen de formas distintas en cada fragmento.

Las soluciones actuales (DeepL, plugins de Calibre, pegar fragmentos en ChatGPT) tratan cada chunk como un texto nuevo, sin memoria del resto del libro. **TenLib resuelve eso** construyendo una memoria editorial persistente que viaja con cada fragmento a lo largo de todo el proceso.

Además, la mayoría de personas con acceso a múltiples IAs (Claude Pro, GPT Plus, Gemini Pro) no puede aprovecharlos en conjunto. TenLib los unifica en un solo pipeline con rotación automática cuando se agotan los tokens del día.

---

## Características principales

- **Chunking semántico** — divide por escenas y capítulos, no por tamaño fijo
- **Book Bible** — memoria editorial persistente: glosario, personajes, voz narrativa, decisiones de estilo
- **Compresión de contexto** — solo el contexto relevante viaja en cada llamada (hasta 40% menos tokens)
- **Multi-modelo con rotación** — Claude, GPT y Gemini en un solo pipeline con failover automático
- **Reanudación automática** — si el proceso se interrumpe, continúa desde donde quedó
- **Control de calidad** — detector de inconsistencias y cola de revisión humana
- **Múltiples modos** — traducción, corrección de traducciones, ajuste de estilo, co-autoría

---

## Modos de operación

```bash
# Traducir un libro de inglés a español
libreditor translate --book libro.epub --from en --to es

# Corregir o mejorar una traducción existente con el original como referencia
libreditor fix-translation --book traduccion.epub --reference original.epub

# Abrir la interfaz de revisión humana para un libro procesado
libreditor review --book mi_libro

# Modo co-autor: desarrollar una idea hasta un libro completo
libreditor write --outline mi_idea.txt
```

---

## Arquitectura

```
┌─────────────────────────────────────────────────────┐
│                  GRADIO UI / CLI                    │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│                  ORCHESTRATOR                       │
│   Gestiona el pipeline · Coordina módulos           │
│   Controla flujo de chunks · Maneja errores         │
└──────┬───────────────┬───────────────┬──────────────┘
       │               │               │
┌──────▼──────┐ ┌──────▼──────┐ ┌─────▼───────────────┐
│    BOOK     │ │   CONTEXT   │ │      MODEL          │
│  PROCESSOR  │ │   ENGINE    │ │      ROUTER         │
│             │ │             │ │                     │
│ · Parse     │ │ · Book Bible│ │ · Claude            │
│ · Chunk     │ │ · Compress  │ │ · GPT               │
│ · Reconstruct│ │ · Update   │ │ · Gemini            │
└─────────────┘ └─────────────┘ │ · Token tracker     │
                                └─────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│                QUALITY CHECKER                      │
│   Detector de inconsistencias · Comparador          │
│   Cola de revisión humana · Marcador de confianza   │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│              STORAGE (SQLite local)                 │
│   books · chunks · bible · quota_usage              │
│   /output → EPUB, DOCX, TXT reconstruidos           │
└─────────────────────────────────────────────────────┘
```

---

## Módulos en detalle

### 1. Book Processor

Convierte el libro crudo en chunks procesables y, al final, reconstruye el archivo de salida.

**Chunking semántico:** no divide por cantidad fija de tokens. Detecta primero capítulos, luego escenas (separadores `***`, saltos dobles, cambios de POV indicados por el autor). Cada chunk queda entre 800 y 2000 tokens — suficiente para que el modelo tenga contexto interno, pequeño para caber junto a la Book Bible en el prompt.

**Formatos soportados (v1):**
- `.txt` — texto plano
- `.epub` — via `ebooklib`
- `.docx` — via `python-docx`

> PDF se deja para versiones futuras por la complejidad del layout.

---

### 2. Context Engine *(el corazón del sistema)*

Mantiene y administra la **Book Bible**: un objeto JSON vivo que representa la memoria editorial del libro completo.

```json
{
  "meta": {
    "title": "El nombre del viento",
    "source_lang": "en",
    "target_lang": "es",
    "voice": "tercera persona, pasado, tono épico-intimista",
    "decisions": [
      "tutear al lector",
      "mantener 'Naming' sin traducir",
      "conservar 'Chandrian' en lugar de hispanizarlo"
    ]
  },
  "glossary": {
    "Kvothe": "Kvothe",
    "Sympathy": "Simpatía",
    "the Chandrian": "los Chandrian",
    "Naming": "Naming"
  },
  "characters": {
    "Kvothe": "protagonista, voz activa, habla directo y sin rodeos",
    "Chronicler": "escriba, tono formal y observador"
  },
  "continuity": {
    "last_scene": "Kvothe acaba de llegar a la Universidad",
    "open_threads": [
      "mencionó a su madre en cap 3, hilo sin resolver"
    ]
  }
}
```

**Antes de cada chunk:** el motor comprime la Biblia a lo estrictamente relevante para ese fragmento. Si el chunk no contiene al Chronicler, su entrada no va en el prompt. En libros con elencos grandes esto reduce hasta un 40% el uso de tokens.

**Después de cada chunk:** el motor actualiza la Biblia con nuevas decisiones detectadas (términos nuevos, decisiones de estilo tomadas por el modelo, continuity updates).

La Biblia se versiona en SQLite — puedes revertir a cualquier estado anterior si una decisión automática fue incorrecta.

---

### 3. Model Router

Gestiona los tres modelos de forma transparente. El Orchestrator no sabe ni le importa qué modelo procesó cada chunk.

**Configuración** en `~/.libreditor/quota.yaml`:

```yaml
models:
  - name: claude
    type: api          # 'api' o 'pro' (plan de suscripción)
    priority: 1
    daily_token_limit: 100000
    api_key: ${ANTHROPIC_API_KEY}

  - name: gemini
    type: pro
    priority: 2
    daily_token_limit: 80000

  - name: gpt
    type: plus
    priority: 3
    daily_token_limit: 80000
```

**Lógica de rotación:**
1. Intenta el modelo de mayor prioridad disponible
2. Si recibe error 429 (rate limit) o supera el límite configurado → pasa al siguiente
3. Si todos están agotados → pausa y notifica al usuario con tiempo estimado de espera
4. Cada chunk registra en SQLite qué modelo lo procesó (importante para auditoría y consistencia)

---

### 4. Quality Checker

Corre en paralelo al pipeline principal, no lo bloquea.

**Detecta automáticamente:**
- El mismo término fuente traducido de dos formas distintas (cruza contra el glosario)
- Cambio de tiempo verbal entre chunks consecutivos
- Nombres propios que aparecen sin estar en el glosario (posible error o término nuevo)
- Fragmentos donde el propio modelo reportó baja confianza

**Confianza del modelo:** cada llamada al modelo devuelve un JSON estructurado:

```json
{
  "translation": "texto traducido aquí...",
  "confidence": 0.82,
  "notes": "expresión idiomática 'under the weather' — opté por 'no estar bien', pero podría ser 'estar pachuco' según el registro"
}
```

Los fragmentos con `confidence < 0.75` o con flags del checker van a una **cola de revisión humana** visible en la UI.

---

### 5. Storage

Todo en SQLite local. Sin dependencias externas, sin nube obligatoria.

```sql
-- Esquema principal

CREATE TABLE books (
    id INTEGER PRIMARY KEY,
    title TEXT,
    source_lang TEXT,
    target_lang TEXT,
    mode TEXT,           -- 'translate', 'fix', 'write'
    status TEXT,         -- 'in_progress', 'review', 'done'
    created_at TIMESTAMP
);

CREATE TABLE chunks (
    id INTEGER PRIMARY KEY,
    book_id INTEGER,
    chunk_index INTEGER,
    original TEXT,
    translated TEXT,
    model_used TEXT,
    confidence REAL,
    status TEXT,         -- 'pending', 'done', 'flagged', 'reviewed'
    FOREIGN KEY (book_id) REFERENCES books(id)
);

CREATE TABLE bible (
    id INTEGER PRIMARY KEY,
    book_id INTEGER,
    version INTEGER,
    content_json TEXT,
    updated_at TIMESTAMP
);

CREATE TABLE quota_usage (
    model TEXT,
    date TEXT,
    tokens_used INTEGER,
    PRIMARY KEY (model, date)
);
```

**Reanudación automática:** si el proceso se interrumpe, al reanudarlo el Orchestrator consulta `WHERE status = 'pending'` y continúa desde ahí. No se reprocesa nada.

---

## Roadmap de desarrollo

El proyecto se construye en 4 fases para tener algo funcional desde el primer sprint.

### Fase 1 — MVP (1-2 semanas)
> Objetivo: pipeline funcional de extremo a extremo con un modelo

- [ ] Book Processor: parse de TXT y EPUB, chunking semántico básico
- [ ] Llamada a un modelo (Claude API) con prompt de traducción
- [ ] Reconstrucción del archivo de salida en TXT
- [ ] Storage SQLite básico (books + chunks)
- [ ] CLI mínimo: `libreditor translate --book X --from en --to es`

**Criterio de éxito:** traducir un libro completo de 100.000 palabras de principio a fin, con output coherente y reanudable.

---

### Fase 2 — Context Engine (1-2 semanas)
> Objetivo: la Book Bible entra en el pipeline

- [ ] Estructura JSON de la Book Bible
- [ ] Extracción automática de glosario en el primer chunk
- [ ] Compresión de contexto por chunk
- [ ] Actualización incremental de la Biblia
- [ ] Versionado de la Biblia en SQLite

**Criterio de éxito:** mismo libro traducido en Fase 1, ahora con consistencia de nombres y términos a lo largo de todo el texto.

---

### Fase 3 — Model Router (1 semana)
> Objetivo: los tres modelos en un solo pipeline

- [ ] Abstracción unificada de llamadas (Claude / GPT / Gemini)
- [ ] Configuración de quota por modelo en YAML
- [ ] Rotación automática con failover
- [ ] Tracking de tokens en SQLite
- [ ] Soporte para planes Pro (sin API key) vía automatización ligera

**Criterio de éxito:** procesar un libro usando los tres modelos en rotación sin intervención manual.

---

### Fase 4 — Quality + UI (2 semanas)
> Objetivo: producto completo y usable por otros

- [ ] Quality Checker con detección de inconsistencias
- [ ] Cola de revisión humana
- [ ] UI Gradio: progreso en tiempo real, revisión de chunks, edición de la Biblia
- [ ] Modo `fix-translation` (corrección de traducción existente)
- [ ] Modo `write` (co-autoría con outline)
- [ ] Exportación a EPUB y DOCX
- [ ] Documentación de usuario

---

## Stack tecnológico

| Componente | Tecnología |
|---|---|
| Lenguaje | Python 3.11+ |
| UI | Gradio |
| Storage | SQLite (via `sqlite3` stdlib) |
| Parse EPUB | `ebooklib` |
| Parse DOCX | `python-docx` |
| Claude | `anthropic` SDK |
| GPT | `openai` SDK |
| Gemini | `google-generativeai` SDK |
| CLI | `click` |
| Config | `PyYAML` |

---

## Instalación (Fase 1)

```bash
git clone https://github.com/tu-usuario/libreditor.git
cd libreditor

python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

pip install -r requirements.txt

# Configurar modelos
cp config.example.yaml ~/.libreditor/quota.yaml
# Editar el archivo con tus API keys o configuración de planes Pro
```

---

## Estructura del proyecto

```
libreditor/
├── libreditor/
│   ├── __init__.py
│   ├── cli.py                  # Punto de entrada CLI
│   ├── orchestrator.py         # Coordinador del pipeline
│   ├── processor/
│   │   ├── __init__.py
│   │   ├── parser.py           # Parse de EPUB, DOCX, TXT
│   │   └── chunker.py          # Chunking semántico
│   ├── context/
│   │   ├── __init__.py
│   │   ├── bible.py            # Book Bible (estructura + versionado)
│   │   └── compressor.py       # Compresión de contexto por chunk
│   ├── router/
│   │   ├── __init__.py
│   │   ├── base.py             # Interfaz abstracta de modelo
│   │   ├── claude.py
│   │   ├── gpt.py
│   │   └── gemini.py
│   ├── quality/
│   │   ├── __init__.py
│   │   └── checker.py          # Detección de inconsistencias
│   ├── storage/
│   │   ├── __init__.py
│   │   └── db.py               # SQLite + queries
│   └── ui/
│       └── app.py              # Gradio UI
├── tests/
├── config.example.yaml
├── requirements.txt
└── README.md
```

---

## Principios de diseño

**Local-first.** Todos los datos del libro, la Biblia y el progreso viven en tu máquina. Ningún dato sale salvo las llamadas a los modelos que tú mismo configuras.

**Reanudable por defecto.** Cualquier proceso puede interrumpirse y retomarse. El estado siempre está en disco.

**Modelo-agnóstico.** Agregar un modelo nuevo es implementar una clase que hereda de `BaseModel`. El resto del sistema no cambia.

**La calidad primero.** El objetivo no es traducir rápido sino traducir bien. La velocidad es una consecuencia de optimizar tokens, no el fin.

---

## Contribuir

El proyecto está en construcción activa. Las contribuciones más valiosas en este momento son:

- Parsers para nuevos formatos (PDF, RTF, ODT)
- Adaptadores para nuevos modelos
- Mejoras al algoritmo de chunking semántico
- Prompts de sistema mejor calibrados para distintos géneros literarios

Abre un issue antes de un PR grande para alinear dirección.

---

## Licencia

MIT — libre para usar, modificar y distribuir.

---

*TenLib nació de la frustración de leer libros en traducciones mediocres cuando la tecnología para hacerlo mejor ya existe. Solo faltaba juntarla bien.*