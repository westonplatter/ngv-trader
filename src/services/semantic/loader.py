"""Load and validate the OSI semantic model into an in-memory registry.

Parses ``osi/ngv_semantic_model.yaml`` into a :class:`SemanticModel`: a set of
datasets (each a physical table/view with dimensions), a directed relationship
graph for joins, and metrics that each name the fact dataset they live on. The
model is the allow-list — only names defined here can be referenced — and it
provides the graph helpers the resolver uses to route a query to a metric's fact
and join in only the dimensions reachable from it.

See docs/core/semantic-queries.md for the design and authoring guide.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[3] / "osi" / "ngv_semantic_model.yaml"
_DIALECT = "ANSI_SQL"


@dataclass(frozen=True)
class Dimension:
    name: str
    dataset: str
    expression: str
    is_time: bool
    description: str | None
    synonyms: tuple[str, ...]


@dataclass(frozen=True)
class Metric:
    name: str
    fact: str  # dataset name this metric aggregates over
    expression: str
    description: str | None
    synonyms: tuple[str, ...]


@dataclass(frozen=True)
class Relationship:
    name: str
    from_dataset: str
    from_columns: tuple[str, ...]
    to_dataset: str
    to_columns: tuple[str, ...]


@dataclass(frozen=True)
class Dataset:
    name: str
    source: str
    primary_key: tuple[str, ...]
    description: str | None
    dimensions: dict[str, Dimension] = field(default_factory=dict)


@dataclass(frozen=True)
class SemanticModel:
    version: str
    datasets: dict[str, Dataset]
    relationships: tuple[Relationship, ...]
    metrics: dict[str, Metric]

    # -- graph helpers (the resolver's interface) ---------------------------

    def _adjacency(self) -> dict[str, list[Relationship]]:
        adj: dict[str, list[Relationship]] = {name: [] for name in self.datasets}
        for rel in self.relationships:
            adj.setdefault(rel.from_dataset, []).append(rel)
        return adj

    def reachable(self, fact: str) -> list[str]:
        """Dataset names reachable from ``fact`` via directed relationships, BFS order (fact first)."""
        adj = self._adjacency()
        seen = [fact]
        queue = deque([fact])
        while queue:
            cur = queue.popleft()
            for rel in adj.get(cur, []):
                if rel.to_dataset not in seen:
                    seen.append(rel.to_dataset)
                    queue.append(rel.to_dataset)
        return seen

    def join_path(self, fact: str, target: str) -> list[Relationship] | None:
        """Shortest directed relationship path ``fact`` → ``target`` (empty if same), or None."""
        if fact == target:
            return []
        adj = self._adjacency()
        prev: dict[str, Relationship] = {}
        seen = {fact}
        queue = deque([fact])
        while queue:
            cur = queue.popleft()
            for rel in adj.get(cur, []):
                if rel.to_dataset in seen:
                    continue
                seen.add(rel.to_dataset)
                prev[rel.to_dataset] = rel
                if rel.to_dataset == target:
                    path: list[Relationship] = []
                    node = target
                    while node != fact:
                        rel_used = prev[node]
                        path.append(rel_used)
                        node = rel_used.from_dataset
                    return list(reversed(path))
                queue.append(rel.to_dataset)
        return None

    def resolve_dimension(self, fact: str, name: str) -> Dimension:
        """Find dimension ``name`` on the nearest dataset reachable from ``fact`` (fact first)."""
        for ds_name in self.reachable(fact):
            dim = self.datasets[ds_name].dimensions.get(name)
            if dim is not None:
                return dim
        available = sorted({d for ds in self.reachable(fact) for d in self.datasets[ds].dimensions})
        raise ValueError(f"Dimension '{name}' is not available for this metric. Available here: {', '.join(available) or '(none)'}.")

    def time_dimension(self, fact: str) -> Dimension | None:
        for ds_name in self.reachable(fact):
            for dim in self.datasets[ds_name].dimensions.values():
                if dim.is_time:
                    return dim
        return None

    def all_dimension_names(self) -> list[str]:
        return sorted({name for ds in self.datasets.values() for name in ds.dimensions})

    def filterable_dimension_names(self) -> list[str]:
        return sorted({name for ds in self.datasets.values() for name, dim in ds.dimensions.items() if not dim.is_time})


def _dialect_expression(node: dict[str, Any], *, context: str) -> str:
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


def _parse_dataset(raw: dict[str, Any]) -> Dataset:
    name = raw.get("name")
    source = raw.get("source")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("dataset 'name' is required")
    if not isinstance(source, str) or not source.strip():
        raise ValueError(f"dataset '{name}': 'source' is required")
    primary_key = tuple(str(c) for c in (raw.get("primary_key") or []))

    dimensions: dict[str, Dimension] = {}
    for fld in raw.get("fields", []) or []:
        if not isinstance(fld, dict):
            continue
        dim_block = fld.get("dimension")
        if not isinstance(dim_block, dict):
            continue  # plain fact field, not a dimension
        dim_name = fld.get("name")
        if not isinstance(dim_name, str) or not dim_name.strip():
            raise ValueError(f"dataset '{name}': dimension field missing 'name'")
        dimensions[dim_name] = Dimension(
            name=dim_name,
            dataset=name,
            expression=_dialect_expression(fld, context=f"dataset '{name}' dimension '{dim_name}'"),
            is_time=bool(dim_block.get("is_time", False)),
            description=fld.get("description"),
            synonyms=_synonyms(fld),
        )
    return Dataset(name=name.strip(), source=source.strip(), primary_key=primary_key, description=raw.get("description"), dimensions=dimensions)


def _parse_relationship(raw: dict[str, Any]) -> Relationship:
    name = raw.get("name")
    src = raw.get("from")
    dst = raw.get("to")
    if not isinstance(name, str) or not isinstance(src, dict) or not isinstance(dst, dict):
        raise ValueError("relationship requires 'name', 'from', and 'to'")
    from_cols = tuple(str(c) for c in (src.get("columns") or []))
    to_cols = tuple(str(c) for c in (dst.get("columns") or []))
    if not from_cols or len(from_cols) != len(to_cols):
        raise ValueError(f"relationship '{name}': from/to columns must be non-empty and equal length")
    return Relationship(
        name=name,
        from_dataset=str(src.get("dataset")),
        from_columns=from_cols,
        to_dataset=str(dst.get("dataset")),
        to_columns=to_cols,
    )


def load_model(path: Path | str | None = None) -> SemanticModel:  # noqa: C901, PLR0912 — linear parse-and-validate
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

    raw_datasets = entry.get("datasets")
    if not isinstance(raw_datasets, list) or not raw_datasets:
        raise ValueError("semantic model: 'datasets' must be a non-empty list")
    datasets: dict[str, Dataset] = {}
    for raw in raw_datasets:
        if not isinstance(raw, dict):
            raise ValueError("semantic model: each dataset must be a mapping")
        ds = _parse_dataset(raw)
        datasets[ds.name] = ds

    relationships: list[Relationship] = []
    for raw in entry.get("relationships", []) or []:
        if not isinstance(raw, dict):
            continue
        rel = _parse_relationship(raw)
        for ds_name in (rel.from_dataset, rel.to_dataset):
            if ds_name not in datasets:
                raise ValueError(f"relationship '{rel.name}': unknown dataset '{ds_name}'")
        relationships.append(rel)

    metrics: dict[str, Metric] = {}
    for raw in entry.get("metrics", []) or []:
        if not isinstance(raw, dict):
            continue
        name = raw.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("semantic model: metric missing 'name'")
        fact = raw.get("fact")
        if not isinstance(fact, str) or fact not in datasets:
            raise ValueError(f"metric '{name}': 'fact' must name a defined dataset")
        metrics[name] = Metric(
            name=name,
            fact=fact,
            expression=_dialect_expression(raw, context=f"metric '{name}'"),
            description=raw.get("description"),
            synonyms=_synonyms(raw),
        )

    if not metrics:
        raise ValueError("semantic model: at least one metric is required")

    return SemanticModel(
        version=version,
        datasets=datasets,
        relationships=tuple(relationships),
        metrics=metrics,
    )


@lru_cache(maxsize=1)
def get_model() -> SemanticModel:
    """Return the process-wide semantic model (parsed once)."""
    return load_model()
