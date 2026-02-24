import re
from .models import TextSegment, BoundaryType, ChunkConfig
from .token_estimator import TokenEstimator

class BoundaryDetector:
    """
    Responsabilidad unica: tomar texto plano y devolver lista de textsegments
    respetando la jerarquia semantica.
    no sabe nada de tamaños ni de tokens.
    """
    def __init__(self,config: ChunkConfig, estimator:TokenEstimator):
        self._config = config
        self._estimator = estimator
        self._compiled = self._compile_patterns()
    
    def detect(self, text:str, source_section:int=0,) -> list[TextSegment]:
        """
        Detecta todos los limites en el texto y devuelve una lista ordenada de TextSegments.
        """
        assert isinstance(text, str), "El Chunker debe recibir texto limpio como string, no bytes ni raw data. El Parser falló en la decodificación."
        
        lines = text.splitlines(keepends=True)
        segments: list[TextSegment] = []
        current_lines: list[str] = []
        current_start: int = 0
        current_boundary: BoundaryType = BoundaryType.PARAGRAPH
        char_position = 0

        for i, line in enumerate(lines):
            boundary = self._classify_line(line, lines, i)
            
            if boundary is not None:
                if current_lines:
                    # Cerrar el segmento anterior
                    segment_text = "".join(current_lines).strip()
                    if segment_text:
                        segments.append(TextSegment(
                            text=segment_text,
                            boundary_type=current_boundary,
                            source_section=source_section,
                            original_position=current_start,
                            token_estimated=self._estimator.estimate(segment_text)
                        ))
                    current_lines = [line]
                    current_start = char_position
                    current_boundary = boundary
                else:
                    # Es la primera línea y marca un límite
                    current_lines.append(line)
                    current_boundary = boundary
            else:
                current_lines.append(line)
            
            char_position += len(line)  
            
        # cerrar el último segmento
        if current_lines:
            segment_text = "".join(current_lines).strip()
            if segment_text:
                segments.append(TextSegment(
                    text=segment_text,
                    boundary_type=current_boundary,
                    source_section=source_section,
                    original_position=current_start,
                    token_estimated=self._estimator.estimate(segment_text)
                ))
        return [s for s in segments if s.text] # filtrar vacíos
    
    def _classify_line(self, line:str, all_lines:list[str], index:int) -> BoundaryType | None:
        """
        Retorna el tipo de límite si la línea marca el inicio de un nuevo
        segmento, o None si es continuación del segmento actual.
        Respeta la jerarquía: capítulo > escena > pov.
        """
        stripped = line.strip()
        
        # Doble linea vacia: escena
        if not stripped:
            if index > 0 and index < len(all_lines) - 1:
                prev_empty = not all_lines[index - 1].strip()
                # Verifica que la linea anterior sea vacía (doble salto)
                if prev_empty:
                    return BoundaryType.SCENE
            # Si es vacía pero no cumple lo anterior, la ignoramos.
            return None

        # 1. Capítulos
        for pattern in self._compiled[BoundaryType.CHAPTER]:
            if pattern.match(stripped):
                return BoundaryType.CHAPTER
        
        # 2. Escenas
        for pattern in self._compiled[BoundaryType.SCENE]:
            if pattern.match(stripped):
                return BoundaryType.SCENE
        # 3. pov
        for pattern in self._compiled[BoundaryType.POV]:
            if pattern.match(stripped):
                return BoundaryType.POV
        
        # 4. parrafo
        for pattern in self._compiled[BoundaryType.PARAGRAPH]:
            if pattern.match(stripped):
                return BoundaryType.PARAGRAPH
        
        # 5. oracion
        for pattern in self._compiled[BoundaryType.SENTENCE]:
            if pattern.match(stripped):
                return BoundaryType.SENTENCE
        
        return None

    def _compile_patterns(self) -> dict[BoundaryType, list[re.Pattern]]:
        """Compila los patrones regex para optimizar el detector."""
        return {
            BoundaryType.CHAPTER: [
                re.compile(p, re.IGNORECASE | re.MULTILINE)
                for p in self._config.chapter_patterns
            ],
            BoundaryType.SCENE: [
                re.compile(p, re.MULTILINE)
                for p in self._config.scene_patterns
            ],
            BoundaryType.POV: [
                re.compile(p, re.MULTILINE)
                for p in self._config.pov_patterns
            ],
            BoundaryType.PARAGRAPH: [
                re.compile(p, re.MULTILINE)
                for p in self._config.paragraph_patterns
            ],
            BoundaryType.SENTENCE: [
                re.compile(p, re.MULTILINE)
                for p in self._config.sentence_patterns
            ],
        }