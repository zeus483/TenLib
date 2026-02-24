# chunker/chunker.py
from .detector import BoundaryDetector
from .normalizer import ChunkNormalizer
from .models import ChunkConfig
from .token_estimator import TokenEstimator, SimpleTokenEstimator
from ..models import RawBook, Chunk


class Chunker:

    def __init__(
        self,
        config: ChunkConfig | None = None,
        estimator: TokenEstimator | None = None,
    ):
        self._config = config or ChunkConfig()
        self._estimator = estimator or SimpleTokenEstimator()
        self._detector = BoundaryDetector(self._config, self._estimator)
        self._normalizer = ChunkNormalizer(self._config, self._estimator)

    def chunk(self, book: RawBook) -> list[Chunk]:
        all_chunks: list[Chunk] = []
        global_index = 0

        for section_idx, section_text in enumerate(book.sections):
            segments = self._detector.detect(section_text, source_section=section_idx)
            chunks = self._normalizer.normalize(segments)

            # Re-indexar globalmente (el normalizer indexa por sección)
            for chunk in chunks:
                chunk.index = global_index
                global_index += 1
                all_chunks.append(chunk)

        return all_chunks