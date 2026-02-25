from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

#chuckStatus Enum

class ChunkStatus(Enum):
    PENDING = "pending"
    DONE = "done"
    FLAGGED = "flagged"
    REVIEWED = "reviewed"

@dataclass
class RawBook:
    """Lo que sale de cualquier Parser: texto limpio + metadata"""
    title: str
    source_path: str
    sections: list[str] #las secciones como texto
    detected_language: Optional[str] = None

#los chunks Unidades de trabajo
@dataclass
class Chunk:
    """Unidad de trabajo del pipeline."""
    index: int
    original: str
    token_estimated: int
    source_section: int
    translated: Optional[str] = None
    model_used: Optional[str] = None
    confidence: Optional[float] = None
    status: ChunkStatus = ChunkStatus.PENDING
    flags: list[str] = field(default_factory=list)
