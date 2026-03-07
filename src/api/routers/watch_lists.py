"""Watch Lists API router."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.models import (
    ContractRef,
    LatestFutures,
    LatestFuturesOptions,
    WatchList,
    WatchListInstrument,
)
from src.services.jobs import (
    JOB_TYPE_MARKET_DATA_SNAPSHOT,
    enqueue_job,
)
from src.utils.contract_display import contract_display_name

router = APIRouter()
DB_SESSION_DEPENDENCY = Depends(get_db)


class WatchListCreateRequest(BaseModel):
    name: str = Field(..., min_length=1)
    description: str | None = None


class WatchListUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None


class InstrumentAddRequest(BaseModel):
    con_id: int


class InstrumentResponse(BaseModel):
    id: int
    watch_list_id: int
    con_id: int
    symbol: str
    sec_type: str
    exchange: str
    currency: str
    local_symbol: str | None
    trading_class: str | None
    contract_month: str | None
    contract_expiry: str | None
    multiplier: str | None
    strike: float | None
    right: str | None
    primary_exchange: str | None
    bid_price: float | None
    ask_price: float | None
    last_price: float | None
    close_price: float | None
    iv: float | None
    delta: float | None
    gamma: float | None
    theta: float | None
    vega: float | None
    und_price: float | None
    quote_as_of: datetime | None
    contract_display_name: str
    created_at: datetime


class WatchListReorderRequest(BaseModel):
    ids: list[int] = Field(..., min_length=1)


class WatchListResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    name: str
    description: str | None
    position: int
    instrument_count: int
    created_at: datetime
    updated_at: datetime


class WatchListDetailResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    name: str
    description: str | None
    instruments: list[InstrumentResponse]
    created_at: datetime
    updated_at: datetime


class WatchListQuotesRefreshResponse(BaseModel):
    queued: bool
    job_id: int | None
    message: str


def to_instrument_response(
    inst: WatchListInstrument,
    contract: ContractRef,
    market_data: LatestFuturesOptions | LatestFutures | None = None,
) -> InstrumentResponse:
    bid = market_data.bid if market_data else None
    ask = market_data.ask if market_data else None
    last = getattr(market_data, "last", None) if market_data else None
    close = market_data.close if market_data else None
    quote_as_of = market_data.market_ts if market_data else None

    # Greeks and option-specific fields (only on LatestFuturesOptions)
    iv = getattr(market_data, "iv", None) if market_data else None
    delta = getattr(market_data, "delta", None) if market_data else None
    gamma = getattr(market_data, "gamma", None) if market_data else None
    theta = getattr(market_data, "theta", None) if market_data else None
    vega = getattr(market_data, "vega", None) if market_data else None
    und_price = getattr(market_data, "und_price", None) if market_data else None

    return InstrumentResponse(
        id=inst.id,
        watch_list_id=inst.watch_list_id,
        con_id=inst.con_id,
        symbol=contract.symbol,
        sec_type=contract.sec_type,
        exchange=contract.exchange,
        currency=contract.currency,
        local_symbol=contract.local_symbol,
        trading_class=contract.trading_class,
        contract_month=contract.contract_month,
        contract_expiry=contract.contract_expiry,
        multiplier=contract.multiplier,
        strike=contract.strike,
        right=contract.right,
        primary_exchange=contract.primary_exchange,
        bid_price=bid,
        ask_price=ask,
        last_price=last,
        close_price=close,
        iv=iv,
        delta=delta,
        gamma=gamma,
        theta=theta,
        vega=vega,
        und_price=und_price,
        quote_as_of=quote_as_of,
        contract_display_name=contract_display_name(
            symbol=contract.symbol,
            sec_type=contract.sec_type,
            right=contract.right,
            strike=contract.strike,
            contract_expiry=contract.contract_expiry,
            contract_month=contract.contract_month,
            exchange=contract.exchange,
            trading_class=contract.trading_class,
        ),
        created_at=inst.created_at,
    )


@router.get("/watch-lists", response_model=list[WatchListResponse])
def list_watch_lists(db: Session = DB_SESSION_DEPENDENCY) -> list[WatchListResponse]:
    count_subq = select(func.count(WatchListInstrument.id)).where(WatchListInstrument.watch_list_id == WatchList.id).correlate(WatchList).scalar_subquery()
    stmt = select(WatchList, count_subq).order_by(WatchList.position.asc(), WatchList.created_at.desc())
    rows = db.execute(stmt).all()
    return [
        WatchListResponse(
            id=wl.id,
            name=wl.name,
            description=wl.description,
            position=wl.position,
            instrument_count=count,
            created_at=wl.created_at,
            updated_at=wl.updated_at,
        )
        for wl, count in rows
    ]


@router.post("/watch-lists", response_model=WatchListResponse, status_code=201)
def create_watch_list(body: WatchListCreateRequest, db: Session = DB_SESSION_DEPENDENCY) -> WatchListResponse:
    max_pos = db.execute(select(func.coalesce(func.max(WatchList.position), -1))).scalar_one()
    wl = WatchList(name=body.name, description=body.description, position=max_pos + 1)
    db.add(wl)
    db.commit()
    db.refresh(wl)
    return WatchListResponse(
        id=wl.id,
        name=wl.name,
        description=wl.description,
        position=wl.position,
        instrument_count=0,
        created_at=wl.created_at,
        updated_at=wl.updated_at,
    )


@router.get("/watch-lists/{watch_list_id}", response_model=WatchListDetailResponse)
def get_watch_list(watch_list_id: int, db: Session = DB_SESSION_DEPENDENCY) -> WatchListDetailResponse:
    wl = db.get(WatchList, watch_list_id)
    if wl is None:
        raise HTTPException(status_code=404, detail="Watch list not found")

    # Join instruments with contracts
    rows = db.execute(
        select(WatchListInstrument, ContractRef)
        .join(ContractRef, ContractRef.con_id == WatchListInstrument.con_id)
        .where(WatchListInstrument.watch_list_id == watch_list_id)
        .order_by(WatchListInstrument.created_at)
    ).all()

    # Look up latest market data for all instruments by con_id
    con_ids = [inst.con_id for inst, _ in rows]
    market_data_map: dict[int, LatestFuturesOptions | LatestFutures] = {}
    if con_ids:
        fop_rows = db.execute(select(LatestFuturesOptions).where(LatestFuturesOptions.con_id.in_(con_ids))).scalars().all()
        for row in fop_rows:
            market_data_map[row.con_id] = row

        fut_rows = db.execute(select(LatestFutures).where(LatestFutures.con_id.in_(con_ids))).scalars().all()
        for row in fut_rows:
            if row.con_id not in market_data_map:
                market_data_map[row.con_id] = row

    return WatchListDetailResponse(
        id=wl.id,
        name=wl.name,
        description=wl.description,
        instruments=[to_instrument_response(inst, contract, market_data_map.get(inst.con_id)) for inst, contract in rows],
        created_at=wl.created_at,
        updated_at=wl.updated_at,
    )


@router.post(
    "/watch-lists/{watch_list_id}/quotes/refresh",
    response_model=WatchListQuotesRefreshResponse,
)
def enqueue_watch_list_quotes_refresh(watch_list_id: int, db: Session = DB_SESSION_DEPENDENCY) -> WatchListQuotesRefreshResponse:
    wl = db.get(WatchList, watch_list_id)
    if wl is None:
        raise HTTPException(status_code=404, detail="Watch list not found")

    con_ids = [row.con_id for row in db.execute(select(WatchListInstrument.con_id).where(WatchListInstrument.watch_list_id == watch_list_id)).all()]

    if not con_ids:
        return WatchListQuotesRefreshResponse(
            queued=False,
            job_id=None,
            message="No instruments in this watch list.",
        )

    job = enqueue_job(
        session=db,
        job_type=JOB_TYPE_MARKET_DATA_SNAPSHOT,
        payload={"con_ids": con_ids},
        source="watchlists-api",
        request_text=f"refresh quotes for {len(con_ids)} instrument(s) (watch list #{watch_list_id})",
    )
    db.commit()

    return WatchListQuotesRefreshResponse(
        queued=True,
        job_id=job.id,
        message=f"Enqueued snapshot for {len(con_ids)} con_id(s).",
    )


@router.patch("/watch-lists/{watch_list_id}", response_model=WatchListResponse)
def update_watch_list(
    watch_list_id: int,
    body: WatchListUpdateRequest,
    db: Session = DB_SESSION_DEPENDENCY,
) -> WatchListResponse:
    wl = db.get(WatchList, watch_list_id)
    if wl is None:
        raise HTTPException(status_code=404, detail="Watch list not found")
    if body.name is not None:
        wl.name = body.name
    if body.description is not None:
        wl.description = body.description
    from datetime import timezone

    wl.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(wl)
    count = db.execute(select(func.count(WatchListInstrument.id)).where(WatchListInstrument.watch_list_id == watch_list_id)).scalar_one()
    return WatchListResponse(
        id=wl.id,
        name=wl.name,
        description=wl.description,
        position=wl.position,
        instrument_count=count,
        created_at=wl.created_at,
        updated_at=wl.updated_at,
    )


@router.delete("/watch-lists/{watch_list_id}", status_code=204)
def delete_watch_list(watch_list_id: int, db: Session = DB_SESSION_DEPENDENCY) -> None:
    wl = db.get(WatchList, watch_list_id)
    if wl is None:
        raise HTTPException(status_code=404, detail="Watch list not found")
    db.execute(delete(WatchListInstrument).where(WatchListInstrument.watch_list_id == watch_list_id))
    db.delete(wl)
    db.commit()


@router.put("/watch-lists/reorder", status_code=204)
def reorder_watch_lists(body: WatchListReorderRequest, db: Session = DB_SESSION_DEPENDENCY) -> None:
    for position, wl_id in enumerate(body.ids):
        db.execute(update(WatchList).where(WatchList.id == wl_id).values(position=position))
    db.commit()


@router.post(
    "/watch-lists/{watch_list_id}/instruments",
    response_model=InstrumentResponse,
    status_code=201,
)
def add_instrument(
    watch_list_id: int,
    body: InstrumentAddRequest,
    db: Session = DB_SESSION_DEPENDENCY,
) -> InstrumentResponse:
    wl = db.get(WatchList, watch_list_id)
    if wl is None:
        raise HTTPException(status_code=404, detail="Watch list not found")

    # Verify contract exists
    contract = db.get(ContractRef, body.con_id)
    if contract is None:
        raise HTTPException(status_code=404, detail=f"Contract con_id={body.con_id} not found")

    # Check for duplicate
    existing = db.execute(
        select(WatchListInstrument).where(
            WatchListInstrument.watch_list_id == watch_list_id,
            WatchListInstrument.con_id == body.con_id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return to_instrument_response(existing, contract)

    inst = WatchListInstrument(
        watch_list_id=watch_list_id,
        con_id=body.con_id,
    )
    db.add(inst)
    db.commit()
    db.refresh(inst)
    return to_instrument_response(inst, contract)


@router.delete("/watch-lists/{watch_list_id}/instruments/{instrument_id}", status_code=204)
def remove_instrument(watch_list_id: int, instrument_id: int, db: Session = DB_SESSION_DEPENDENCY) -> None:
    inst = db.execute(
        select(WatchListInstrument).where(
            WatchListInstrument.id == instrument_id,
            WatchListInstrument.watch_list_id == watch_list_id,
        )
    ).scalar_one_or_none()
    if inst is None:
        raise HTTPException(status_code=404, detail="Instrument not found")
    db.delete(inst)
    db.commit()
