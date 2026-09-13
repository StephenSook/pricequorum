"""Precision, recall and F1 of plan matching over the hand-labeled pairs in labeled_plans.csv.

Usage, from backend/:
    uv run python -m evals.resolver_report --base-url https://<backend>

The harness reaches the resolver only over HTTP. It needs a scoring endpoint that the contract does not
define yet: POST /api/resolver/match {left, right} returning {match: bool, score: int}, where left and
right are {label, currency, interval}. When the backend's OpenAPI document has no such path, the report
prints NOT RUNNABLE and exits 2 rather than inventing numbers.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx

LABELS = Path(__file__).resolve().parent / "labeled_plans.csv"
MATCH_PATH = "/api/resolver/match"


@dataclass(frozen=True)
class LabeledPair:
    left: dict[str, str]
    right: dict[str, str]
    is_match: bool
    note: str


def load_pairs(path: Path = LABELS) -> list[LabeledPair]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    pairs = []
    for row in rows:
        if row["is_match"] not in ("0", "1"):
            raise ValueError(f"is_match must be 0 or 1, got {row['is_match']!r} for {row['left_label']}")
        pairs.append(
            LabeledPair(
                left={"label": row["left_label"], "currency": row["left_currency"], "interval": row["left_interval"]},
                right={
                    "label": row["right_label"],
                    "currency": row["right_currency"],
                    "interval": row["right_interval"],
                },
                is_match=row["is_match"] == "1",
                note=row["note"],
            )
        )
    return pairs


def precision_recall_f1(labels: list[bool], predictions: list[bool]) -> tuple[float, float, float]:
    """Precision and recall of the match class. Undefined ratios are reported as 0.0."""
    if len(labels) != len(predictions):
        raise ValueError("labels and predictions must have the same length")
    true_pos = sum(1 for label, pred in zip(labels, predictions, strict=True) if label and pred)
    false_pos = sum(1 for label, pred in zip(labels, predictions, strict=True) if not label and pred)
    false_neg = sum(1 for label, pred in zip(labels, predictions, strict=True) if label and not pred)
    precision = true_pos / (true_pos + false_pos) if true_pos + false_pos else 0.0
    recall = true_pos / (true_pos + false_neg) if true_pos + false_neg else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Resolver precision, recall and F1")
    parser.add_argument("--base-url", default=os.environ.get("PQ_BASE_URL"))
    args = parser.parse_args(argv)
    pairs = load_pairs()
    matches = sum(1 for pair in pairs if pair.is_match)
    print(f"{len(pairs)} labeled pairs: {matches} matches, {len(pairs) - matches} non-matches")
    if not args.base_url:
        print("NOT RUNNABLE: set --base-url or PQ_BASE_URL")
        return 2
    base = args.base_url.rstrip("/")
    with httpx.Client(timeout=30.0) as client:
        spec = client.get(f"{base}/openapi.json")
        paths = spec.json().get("paths", {}) if spec.status_code == 200 else {}
        if MATCH_PATH not in paths:
            print(
                f"NOT RUNNABLE: the backend exposes no {MATCH_PATH} endpoint, so the resolver cannot be scored over HTTP"
            )
            return 2
        predictions = []
        for pair in pairs:
            response = client.post(f"{base}{MATCH_PATH}", json={"left": pair.left, "right": pair.right})
            body = response.json() if response.status_code == 200 else {}
            if not isinstance(body.get("match"), bool):
                print(f"NOT RUNNABLE: {MATCH_PATH} answered {response.status_code} without a boolean match")
                return 2
            predictions.append(body["match"])
    precision, recall, f1 = precision_recall_f1([pair.is_match for pair in pairs], predictions)
    print(f"precision {precision:.3f}, recall {recall:.3f}, F1 {f1:.3f}")
    for pair, prediction in zip(pairs, predictions, strict=True):
        if prediction != pair.is_match:
            print(f"  wrong: {pair.left['label']} vs {pair.right['label']} predicted {prediction} ({pair.note})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
