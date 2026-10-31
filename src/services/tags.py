"""The tag catalog as a service: who may write, and how names resolve to rows.

Shared by the tags and tasks routers (docs/design/tags-and-tasks.md). Attaching
and detaching tags to items lives in ``src/services/item_links.py``.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models import Tag
from src.services.errors import NotFoundError, ServiceError
from src.services.item_links import now_utc

# `user`, or `agent:<name>` for writes made by an LLM agent.
CREATED_BY_PATTERN = re.compile(r"^(user|agent:[A-Za-z0-9_.\-]+)$")


def normalize_tag_value(value: str) -> str:
    """Fold case, spaces, ``-`` and ``_``: "Long Beta", "long_beta", "long-beta" match."""
    return re.sub(r"[\s_\-]+", "-", value.strip().lower()).strip("-")


class TagError(ServiceError):
    """A tag request the catalog cannot satisfy."""


class TagNotFound(TagError, NotFoundError):
    """A tag id or name that does not exist."""


def validate_created_by(created_by: str) -> str:
    if not CREATED_BY_PATTERN.match(created_by):
        raise TagError("created_by must be 'user' or 'agent:<name>'")
    return created_by


def require_tag(db: Session, tag_id: int) -> Tag:
    tag = db.get(Tag, tag_id)
    if tag is None:
        raise TagNotFound("Tag not found")
    return tag


def find_tag(db: Session, value: str) -> Tag | None:
    """The tag whose name matches ``value`` after normalization, if any."""
    return db.execute(select(Tag).where(Tag.normalized_value == normalize_tag_value(value))).scalar_one_or_none()


def get_or_create_tag(db: Session, value: str, created_by: str, color: str | None = None) -> Tag:
    """The tag with this normalized value, created if missing. Unarchives nothing."""
    normalized = normalize_tag_value(value)
    if not normalized:
        raise TagError("value cannot be empty")
    existing = find_tag(db, value)
    if existing is not None:
        return existing
    tag = Tag(value=value.strip(), normalized_value=normalized, color=color, created_by=created_by, created_at=now_utc())
    db.add(tag)
    db.flush()
    return tag


def resolve_tags(db: Session, handles: list[int | str], created_by: str, create: bool) -> list[Tag]:
    """Tags by id or by name, deduplicated. Unknown names are created when ``create``."""
    tags: dict[int, Tag] = {}
    for handle in handles:
        if isinstance(handle, int):
            tag = require_tag(db, handle)
        elif create:
            tag = get_or_create_tag(db, handle, created_by)
        else:
            found = find_tag(db, handle)
            if found is None:
                raise TagNotFound(f"Tag {handle!r} not found")
            tag = found
        tags[tag.id] = tag
    return list(tags.values())
