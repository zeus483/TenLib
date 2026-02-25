from chunker.models import ChunkConfig
from chunker.detector import BoundaryDetector
from chunker.token_estimator import SimpleTokenEstimator

c = ChunkConfig()
d = BoundaryDetector(c, SimpleTokenEstimator())
for p in d._compiled[BoundaryType.CHAPTER]:
    print(p.pattern, p.match("Capítulo 1"))
