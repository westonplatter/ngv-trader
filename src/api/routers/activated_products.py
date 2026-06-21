"""Activated products API router.

Read-only listing of the products we actively maintain in the security master,
including the count of active contracts present in the ``contracts`` table.
"""

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.models import ActivatedProduct, ContractRef

router = APIRouter()
DB_SESSION_DEPENDENCY = Depends(get_db)


class ActivatedProductResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    symbol: str
    sec_type: str
    currency: str
    months_ahead: int
    exchange: str | None
    valid_exchanges: str | None
    multiplier: str | None
    trading_class: str | None
    long_name: str | None
    min_tick: float | None
    discovery_status: str
    last_error: str | None
    is_active: bool
    last_synced_at: datetime | None
    security_master_count: int
    created_at: datetime
    updated_at: datetime


@router.get("/activated-products", response_model=list[ActivatedProductResponse])
def list_activated_products(db: Session = DB_SESSION_DEPENDENCY) -> list[ActivatedProductResponse]:
    products = db.execute(select(ActivatedProduct).order_by(ActivatedProduct.symbol.asc())).scalars().all()

    # Count active security-master contracts per (symbol, sec_type).
    count_rows = db.execute(
        select(ContractRef.symbol, ContractRef.sec_type, func.count(ContractRef.id))
        .where(ContractRef.is_active.is_(True))
        .group_by(ContractRef.symbol, ContractRef.sec_type)
    ).all()
    counts: dict[tuple[str, str], int] = {(symbol, sec_type): count for symbol, sec_type, count in count_rows}

    responses: list[ActivatedProductResponse] = []
    for product in products:
        responses.append(
            ActivatedProductResponse(
                id=product.id,
                symbol=product.symbol,
                sec_type=product.sec_type,
                currency=product.currency,
                months_ahead=product.months_ahead,
                exchange=product.exchange,
                valid_exchanges=product.valid_exchanges,
                multiplier=product.multiplier,
                trading_class=product.trading_class,
                long_name=product.long_name,
                min_tick=product.min_tick,
                discovery_status=product.discovery_status,
                last_error=product.last_error,
                is_active=product.is_active,
                last_synced_at=product.last_synced_at,
                security_master_count=counts.get((product.symbol, product.sec_type), 0),
                created_at=product.created_at,
                updated_at=product.updated_at,
            )
        )
    return responses
