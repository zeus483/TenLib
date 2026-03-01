# tenlib/factory.py
from pathlib import Path
from typing import Optional

from tenlib.orchestrator import Orchestrator
from tenlib.reconstructor import Reconstructor
from tenlib.processor.parsers.factory import ParserFactory
from tenlib.processor.chunker.chunker import Chunker
from tenlib.processor.chunker.models import ChunkConfig
from tenlib.router.router import Router
from tenlib.router.claude import ClaudeAdapter
from tenlib.router.gemini import GeminiAdapter
from tenlib.router.config_loader import load_model_configs
from tenlib.storage.repository import Repository
from tenlib.context.compressor import BibleCompressor
from tenlib.context.extractor import BibleExtractor


_CHUNK_PRESETS: dict[str, dict] = {
    "standard": {"min_tokens": 800,  "max_tokens": 2000, "target_tokens": 1400},
    "large":    {"min_tokens": 1200, "max_tokens": 3500, "target_tokens": 2500},
    "xlarge":   {"min_tokens": 2000, "max_tokens": 5000, "target_tokens": 3500},
}


def build_orchestrator(
    db_path:     Optional[str]  = None,
    config_path: Optional[str]  = None,
    output_dir:  Optional[Path] = None,
    chunk_size:  str            = "standard",
) -> Orchestrator:
    """
    Ensambla el Orchestrator con todas sus dependencias.
    Punto de entrada único para el CLI y los tests de integración.

    chunk_size: "standard" | "large" | "xlarge" — controla el tamaño de los chunks.
    El output siempre es TXT, independientemente del formato de entrada.
    """
    repo   = Repository(db_path=db_path)
    models = _build_models(repo, config_path)
    router = Router(models)

    preset        = _CHUNK_PRESETS.get(chunk_size, _CHUNK_PRESETS["standard"])
    chunk_cfg     = ChunkConfig(**preset)
    reconstructor = Reconstructor(repo, output_dir)

    return Orchestrator(
        repo            = repo,
        parser_factory  = ParserFactory(),
        chunker         = Chunker(config=chunk_cfg),
        router          = router,
        reconstructor   = reconstructor,
        extractor       = BibleExtractor(model=router),  # usa failover del router
        compressor      = BibleCompressor(),
    )


def _build_models(repo: Repository, config_path: Optional[str]) -> list:
    """
    Carga el config y construye los adaptadores disponibles.
    Si un adaptador no tiene api_key configurada, lo omite silenciosamente.
    """
    configs  = load_model_configs(config_path)
    adapters = {
        "claude": ClaudeAdapter,
        "gemini": GeminiAdapter,
    }
    models = []

    for config in configs:
        adapter_class = adapters.get(config.name)
        if not adapter_class:
            continue
        if not config.api_key:
            print(f"[tenlib] ⚠ {config.name}: sin api_key, omitiendo")
            continue
        models.append(adapter_class(config, repo))

    if not models:
        raise RuntimeError(
            "Ningún modelo configurado. "
            "Revisa ~/.tenlib/config.yaml y tus variables de entorno."
        )

    return models
