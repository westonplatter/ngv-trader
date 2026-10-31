"""The strategy catalog as a service: name matching and lookups shared by routers."""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from src.models import Strategy
from src.services.errors import NotFoundError


def normalize_strategy_name(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def require_strategy(db: Session, strategy_id: int) -> Strategy:
    strategy = db.get(Strategy, strategy_id)
    if strategy is None:
        raise NotFoundError("Strategy not found")
    return strategy
