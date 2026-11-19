"""One memory, several embedding models (dossier docs/work/2026-11-18-real-test-problems, E2).

The embedding chain can have fallback models: each stored vector records the model that made it
(``embedding_model``), and a search sends the query embedded by every model it can reach (``query_vectors``:
``[{model, vector}]``). Each row is compared with the query vector of its own model, inside Postgres, in one
``CASE`` expression; rows of a model the query was not embedded with get no distance (left out). Rows stored before
models were recorded (``embedding_model`` empty) are compared with the vector of ``untagged_model`` (the chain's first
model). A caller that sends only ``query_vector`` gets the old behaviour (every row, one vector).
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from sqlalchemy import case

logger = logging.getLogger("hestia_archive")


def fits(vec: Any, column) -> bool:
    dims = getattr(column.type, "dim", None)
    return isinstance(vec, list) and bool(vec) and (not dims or len(vec) == dims) and any(vec)


def pairs(query_vectors: Any, column) -> list[tuple[str, list[float]]]:
    """``[{model, vector}]`` → ``[(model, vector)]`` keeping only vectors of the column's size."""
    out: list[tuple[str, list[float]]] = []
    for item in query_vectors or []:
        if not isinstance(item, dict):
            continue
        model = str(item.get("model") or "")
        try:
            vec = [float(x) for x in item.get("vector") or []]
        except (TypeError, ValueError):
            continue
        if model and fits(vec, column):
            out.append((model, vec))
        elif model:
            logger.warning("[🔄] event=search_vector_dim_mismatch model=%s got=%d (that model skipped)", model, len(vec))
    return out


def distance(column, model_column, *, query_vectors: Any = None, untagged_model: str = "",
             query_vector: Any = None, measure: str = "l2"):
    """SQL distance of each row against the query vector made by the row's own model (None = no vector usable)."""
    dist: Callable = (lambda v: column.l2_distance(v)) if measure == "l2" else (lambda v: column.cosine_distance(v))
    tagged = pairs(query_vectors, column)
    if tagged:
        whens = [(model_column == m, dist(v)) for m, v in tagged]
        first = dict(tagged).get(untagged_model) if untagged_model else None
        if first is not None:
            whens.append((model_column.is_(None), dist(first)))
        return case(*whens)   # no ELSE: a row of another model gets NULL (left out)
    if query_vector is not None and fits(list(query_vector), column):
        return dist([float(x) for x in query_vector])
    return None


def tag(vec: Any, model: str | None) -> str | None:
    """The model to store with a vector (none without a vector)."""
    return (str(model)[:120] or None) if vec and model else None
