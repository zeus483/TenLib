from tenlib.processor.chunker.models import ChunkConfig, BoundaryType
from tenlib.processor.chunker.detector import BoundaryDetector
from tenlib.processor.chunker.token_estimator import SimpleTokenEstimator

c = ChunkConfig()
d = BoundaryDetector(c, SimpleTokenEstimator())
print("compiled:", d._compiled[BoundaryType.CHAPTER])
p = d._compiled[BoundaryType.CHAPTER][0]
print(p.pattern)
print("MATCH?", p.match("Capítulo 1"))
