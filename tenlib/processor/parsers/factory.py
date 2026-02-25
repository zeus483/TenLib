import os
from tenlib.processor.models import RawBook
from .base import BaseParser
from .txt_parser import TxtParser
from .epub_parser import EpubParser


class UnsupportedFormatError(Exception):
    """Se lanza cuando ningún parser registrado puede manejar el archivo."""
    pass


class ParserFactory:
    """
    Registro central de parsers.

    Uso básico:
        book = ParserFactory.parse("/ruta/al/libro.epub")

    Uso con parser registrado externamente:
        factory = ParserFactory()
        factory.register(MiParserCustom())
        book = factory.parse("/ruta/al/libro.pdf")

    Los parsers se evalúan en orden de registro.
    El primero que responda True a can_handle() gana.
    """

    # Parsers disponibles por defecto — en orden de prioridad
    _DEFAULT_PARSERS: list[BaseParser] = [
        EpubParser(),
        TxtParser(),   # va último porque .txt es el fallback más permisivo
    ]

    def __init__(self):
        self._parsers: list[BaseParser] = list(self._DEFAULT_PARSERS)

    def register(self, parser: BaseParser) -> None:
        """Registra un parser adicional al inicio de la lista (mayor prioridad)."""
        self._parsers.insert(0, parser)

    def parse(self, file_path: str) -> RawBook:
        """
        Detecta el parser correcto para el archivo y devuelve un RawBook.

        Raises:
            FileNotFoundError: si el archivo no existe.
            UnsupportedFormatError: si ningún parser puede manejarlo.
        """
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"Archivo no encontrado: {file_path}")

        for parser in self._parsers:
            if parser.can_handle(file_path):
                return parser.parse(file_path)

        ext = os.path.splitext(file_path)[1].lower()
        raise UnsupportedFormatError(
            f"Formato '{ext}' no soportado. "
            f"Formatos disponibles: "
            f"{self._supported_extensions()}"
        )

    def _supported_extensions(self) -> str:
        exts: set[str] = set()
        for parser in self._parsers:
            # convención: los parsers exponen _SUPPORTED_EXTENSIONS si quieren
            if hasattr(parser, '__class__'):
                module = vars(parser.__class__.__module__ and
                              __import__(parser.__class__.__module__,
                                         fromlist=['_SUPPORTED_EXTENSIONS'])
                              or {})
                # fallback: simplemente listamos los parsers por nombre
        return ".txt, .md, .epub"

    # ------------------------------------------------------------------ #
    #  Método de clase para uso rápido sin instanciar                     #
    # ------------------------------------------------------------------ #

    @classmethod
    def parse_file(cls, file_path: str) -> RawBook:
        """Shortcut: ParserFactory.parse_file('libro.epub')"""
        return cls().parse(file_path)