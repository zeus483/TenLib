# tenlib/cli.py
import sys
import click
from dotenv import load_dotenv

from tenlib.factory import build_orchestrator
from tenlib.orchestrator import BookAlreadyDoneError
from tenlib.router.router import AllModelsExhaustedError


# Carga .env una sola vez, antes que cualquier otra cosa
load_dotenv()

# Extensiones soportadas
_SUPPORTED_FORMATS = {".epub", ".txt", ".md", ".pdf"}


# ------------------------------------------------------------------
# Grupo raíz
# ------------------------------------------------------------------

@click.group()
@click.version_option(package_name="tenlib")
def main():
    """
    TenLib — editor literario agéntico.

    Traduce, corrige y escribe libros completos con IA,
    preservando coherencia y optimizando el uso de tokens.
    """


# ------------------------------------------------------------------
# tenlib translate
# ------------------------------------------------------------------

@main.command()
@click.option(
    "--book", "-b",
    required = True,
    type     = click.Path(exists=False),   # validamos nosotros para mejor mensaje
    help     = "Ruta al archivo del libro (.epub, .txt, .md)",
)
@click.option(
    "--from", "source_lang",
    required = True,
    metavar  = "LANG",
    help     = "Idioma de origen (ej: en, ja, fr)",
)
@click.option(
    "--to", "target_lang",
    required = True,
    metavar  = "LANG",
    help     = "Idioma de destino (ej: es, en)",
)
@click.option(
    "--chunk-size",
    default      = "standard",
    show_default = True,
    type         = click.Choice(["standard", "large", "xlarge"], case_sensitive=False),
    help         = "Tamaño de los chunks: standard (800-2000), large (1200-3500), xlarge (2000-5000 tokens)",
)
def translate(book: str, source_lang: str, target_lang: str, chunk_size: str):
    """Traduce un libro completo preservando voz narrativa y coherencia."""

    # ── Validaciones de entrada ───────────────────────────────────
    _validate_file(book)
    _validate_lang(source_lang, "--from")
    _validate_lang(target_lang, "--to")

    if source_lang.lower() == target_lang.lower():
        _abort("El idioma de origen y destino no pueden ser el mismo.")

    # ── Ensamblar pipeline ────────────────────────────────────────
    try:
        orchestrator = build_orchestrator(chunk_size=chunk_size)
    except FileNotFoundError as e:
        _abort(str(e))
    except RuntimeError as e:
        _abort(str(e))

    # ── Ejecutar ──────────────────────────────────────────────────
    try:
        result = orchestrator.run(
            file_path   = book,
            source_lang = source_lang.lower(),
            target_lang = target_lang.lower(),
        )

    except BookAlreadyDoneError:
        _handle_already_done(book)
        return

    except AllModelsExhaustedError as e:
        _error(
            f"Sin modelos disponibles. {e}\n"
            f"Reejecutando el mismo comando cuando tengas quota disponible "
            f"el proceso se reanudará automáticamente."
        )
        sys.exit(2)

    except FileNotFoundError:
        _abort(f"Archivo no encontrado: {book}")

    except KeyboardInterrupt:
        click.echo(
            "\n[tenlib] Proceso interrumpido. "
            "Ejecuta el mismo comando para reanudarlo desde donde quedó."
        )
        sys.exit(0)

    except Exception as e:
        _error(
            f"Error inesperado: {type(e).__name__}: {e}\n\n"
            f"Si el problema persiste, abre un issue en:\n"
            f"https://github.com/tu-usuario/tenlib/issues"
        )
        sys.exit(1)

    # ── Resumen final ─────────────────────────────────────────────
    _print_summary(result)


# ------------------------------------------------------------------
# tenlib fix
# ------------------------------------------------------------------

@main.command()
@click.option(
    "--translation",
    required = True,
    type     = click.Path(exists=False),
    help     = "Archivo con la traducción existente (.epub, .txt, .md)",
)
@click.option(
    "--original",
    required = False,
    type     = click.Path(exists=False),
    help     = "Archivo original de referencia (.epub, .txt, .md). Opcional.",
)
@click.option(
    "--to", "target_lang",
    required = True,
    metavar  = "LANG",
    help     = "Idioma destino de la traducción corregida (ej: es, en)",
)
@click.option(
    "--from", "source_lang",
    default      = "auto",
    show_default = True,
    metavar      = "LANG",
    help         = "Idioma del original (opcional). Usa 'auto' si no lo sabes.",
)
@click.option(
    "--chunk-size",
    default      = "standard",
    show_default = True,
    type         = click.Choice(["standard", "large", "xlarge"], case_sensitive=False),
    help         = "Tamaño de los chunks: standard (800-2000), large (1200-3500), xlarge (2000-5000 tokens)",
)
def fix(translation: str, original: str | None, target_lang: str, source_lang: str, chunk_size: str):
    """
    Corrige una traducción existente.
    - Con --original: corrección contra referencia.
    - Sin --original: fix-style (mejora fluidez/sintaxis sin referencia).
    """
    _validate_file(translation)
    if original:
        _validate_file(original)
    _validate_lang(target_lang, "--to")
    _validate_lang(source_lang, "--from")

    if (
        original
        and source_lang.lower() != "auto"
        and source_lang.lower() == target_lang.lower()
    ):
        _abort("El idioma de origen y destino no pueden ser el mismo.")

    try:
        orchestrator = build_orchestrator(chunk_size=chunk_size)
    except FileNotFoundError as e:
        _abort(str(e))
    except RuntimeError as e:
        _abort(str(e))

    try:
        if original:
            result = orchestrator.run_fix(
                original_path    = original,
                translation_path = translation,
                source_lang      = source_lang.lower(),
                target_lang      = target_lang.lower(),
            )
        else:
            result = orchestrator.run_fix_style(
                translation_path = translation,
                source_lang      = source_lang.lower(),
                target_lang      = target_lang.lower(),
            )

    except BookAlreadyDoneError:
        _handle_already_done(translation, action_label="corregido")
        return

    except AllModelsExhaustedError as e:
        _error(
            f"Sin modelos disponibles. {e}\n"
            f"Reejecutando el mismo comando cuando tengas quota disponible "
            f"el proceso se reanudará automáticamente."
        )
        sys.exit(2)

    except FileNotFoundError as e:
        _abort(str(e))

    except KeyboardInterrupt:
        click.echo(
            "\n[tenlib] Proceso interrumpido. "
            "Ejecuta el mismo comando para reanudarlo desde donde quedó."
        )
        sys.exit(0)

    except Exception as e:
        _error(
            f"Error inesperado: {type(e).__name__}: {e}\n\n"
            f"Si el problema persiste, abre un issue en:\n"
            f"https://github.com/tu-usuario/tenlib/issues"
        )
        sys.exit(1)

    _print_summary(result)


# ------------------------------------------------------------------
# Stubs — visión completa del proyecto en --help
# ------------------------------------------------------------------


@main.command()
@click.option("--book", "-b", required=True, help="Libro procesado a revisar")
def review(book: str):
    """[Próximamente] Abre la interfaz de revisión humana."""
    click.echo("[tenlib] El comando 'review' estará disponible en la Fase 4.")


@main.command()
@click.option("--outline", "-o", required=True, help="Archivo con el esquema del libro")
def write(outline: str):
    """[Próximamente] Modo co-autor: desarrolla una idea hasta un libro completo."""
    click.echo("[tenlib] El comando 'write' estará disponible en la Fase 4.")


# ------------------------------------------------------------------
# Helpers de validación
# ------------------------------------------------------------------

def _validate_file(path: str) -> None:
    """Verifica existencia y formato del archivo."""
    from pathlib import Path

    p = Path(path)

    if not p.exists():
        _abort(f"Archivo no encontrado: {path}")

    if not p.is_file():
        _abort(f"La ruta no es un archivo: {path}")

    if p.suffix.lower() not in _SUPPORTED_FORMATS:
        supported = ", ".join(sorted(_SUPPORTED_FORMATS))
        _abort(
            f"Formato no soportado: '{p.suffix}'\n"
            f"Formatos disponibles: {supported}"
        )


def _validate_lang(code: str, option: str) -> None:
    """Valida que el código de idioma sea razonable."""
    code = code.strip()

    if not code:
        _abort(f"{option} no puede estar vacío.")

    if not code.replace("-", "").isalpha():
        _abort(
            f"{option} contiene caracteres inválidos: '{code}'\n"
            f"Ejemplos válidos: en, es, ja, fr, pt-br"
        )

    if len(code) > 10:
        _abort(f"{option}: código de idioma demasiado largo: '{code}'")


def _handle_already_done(book: str, action_label: str = "traducido") -> None:
    """
    El libro ya está completamente procesado.
    Pregunta al usuario antes de reprocesar desde cero.
    """
    click.echo(f"\n[tenlib] Este libro ya fue {action_label} completamente.")

    if click.confirm("¿Deseas volver a procesarlo desde cero?", default=False):
        # TODO Fase 2: reset del libro en storage
        click.echo(
            "[tenlib] Reset no implementado todavía. "
            "Elimina el archivo y vuelve a ejecutar el comando."
        )
    else:
        click.echo("[tenlib] Sin cambios.")


# ------------------------------------------------------------------
# Helpers de output
# ------------------------------------------------------------------

def _print_summary(result) -> None:
    """Imprime el resumen final del pipeline."""
    pending = result.total_chunks - result.translated - result.flagged

    click.echo("")
    click.echo("─" * 50)
    if pending > 0:
        click.echo(f"[tenlib] ⚠ Proceso pausado")
    else:
        click.echo(f"[tenlib] ✓ Proceso completado")
    click.echo(f"[tenlib]   Total chunks : {result.total_chunks}")
    click.echo(f"[tenlib]   Traducidos   : {result.translated}")

    if result.flagged:
        click.echo(
            click.style(
                f"[tenlib]   Flaggeados   : {result.flagged} (requieren revisión)",
                fg="yellow",
            )
        )

    if pending > 0:
        click.echo(f"[tenlib]   Pendientes   : {pending}")

    if result.was_resumed:
        click.echo(f"[tenlib]   Modo         : reanudación")

    click.echo(f"[tenlib]   Output       : {result.output_path}")
    click.echo("─" * 50)


def _abort(message: str) -> None:
    """Error de validación — culpa del usuario."""
    click.echo(click.style(f"[tenlib] Error: {message}", fg="red"), err=True)
    sys.exit(1)


def _error(message: str) -> None:
    """Error de sistema — no es culpa del usuario."""
    click.echo(click.style(f"[tenlib] {message}", fg="red"), err=True)
