from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

class BoundaryType(Enum):
    """Que tipo de limite marco el inicio de este segmento."""
    CHAPTER = "chapter"
    SCENE = "scene"
    POV = "pov"
    PARAGRAPH = "paragraph"
    SENTENCE = "sentence"
    
@dataclass
class TextSegment:
    """
    Resultado de la pasada 1.
    Fragmento semanticamente coherente, SIN restricciones de tamaño todavia.
    """
    text:str
    boundary_type: BoundaryType
    source_section: int         #indice de seccion del RawBook
    original_position: int      #posicion original en el texto para reconstruccion
    token_estimated: int = 0    #se llena despues de crear el segmento

@dataclass
class ChunkConfig:
    """Configuracion del chunker. Centralizada y explicita."""
    min_tokens: int = 800
    max_tokens: int = 2000
    target_tokens: int = 1400 #punto ideal de tokens

    # Patrones de detección (se pueden sobreescribir por género)
    chapter_patterns: list[str] = field(default_factory=lambda: [
        r'^\s*cap[ií]tulo\s+[\dIVXLCivxlc]+',
        r'^\s*chapter\s+[\dIVXLCivxlc]+',
        r'^\s*第[一二三四五六七八九十百千]+章',   # japonés/chino
        r'^\s*#{1,2}\s+.+',                      # markdown
        r'^\s*PART\s+[\dIVXLCivxlc]+',
        r'^\s*[IVXLCivxlc]{1,6}\.\s*$',         # "IV." solo en línea
    ])
    
    scene_patterns: list[str] = field(default_factory=lambda: [
        r'^\s*[*\-—]{3,}\s*$',      # *** o --- o ———
        r'^\s*[*\-—]\s*[*\-—]\s*[*\-—]\s*$',   # * * *
        r'^\s*·{3,}\s*$',
        r'^\s*#{3,}\s*$',           # ### sin texto
        r'^\s*$\n^\s*$',            # doble línea vacía (se maneja diferente)
    ])
    
    pov_patterns: list[str] = field(default_factory=lambda: [
        r'^\s*\*{1,2}[A-ZÁÉÍÓÚ][^*]+\*{1,2}\s*$',   # *Nombre*
        r'^\s*[A-ZÁÉÍÓÚ]{2,}[^.!?]*$',               # NOMBRE solo en línea
    ])

    paragraph_patterns: list[str] = field(default_factory=lambda: [
        r'\n\s*\n',                  # Doble salto de línea (párrafo estándar)
        r'^\s{2,}',                  # Línea que inicia con sangría
        r'^\t',                      # Línea que inicia con tabulación
    ])

    sentence_patterns: list[str] = field(default_factory=lambda: [
        r'(?<=[.!?])\s+',            # Punto/exclamación/interrogación seguido de espacio
        r'(?<=[.!?]["”])\s+',        # Punto seguido de comilla de cierre y espacio
        r'(?<=[.!?])(?=\n|$)',       # Punto seguido de salto de línea o fin de texto
    ])
    