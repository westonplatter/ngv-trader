"""Fill the ``tags`` and ``open_task_count`` fields on read-endpoint rows."""

from collections.abc import Callable, Sequence
from typing import Any, Protocol

from sqlalchemy.orm import Session

from src.api.schemas import TagChip
from src.services.item_descriptions import open_task_counts, tags_by_item


class Annotatable(Protocol):
    tags: list[TagChip]
    open_task_count: int


def annotate_items(db: Session, entity_type: str, rows: Sequence[Annotatable], key: Callable[[Any], Any]) -> None:
    """Set each row's open tags and not-done task count, looked up by ``key(row)``.

    ``key`` returns what ``tags_by_item`` expects for the entity type: an id, an
    ``ib_exec_id``, or ``(account_id, con_id)``. Two batched queries per call.
    """
    keys = [key(row) for row in rows]
    tags, counts = tags_by_item(db, entity_type, keys), open_task_counts(db, entity_type, keys)
    for row, row_key in zip(rows, keys, strict=True):
        row.tags = [TagChip.model_validate(chip) for chip in tags.get(row_key, [])]
        row.open_task_count = counts.get(row_key, 0)
