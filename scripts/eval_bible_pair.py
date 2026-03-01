#!/usr/bin/env python3
"""
Evalua calidad de extraccion de personajes/Bible con un par:
- referencia "buena"
- candidato "malo" (o salida a evaluar)

Uso:
  venv/bin/python scripts/eval_bible_pair.py \
    --good "ejemplos_entrenamiento/...prologo_bueno.txt" \
    --bad  "ejemplos_entrenamiento/prologo_malo.txt"
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from tenlib.context.bible import BibleUpdate, BookBible
from tenlib.context.character_detector import extract_character_mentions
from tenlib.context.compressor import BibleCompressor


@dataclass
class EvalSnapshot:
    characters: set[str]
    bible_characters: int
    avg_prompt_chars: float
    max_prompt_chars: int


def _chunk_by_paragraphs(text: str, target_chars: int) -> list[str]:
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    chunks: list[str] = []
    buf: list[str] = []
    current = 0

    for block in blocks:
        add = len(block) + (2 if buf else 0)
        if buf and current + add > target_chars:
            chunks.append("\n\n".join(buf))
            buf = [block]
            current = len(block)
        else:
            buf.append(block)
            current += add

    if buf:
        chunks.append("\n\n".join(buf))
    return chunks


def _evaluate_text(text: str, chunk_chars: int, max_chars_per_chunk: int) -> EvalSnapshot:
    chunks = _chunk_by_paragraphs(text, target_chars=chunk_chars)
    compressor = BibleCompressor()
    bible = BookBible.empty()
    prompt_sizes: list[int] = []

    for chunk in chunks:
        update = BibleUpdate(
            characters=extract_character_mentions(
                source_text="",
                translated_text=chunk,
                max_characters=max_chars_per_chunk,
                existing_characters=bible.characters,
            ),
            last_scene=chunk[:280],
        )
        bible.apply(update)
        compressed = compressor.compress(bible, chunk)
        prompt_sizes.append(len(compressed.to_json()))

    avg_prompt = (sum(prompt_sizes) / len(prompt_sizes)) if prompt_sizes else 0.0
    max_prompt = max(prompt_sizes) if prompt_sizes else 0
    return EvalSnapshot(
        characters=set(bible.characters.keys()),
        bible_characters=len(bible.characters),
        avg_prompt_chars=avg_prompt,
        max_prompt_chars=max_prompt,
    )


def _exact_metrics(gold: set[str], pred: set[str]) -> dict[str, float]:
    inter = gold & pred
    precision = len(inter) / len(pred) if pred else 0.0
    recall = len(inter) / len(gold) if gold else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "tp": len(inter),
        "pred": len(pred),
        "gold": len(gold),
    }


def _fuzzy_metrics(gold: set[str], pred: set[str], threshold: float) -> dict[str, float]:
    gold_left = set(gold)
    tp = 0
    for cand in pred:
        best = None
        best_score = 0.0
        for ref in gold_left:
            score = SequenceMatcher(None, cand.lower(), ref.lower()).ratio()
            if score > best_score:
                best_score = score
                best = ref
        if best is not None and best_score >= threshold:
            tp += 1
            gold_left.remove(best)

    precision = tp / len(pred) if pred else 0.0
    recall = tp / len(gold) if gold else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "tp": tp,
        "pred": len(pred),
        "gold": len(gold),
        "threshold": threshold,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Eval Bible/characters para par bueno-malo")
    parser.add_argument("--good", required=True, help="Ruta al txt bueno (referencia)")
    parser.add_argument("--bad", required=True, help="Ruta al txt malo/candidato")
    parser.add_argument("--chunk-chars", type=int, default=1200, help="Tamaño objetivo de chunk")
    parser.add_argument("--max-characters-per-chunk", type=int, default=40, help="Top personajes por chunk")
    parser.add_argument("--fuzzy-threshold", type=float, default=0.84, help="Umbral fuzzy 0..1")
    args = parser.parse_args()

    good_text = Path(args.good).read_text(encoding="utf-8", errors="ignore")
    bad_text = Path(args.bad).read_text(encoding="utf-8", errors="ignore")

    good_eval = _evaluate_text(
        text=good_text,
        chunk_chars=args.chunk_chars,
        max_chars_per_chunk=args.max_characters_per_chunk,
    )
    bad_eval = _evaluate_text(
        text=bad_text,
        chunk_chars=args.chunk_chars,
        max_chars_per_chunk=args.max_characters_per_chunk,
    )

    exact = _exact_metrics(good_eval.characters, bad_eval.characters)
    fuzzy = _fuzzy_metrics(good_eval.characters, bad_eval.characters, args.fuzzy_threshold)

    report = {
        "good": {
            "characters_count": good_eval.bible_characters,
            "characters": sorted(good_eval.characters),
            "avg_prompt_chars": round(good_eval.avg_prompt_chars, 2),
            "max_prompt_chars": good_eval.max_prompt_chars,
        },
        "bad": {
            "characters_count": bad_eval.bible_characters,
            "characters": sorted(bad_eval.characters),
            "avg_prompt_chars": round(bad_eval.avg_prompt_chars, 2),
            "max_prompt_chars": bad_eval.max_prompt_chars,
        },
        "metrics_exact": {
            **{k: (round(v, 4) if isinstance(v, float) else v) for k, v in exact.items()},
            "extra_in_bad": sorted(bad_eval.characters - good_eval.characters),
            "missing_in_bad": sorted(good_eval.characters - bad_eval.characters),
        },
        "metrics_fuzzy": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in fuzzy.items()},
    }

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
