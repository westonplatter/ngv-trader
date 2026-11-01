"""Request and response models shared by more than one router.

A router owns the models only it uses; anything two routers return or accept
lives here, so routers never import from one another.
"""

import re
from datetime import datetime

from pydantic import BaseModel

from src.models import Account, ContractRef, Job, Order
from src.services.item_refs import ItemRef
from src.utils.contract_display import contract_display_name


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


class JobResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    job_type: str
    status: str
    payload: dict
    result: dict | None
    source: str
    request_text: str | None
    attempts: int
    max_attempts: int
    available_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    archived_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


def to_job_response(job: Job) -> JobResponse:
    return JobResponse(
        id=job.id,
        job_type=job.job_type,
        status=job.status,
        payload=job.payload,
        result=job.result,
        source=job.source,
        request_text=job.request_text,
        attempts=job.attempts,
        max_attempts=job.max_attempts,
        available_at=job.available_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        archived_at=job.archived_at,
        last_error=job.last_error,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


class OrderResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    account_id: int
    account_alias: str | None
    symbol: str
    sec_type: str
    exchange: str
    currency: str
    side: str
    quantity: int
    order_type: str
    limit_price: float | None
    tif: str
    status: str
    source: str
    con_id: int | None
    local_symbol: str | None
    trading_class: str | None
    contract_month: str | None
    contract_expiry: str | None
    option_right: str | None
    option_strike: str | None
    contract_display_name: str
    ib_order_id: int | None
    ib_perm_id: int | None
    filled_quantity: float
    avg_fill_price: float | None
    last_error: str | None
    request_text: str | None
    submitted_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


# (pattern, right group, strike group) tried in order against a local symbol, e.g.
# "WA4G6 C0707" or "CL   MAY 26 70.5 C".
_OPTION_LOCAL_SYMBOL_PATTERNS: tuple[tuple[re.Pattern[str], int, int], ...] = (
    (re.compile(r"\b([CP])([0-9]{3,6})\b"), 1, 2),
    (re.compile(r"\b([CP])\s*([0-9]+(?:\.[0-9]+)?)\b"), 1, 2),
    (re.compile(r"\b([0-9]+(?:\.[0-9]+)?)\s*([CP])\b"), 2, 1),
)


def _derive_option_fields(order: Order) -> tuple[str | None, str | None]:
    if order.sec_type not in {"FOP", "OPT", "BAG"}:
        return None, None
    local_symbol = (order.local_symbol or "").strip().upper()
    if not local_symbol:
        return None, None

    for pattern, right_group, strike_group in _OPTION_LOCAL_SYMBOL_PATTERNS:
        match = pattern.search(local_symbol)
        if match:
            return match.group(right_group), match.group(strike_group)

    return None, None


def to_order_response(
    order: Order,
    account: Account | None,
    contract_ref: ContractRef | None = None,
) -> OrderResponse:
    alias = account.alias if account and account.alias else None
    effective_symbol = contract_ref.symbol if contract_ref and contract_ref.symbol else order.symbol
    effective_sec_type = contract_ref.sec_type if contract_ref and contract_ref.sec_type else order.sec_type
    effective_exchange = contract_ref.exchange if contract_ref and contract_ref.exchange else order.exchange
    effective_local_symbol = contract_ref.local_symbol if contract_ref and contract_ref.local_symbol else order.local_symbol
    effective_trading_class = contract_ref.trading_class if contract_ref and contract_ref.trading_class else order.trading_class
    effective_contract_month = contract_ref.contract_month if contract_ref and contract_ref.contract_month else order.contract_month
    effective_contract_expiry = contract_ref.contract_expiry if contract_ref and contract_ref.contract_expiry else order.contract_expiry
    effective_right = contract_ref.right if contract_ref and contract_ref.right else None
    effective_strike = contract_ref.strike if contract_ref and contract_ref.strike is not None else None

    option_right, option_strike = _derive_option_fields(order)
    if effective_right is not None:
        option_right = effective_right
    if effective_strike is not None:
        option_strike = f"{effective_strike:g}"

    return OrderResponse(
        id=order.id,
        account_id=order.account_id,
        account_alias=alias,
        symbol=effective_symbol,
        sec_type=effective_sec_type,
        exchange=effective_exchange,
        currency=order.currency,
        side=order.side,
        quantity=order.quantity,
        order_type=order.order_type,
        limit_price=order.limit_price,
        tif=order.tif,
        status=order.status,
        source=order.source,
        con_id=order.con_id,
        local_symbol=effective_local_symbol,
        trading_class=effective_trading_class,
        contract_month=effective_contract_month,
        contract_expiry=effective_contract_expiry,
        option_right=option_right,
        option_strike=option_strike,
        contract_display_name=contract_display_name(
            symbol=effective_symbol,
            sec_type=effective_sec_type,
            local_symbol=effective_local_symbol,
            right=option_right,
            strike=(float(option_strike) if option_strike is not None else None),
            contract_expiry=effective_contract_expiry,
            contract_month=effective_contract_month,
            exchange=effective_exchange,
            trading_class=effective_trading_class,
        ),
        ib_order_id=order.ib_order_id,
        ib_perm_id=order.ib_perm_id,
        filled_quantity=order.filled_quantity,
        avg_fill_price=order.avg_fill_price,
        last_error=order.last_error,
        request_text=order.request_text,
        submitted_at=order.submitted_at,
        completed_at=order.completed_at,
        created_at=order.created_at,
        updated_at=order.updated_at,
    )
