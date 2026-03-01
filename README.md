# TenLib
TenLib es un editor literario agéntico orientado a traducción y corrección de libros largos con IA.

Su objetivo principal es resolver el problema que aparece cuando un libro no cabe completo en contexto: mantener continuidad, voz narrativa, nombres, glosario y decisiones de estilo a través de cientos de chunks sin disparar el consumo de tokens.

## Nota del autor
No sé bien inglés y lo sigo practicando. Si ves errores semánticos en el código, los commits o la documentación, una disculpa de antemano.

## Qué hace hoy

- Traduce libros completos en `.txt`, `.md`, `.epub` y `.pdf`
- Corrige traducciones existentes con referencia al original
- Mejora estilo, sintaxis y legibilidad de una traducción aun sin tener el original
- Mantiene una `Book Bible` persistente por libro
- Comprime contexto antes de cada llamada para reducir tokens
- Rota entre modelos configurados y reanuda automáticamente si se corta el proceso
- Guarda progreso, chunks, Bible y consumo en SQLite local

## Estado actual

TenLib ya tiene implementado el pipeline principal:

- `translate`
- `fix` con `--original`
- `fix` sin `--original` (`fix-style`)
- persistencia versionada de `Book Bible`
- compresión de contexto por chunk
- prompts endurecidos para salida JSON estricta
- reanudación automática
- parser y reconstrucción para PDF con soporte opcional de `pymupdf`
- suite automatizada de tests

Los comandos `review` y `write` existen como stubs de roadmap, pero todavía no están implementados.

## Por qué existe

Las soluciones típicas para traducir libros con IA tratan cada fragmento como si fuera independiente. Eso rompe continuidad:

- personajes que cambian de nombre
- tono narrativo inconsistente
- términos del mundo traducidos de formas distintas
- decisiones de estilo que se olvidan entre capítulos

TenLib intenta resolver eso con una memoria editorial viva y persistente que acompaña cada chunk.

## Modos de operación

### 1. Traducir un libro

```bash
tenlib translate --book libro.epub --from en --to es
```

Opcionalmente puedes controlar el tamaño de chunk:

```bash
tenlib translate --book libro.pdf --from ja --to es --chunk-size large
```

Valores disponibles:

- `standard` → 800-2000 tokens
- `large` → 1200-3500 tokens
- `xlarge` → 2000-5000 tokens

### 2. Corregir una traducción con el original como referencia

```bash
tenlib fix \
  --translation traduccion.epub \
  --original original.epub \
  --from en \
  --to es
```

Este modo no traduce desde cero si no hace falta: compara original y borrador, corrige errores de sentido, mejora fluidez y respeta la `Book Bible`.

### 3. Mejorar una traducción sin tener el original

```bash
tenlib fix \
  --translation traduccion_mala.txt \
  --to es
```

Este es el modo `fix-style`: mejora sintaxis, puntuación, cohesión y naturalidad sin inventar contenido nuevo.

### 4. Comandos reservados para fases siguientes

```bash
tenlib review --book mi_libro
tenlib write --outline idea.txt
```

Hoy solo muestran mensaje de "próximamente".

## CLI real

Comandos disponibles actualmente:

- `tenlib translate`
- `tenlib fix`
- `tenlib review`
- `tenlib write`

Formatos aceptados por la CLI:

- `.txt`
- `.md`
- `.epub`
- `.pdf`

## Arquitectura

```text
CLI
  -> Orchestrator
      -> ParserFactory
      -> Chunker
      -> Router
      -> BibleExtractor
      -> BibleCompressor
      -> Repository (SQLite)
      -> Reconstructor / PdfReconstructor
```

## Pipeline

### Traducción

1. Se parsea el libro
2. Se divide en chunks semánticos
3. Se carga o inicializa la `Book Bible`
4. Se comprime la Bible al contexto relevante del chunk
5. Se construye el prompt de traducción
6. El `Router` elige el mejor modelo disponible
7. Se guarda el chunk traducido
8. Se actualiza la Bible
9. Se reconstruye el output final

### Fix con original

1. Se parsean original y traducción existente
2. Se chunkea el original
3. La traducción se alinea a esos límites
4. Cada llamada recibe original + traducción existente
5. El modelo corrige, no retraduce ciegamente
6. La Bible se actualiza igual que en `translate`

### Fix sin original

1. Se parsea la traducción existente
2. Se chunkea
3. El modelo pule el texto con foco en legibilidad y consistencia
4. La Bible se actualiza con heurísticas locales y contexto persistente

## Book Bible

La `Book Bible` es la memoria editorial persistente del libro. Se guarda versionada en SQLite y hoy contiene:

- `voice`
- `decisions`
- `glossary`
- `characters`
- `last_scene`

Ejemplo:

```json
{
  "voice": "narrador en tercera persona, tiempo pasado",
  "decisions": [
    "mantener tono sobrio en los diálogos",
    "no hispanizar nombres propios fijados"
  ],
  "glossary": {
    "Rimuru": "Rimuru",
    "Tempest": "Tempestad"
  },
  "characters": {
    "Rimuru": "voz calmada y estratégica",
    "Benimaru": "tono firme y militar"
  },
  "last_scene": "El consejo se reunió para discutir la guerra inminente."
}
```

### Qué mejoró recientemente

- la Bible se inicializa y persiste desde el inicio del pipeline
- se actualiza en cada chunk procesado
- no se marca un libro como `done` si aún quedan chunks pendientes
- `decisions` se deduplican y se recortan para controlar crecimiento
- `last_scene` se trunca para no inflar contexto
- se endureció la detección de personajes para evitar ruido

## Detección de personajes

Uno de los puntos más delicados era que la Bible podía terminar agregando como personaje casi cualquier palabra capitalizada.

Eso ya se endureció:

- no se depende solo de mayúsculas
- se usan pistas contextuales como verbos de habla, verbos de acción y títulos
- se filtran pronombres, conectores y ruido editorial
- se preservan personajes ya conocidos aunque aparezcan con poca evidencia
- nombres válidos como `Ultima` no se bloquean por listas frágiles de stopwords

Esto bajó ruido y también reduce tokens en prompts posteriores.

## Compresión de contexto

Antes de cada llamada, la Bible se comprime:

- glosario: solo términos relevantes al chunk
- personajes: solo personajes relevantes al chunk
- decisiones: solo una ventana reciente
- `last_scene`: truncado

El objetivo es mantener continuidad sin enviar toda la memoria completa en cada prompt.

## Prompts

Los prompts actuales se endurecieron para ser más robustos entre modelos:

- salida JSON estricta
- prohibición explícita de markdown
- instrucciones separadas por modo (`translate`, `fix`, `fix-style`)
- calibración más clara de `confidence`
- mayor énfasis en preservar estructura, tono y consistencia

Formato esperado del modelo:

```json
{
  "notes": "resumen breve de decisiones",
  "confidence": 0.82,
  "translation": "texto final"
}
```

## Router y modelos

Hoy el router soporta adaptadores configurables para:

- `gemini`
- `claude`

La configuración vive por defecto en `~/.tenlib/config.yaml`.

Ejemplo:

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
    daily_token_limit: 10000000
    api_key: ${ANTHROPIC_API_KEY}
    timeout_seconds: 60
    temperature: 0.3
```

Lógica general:

1. intenta el modelo de mayor prioridad disponible
2. si se agota quota o falla, rota al siguiente
3. si todos fallan, el pipeline queda pausado
4. al reejecutar el mismo comando, TenLib reanuda desde donde quedó

## Persistencia

Todo se guarda en SQLite local:

- `books`
- `chunks`
- `bible`
- `quota_usage`

Esto permite:

- reanudar procesos
- versionar la Bible
- auditar qué modelo procesó cada chunk
- reconstruir output aunque haya chunks flaggeados

## Reconstrucción de salida

### TXT / MD / EPUB

La salida estándar hoy se reconstruye como `.txt`.

Si un chunk queda `flagged` sin traducción final, se inserta el texto original con una marca visible:

```text
[⚠ PENDIENTE DE REVISIÓN]
```

### PDF

Si trabajas con PDF y tienes `pymupdf`, TenLib puede:

- extraer texto desde PDF
- reconstruir un PDF de salida intentando preservar imágenes e ilustraciones

Si `pymupdf` no está instalado, el sistema cae de vuelta a salida `.txt`.

## Evaluación de Bible y prompts

Se agregó un evaluador reproducible para comparar una referencia buena contra una versión mala o candidata:

- extracción de personajes
- cobertura y ruido
- métricas `precision`, `recall`, `f1`
- presión de contexto de la Bible en prompts

Script:

`scripts/eval_bible_pair.py`

Uso:

```bash
venv/bin/python scripts/eval_bible_pair.py \
  --good "ejemplos_entrenamiento/CanisLycaon] Tensei Shitara Slime Datta Ken Vol 21 [Prólogo].txt" \
  --bad "ejemplos_entrenamiento/prologo_malo.txt"
```

Este evaluador se agregó para poder mejorar heurísticas de Bible y calibrar prompts sin hardcodear reglas específicas de un libro.

## Instalación

### Base

```bash
git clone https://github.com/zeus483/TenLib.git
cd TenLib

python -m venv venv
source venv/bin/activate

pip install -e .
```

### Dependencias opcionales

Para PDF:

```bash
pip install pymupdf
```

## Configuración

1. copia la plantilla:

```bash
mkdir -p ~/.tenlib
cp config.example.yaml ~/.tenlib/config.yaml
```

2. define tus variables de entorno en `.env` o en tu shell:

```bash
export GEMINI_API_KEY=tu_key
export ANTHROPIC_API_KEY=tu_key
```

TenLib carga `.env` automáticamente al arrancar.

También puedes apuntar a otro config con:

```bash
export TENLIB_CONFIG_PATH=/ruta/a/config.yaml
```

## Tests

Ejecutar toda la suite:

```bash
venv/bin/pytest -q
```

Ejecutar solo evaluación de contexto/Bible:

```bash
venv/bin/pytest -q tests/context
```

## Estructura del proyecto

```text
tenlib/
├── cli.py
├── factory.py
├── orchestrator.py
├── reconstructor.py
├── reconstructor_pdf.py
├── context/
│   ├── bible.py
│   ├── character_detector.py
│   ├── compressor.py
│   └── extractor.py
├── processor/
│   ├── chunker/
│   └── parsers/
├── router/
│   ├── claude.py
│   ├── gemini.py
│   ├── prompt_builder.py
│   ├── response_parser.py
│   └── router.py
└── storage/
    ├── db.py
    ├── models.py
    └── repository.py
```

## Roadmap

### En progreso

- mejorar aún más precisión de personajes y glosario
- seguir bajando tokens de Bible sin perder continuidad
- robustecer evaluación automática con más casos reales

### Siguiente fase natural

- exportación real a EPUB
- exportación real a DOCX
- revisión humana
- UI
- modo `write`

## Agradecimientos

Gracias a **CanisLycaon** por sus traducciones, que se usaron como material de referencia para evaluar y mejorar la `Book Bible`, ajustar prompts y calibrar heurísticas de consistencia editorial.

Ese material se utilizó como referencia de calidad dentro del proyecto para comparar salidas y reducir ruido en contexto, no para hardcodear reglas específicas de una sola obra.

## Licencia

MIT.
