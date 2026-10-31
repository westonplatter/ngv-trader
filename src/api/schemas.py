"""Request and response models shared by more than one router.

A router owns the models only it uses; anything two routers return or accept
lives here, so routers never import from one another.
"""

from datetime import datetime

from pydantic import BaseModel

from src.services.item_links import ItemRef


class TagChip(BaseModel):
    """A tag as shown on an item, with who applied it there."""

    id: int
    value: str
    color: str | None
    created_by: str
    assigned_at: datetime
    ended_at: datetime | None = None


class ItemRefBody(BaseModel):
    """One item. ``id`` for trades, trade groups, tasks, and strategies; ``account_id`` +
    ``con_id`` for a position; ``ib_exec_id`` for a live (unsettled) fill."""

    entity_type: str
    id: int | None = None
    account_id: int | None = None
    con_id: int | None = None
    ib_exec_id: str | None = None

    def ref(self) -> ItemRef:
        return ItemRef(self.entity_type, id=self.id, account_id=self.account_id, con_id=self.con_id, ib_exec_id=self.ib_exec_id)
