"""Load and validate the OSI semantic model into an in-memory registry.

Parses ``osi/ngv_semantic_model.yaml`` into a :class:`SemanticModel` exposing the
dataset source, its metrics, and its dimensions (with the ANSI_SQL expressions the
resolver emits verbatim). The model is the allow-list: only names defined here can
ever be referenced by the tradebot's ``query_metric`` tool.

This loader intentionally supports the single-dataset shape this project uses (one
fact source = one read-only view). It is not a general OSI interpreter.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

# osi/ngv_semantic_model.yaml lives at the repo root.
_DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[3] / "osi" / "ngv_semantic_model.yaml"
_DIALECT = "ANSI_SQL"


@dataclass(frozen=True)
class Dimension:
    """A categorical (or time) attribute to slice/filter by."""

    name: str
    expression: str
    is_time: bool
    description: str | None
    synonyms: tuple[str, ...]


@dataclass(frozen=True)
class Metric:
    """A named aggregation expressed in SQL."""

    name: str
    expression: str
    description: str | None
    synonyms: tuple[str, ...]


@dataclass(frozen=True)
class SemanticModel:
    version: str
    dataset_name: str
    source: str
    metrics: dict[str, Metric]
    dimensions: dict[str, Dimension]

    @property
    def time_dimension(self) -> Dimension | None:
        for dim in self.dimensions.values():
            if dim.is_time:
                return dim
        return None


def _dialect_expression(node: dict[str, Any], *, context: str) -> str:
    """Extract the ANSI_SQL expression from an OSI ``expression.dialects`` block."""
    expression = node.get("expression")
    if not isinstance(expression, dict):
        raise ValueError(f"{context}: missing 'expression' block")
    dialects = expression.get("dialects")
    if not isinstance(dialects, list) or not dialects:
        raise ValueError(f"{context}: 'expression.dialects' must be a non-empty list")
    for entry in dialects:
        if isinstance(entry, dict) and entry.get("dialect") == _DIALECT:
            expr = entry.get("expression")
            if isinstance(expr, str) and expr.strip():
                return expr.strip()
    raise ValueError(f"{context}: no non-empty {_DIALECT} dialect expression")


def _synonyms(node: dict[str, Any]) -> tuple[str, ...]:
    ai_context = node.get("ai_context")
    if not isinstance(ai_context, dict):
        return ()
    syns = ai_context.get("synonyms")
    if not isinstance(syns, list):
        return ()
    return tuple(str(s) for s in syns if isinstance(s, str) and s.strip())


def load_model(path: Path | str | None = None) -> SemanticModel:  # noqa: C901, PLR0912 — linear parse-and-validate
    """Parse and validate the semantic model YAML at ``path``."""
    model_path = Path(path) if path is not None else _DEFAULT_MODEL_PATH
    with model_path.open("r", encoding="utf-8") as handle:
        doc = yaml.safe_load(handle)

    if not isinstance(doc, dict):
        raise ValueError("semantic model: top-level document must be a mapping")
    version = str(doc.get("version") or "")
    semantic_model = doc.get("semantic_model")
    if not isinstance(semantic_model, list) or not semantic_model:
        raise ValueError("semantic model: 'semantic_model' must be a non-empty list")

    entry = semantic_model[0]
    if not isinstance(entry, dict):
        raise ValueError("semantic model: first semantic_model entry must be a mapping")

    datasets = entry.get("datasets")
    if not isinstance(datasets, list) or not datasets:
        raise ValueError("semantic model: 'datasets' must be a non-empty list")
    dataset = datasets[0]
    if not isinstance(dataset, dict):
        raise ValueError("semantic model: first dataset must be a mapping")

    dataset_name = dataset.get("name")
    source = dataset.get("source")
    if not isinstance(dataset_name, str) or not dataset_name.strip():
        raise ValueError("semantic model: dataset 'name' is required")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("semantic model: dataset 'source' is required")

    dimensions: dict[str, Dimension] = {}
    for field in dataset.get("fields", []) or []:
        if not isinstance(field, dict):
            continue
        dim_block = field.get("dimension")
        if not isinstance(dim_block, dict):
            continue  # plain fact field, not a dimension
        name = field.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("semantic model: dimension field missing 'name'")
        dimensions[name] = Dimension(
            name=name,
            expression=_dialect_expression(field, context=f"dimension '{name}'"),
            is_time=bool(dim_block.get("is_time", False)),
            description=field.get("description"),
            synonyms=_synonyms(field),
        )

    metrics: dict[str, Metric] = {}
    for metric in entry.get("metrics", []) or []:
        if not isinstance(metric, dict):
            continue
        name = metric.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("semantic model: metric missing 'name'")
        metrics[name] = Metric(
            name=name,
            expression=_dialect_expression(metric, context=f"metric '{name}'"),
            description=metric.get("description"),
            synonyms=_synonyms(metric),
        )

    if not metrics:
        raise ValueError("semantic model: at least one metric is required")

    return SemanticModel(
        version=version,
        dataset_name=dataset_name.strip(),
        source=source.strip(),
        metrics=metrics,
        dimensions=dimensions,
    )


@lru_cache(maxsize=1)
def get_model() -> SemanticModel:
    """Return the process-wide semantic model (parsed once)."""
    return load_model()
