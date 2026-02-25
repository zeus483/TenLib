# storage/models.py
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class BookStatus(Enum):
    IN_PROGRESS = "in_progress"
    REVIEW      = "review"
    DONE        = "done"


class BookMode(Enum):
    TRANSLATE = "translate"
    FIX       = "fix"
    WRITE     = "write"


class ChunkStatus(Enum):
    PENDING  = "pending"
    DONE     = "done"
    FLAGGED  = "flagged"
    REVIEWED = "reviewed"


@dataclass
class StoredBook:
    id:          int
    title:       str
    file_hash:   str
    mode:        BookMode
    status:      BookStatus
    created_at:  str
    source_lang: Optional[str] = None
    target_lang: Optional[str] = None


@dataclass
class StoredChunk:
    id:              int
    book_id:         int
    chunk_index:     int
    original:        str
    status:          ChunkStatus
    translated:      Optional[str]  = None
    model_used:      Optional[str]  = None
    confidence:      Optional[float] = None
    token_estimated: Optional[int]  = None
    source_section:  Optional[int]  = None
    flags:           list[str]      = field(default_factory=list)