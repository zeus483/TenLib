# chunker/normalizer.py
from .models import TextSegment, BoundaryType, ChunkConfig
from .token_estimator import TokenEstimator
from ..models import Chunk, ChunkStatus


class ChunkNormalizer:
    """
    Pasada 2: toma segmentos semánticos y los ajusta al rango de tokens.
    Devuelve la lista final de Chunks listos para el pipeline.
    """

    def __init__(self, config: ChunkConfig, estimator: TokenEstimator):
        self._config = config
        self._estimator = estimator

    def normalize(self, segments: list[TextSegment]) -> list[Chunk]:
        if not segments:
            return []

        # Primero resolver segmentos grandes (pueden generar varios)
        expanded = self._expand_large_segments(segments)

        # Luego fusionar segmentos pequeños
        merged = self._merge_small_segments(expanded)

        # Convertir a Chunks finales
        return self._to_chunks(merged)

    # ------------------------------------------------------------------
    # Expansión de segmentos grandes
    # ------------------------------------------------------------------

    def _expand_large_segments(
        self, segments: list[TextSegment]
    ) -> list[TextSegment]:
        result = []
        for seg in segments:
            if seg.token_estimated <= self._config.max_tokens:
                result.append(seg)
            else:
                result.extend(self._split_segment(seg))
        return result

    def _split_segment(self, segment: TextSegment) -> list[TextSegment]:
        """
        Divide un segmento grande usando párrafos.
        Si un párrafo solo ya es demasiado grande, baja al nivel de oraciones.
        Nunca corta dentro de una oración.
        """
        paragraphs = [p.strip() for p in segment.text.split("\n\n") if p.strip()]

        if len(paragraphs) <= 1:
            # Solo hay un párrafo enorme — bajar a oraciones
            return self._split_by_sentences(segment)

        result: list[TextSegment] = []
        current_parts: list[str] = []
        current_tokens = 0

        for para in paragraphs:
            para_tokens = self._estimator.estimate(para)

            if para_tokens > self._config.max_tokens:
                # Este párrafo solo ya es demasiado grande
                if current_parts:
                    result.append(self._make_subsegment(
                        "\n\n".join(current_parts), segment
                    ))
                    current_parts = []
                    current_tokens = 0
                # Dividir el párrafo por oraciones
                mini_seg = self._make_subsegment(para, segment)
                result.extend(self._split_by_sentences(mini_seg))
                continue

            if current_tokens + para_tokens > self._config.max_tokens and current_parts:
                # Añadir este párrafo sobrepasaría el límite — cerrar chunk actual
                result.append(self._make_subsegment(
                    "\n\n".join(current_parts), segment
                ))
                current_parts = [para]
                current_tokens = para_tokens
            else:
                current_parts.append(para)
                current_tokens += para_tokens

        if current_parts:
            result.append(self._make_subsegment(
                "\n\n".join(current_parts), segment
            ))

        return result

    def _split_by_sentences(self, segment: TextSegment) -> list[TextSegment]:
        """Último recurso: divide por oraciones usando puntuación."""
        import re
        # Patrón que respeta puntos en abreviaciones y elipsis
        sentence_endings = re.compile(
            r'(?<=[.!?…])\s+(?=[A-ZÁÉÍÓÚÑ""«—])'
        )
        sentences = sentence_endings.split(segment.text)

        result: list[TextSegment] = []
        current_parts: list[str] = []
        current_tokens = 0

        for sentence in sentences:
            sentence_tokens = self._estimator.estimate(sentence)

            # Oración individual que supera el máximo — no queda otra que incluirla sola
            if sentence_tokens > self._config.max_tokens:
                if current_parts:
                    result.append(self._make_subsegment(
                        " ".join(current_parts), segment
                    ))
                    current_parts = []
                    current_tokens = 0
                result.append(self._make_subsegment(sentence, segment))
                continue

            if current_tokens + sentence_tokens > self._config.max_tokens and current_parts:
                result.append(self._make_subsegment(
                    " ".join(current_parts), segment
                ))
                current_parts = [sentence]
                current_tokens = sentence_tokens
            else:
                current_parts.append(sentence)
                current_tokens += sentence_tokens

        if current_parts:
            result.append(self._make_subsegment(
                " ".join(current_parts), segment
            ))

        return result

    # ------------------------------------------------------------------
    # Fusión de segmentos pequeños
    # ------------------------------------------------------------------

    def _merge_small_segments(
        self, segments: list[TextSegment]
    ) -> list[TextSegment]:
        """
        Fusiona segmentos consecutivos que están por debajo del mínimo.
        Regla: nunca fusionar si el límite entre ellos es de nivel CHAPTER.
        Los capítulos son fronteras sagradas.
        """
        if not segments:
            return []

        result: list[TextSegment] = [segments[0]]

        for current in segments[1:]:
            previous = result[-1]
            combined_tokens = previous.token_estimated + current.token_estimated

            can_merge = (
                previous.token_estimated < self._config.min_tokens
                and combined_tokens <= self._config.max_tokens
                and current.boundary_type != BoundaryType.CHAPTER
                and previous.boundary_type != BoundaryType.CHAPTER
            )

            if can_merge:
                merged_text = previous.text + "\n\n" + current.text
                result[-1] = TextSegment(
                    text=merged_text,
                    boundary_type=previous.boundary_type,
                    source_section=previous.source_section,
                    original_position=previous.original_position,
                    token_estimated=self._estimator.estimate(merged_text),
                )
            else:
                result.append(current)

        return result

    # ------------------------------------------------------------------
    # Conversión final a Chunks
    # ------------------------------------------------------------------

    def _to_chunks(self, segments: list[TextSegment]) -> list[Chunk]:
        return [
            Chunk(
                index=i,
                original=seg.text,
                token_estimated=seg.token_estimated,
                source_section=seg.source_section,
                status=ChunkStatus.PENDING,
            )
            for i, seg in enumerate(segments)
        ]

    def _make_subsegment(self, text: str, parent: TextSegment) -> TextSegment:
        return TextSegment(
            text=text,
            boundary_type=BoundaryType.PARAGRAPH,
            source_section=parent.source_section,
            original_position=parent.original_position,
            token_estimated=self._estimator.estimate(text),
        )