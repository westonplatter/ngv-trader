"""Watch Lists API router."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.models import WatchList, WatchListInstrument
from src.services.jobs import JOB_TYPE_WATCHLIST_QUOTES_REFRESH, enqueue_job_if_idle
from src.services.watchlist_quotes import list_watch_list_quotes
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
    symbol: str = Field(..., min_length=1)
    sec_type: str = Field(..., min_length=1)
    exchange: str = Field(..., min_length=1)
    currency: str = "USD"
    local_symbol: str | None = None
    trading_class: str | None = None
    contract_month: str | None = None
    contract_expiry: str | None = None
    multiplier: str | None = None
    strike: float | None = None
    right: str | None = None
    primary_exchange: str | None = None


class InstrumentResponse(BaseModel):
    model_config = {"from_attributes": True}

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
    close_price: float | None
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


class WatchListInstrumentQuoteResponse(BaseModel):
    instrument_id: int
    con_id: int
    bid: float | None
    ask: float | None
    close: float | None
    as_of: datetime | None


class WatchListQuotesRefreshResponse(BaseModel):
    queued: bool
    job_id: int | None
    message: str


def to_instrument_response(inst: WatchListInstrument) -> InstrumentResponse:
    return InstrumentResponse(
        id=inst.id,
        watch_list_id=inst.watch_list_id,
        con_id=inst.con_id,
        symbol=inst.symbol,
        sec_type=inst.sec_type,
        exchange=inst.exchange,
        currency=inst.currency,
        local_symbol=inst.local_symbol,
        trading_class=inst.trading_class,
        contract_month=inst.contract_month,
        contract_expiry=inst.contract_expiry,
        multiplier=inst.multiplier,
        strike=inst.strike,
        right=inst.right,
        primary_exchange=inst.primary_exchange,
        bid_price=inst.bid_price,
        ask_price=inst.ask_price,
        close_price=inst.close_price,
        quote_as_of=inst.quote_as_of,
        contract_display_name=contract_display_name(
            symbol=inst.symbol,
            sec_type=inst.sec_type,
            right=inst.right,
            strike=inst.strike,
            contract_expiry=inst.contract_expiry,
            contract_month=inst.contract_month,
            exchange=inst.exchange,
            trading_class=inst.trading_class,
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
    instruments = (
        db.execute(select(WatchListInstrument).where(WatchListInstrument.watch_list_id == watch_list_id).order_by(WatchListInstrument.created_at))
        .scalars()
        .all()
    )
    return WatchListDetailResponse(
        id=wl.id,
        name=wl.name,
        description=wl.description,
        instruments=[to_instrument_response(inst) for inst in instruments],
        created_at=wl.created_at,
        updated_at=wl.updated_at,
    )


@router.get(
    "/watch-lists/{watch_list_id}/quotes",
    response_model=list[WatchListInstrumentQuoteResponse],
)
def get_watch_list_quotes(watch_list_id: int, db: Session = DB_SESSION_DEPENDENCY) -> list[WatchListInstrumentQuoteResponse]:
    wl = db.get(WatchList, watch_list_id)
    if wl is None:
        raise HTTPException(status_code=404, detail="Watch list not found")

    rows = list_watch_list_quotes(db, watch_list_id)

    return [
        WatchListInstrumentQuoteResponse(
            instrument_id=row.instrument_id,
            con_id=row.con_id,
            bid=row.bid,
            ask=row.ask,
            close=row.close,
            as_of=row.as_of,
        )
        for row in rows
    ]


@router.post(
    "/watch-lists/{watch_list_id}/quotes/refresh",
    response_model=WatchListQuotesRefreshResponse,
)
def enqueue_watch_list_quotes_refresh(watch_list_id: int, db: Session = DB_SESSION_DEPENDENCY) -> WatchListQuotesRefreshResponse:
    wl = db.get(WatchList, watch_list_id)
    if wl is None:
        raise HTTPException(status_code=404, detail="Watch list not found")

    job = enqueue_job_if_idle(
        session=db,
        job_type=JOB_TYPE_WATCHLIST_QUOTES_REFRESH,
        payload={"watch_list_id": watch_list_id},
        source="watchlists-api",
        request_text=f"refresh quotes for watch list #{watch_list_id}",
        max_attempts=1,
    )
    db.commit()

    if job is None:
        return WatchListQuotesRefreshResponse(
            queued=False,
            job_id=None,
            message="A quote refresh job is already queued or running.",
        )

    return WatchListQuotesRefreshResponse(
        queued=True,
        job_id=job.id,
        message=f"Enqueued quote refresh job #{job.id}.",
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

    # Check for duplicate
    existing = db.execute(
        select(WatchListInstrument).where(
            WatchListInstrument.watch_list_id == watch_list_id,
            WatchListInstrument.con_id == body.con_id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return to_instrument_response(existing)

    inst = WatchListInstrument(
        watch_list_id=watch_list_id,
        con_id=body.con_id,
        symbol=body.symbol.upper(),
        sec_type=body.sec_type.upper(),
        exchange=body.exchange.upper(),
        currency=body.currency.upper(),
        local_symbol=body.local_symbol,
        trading_class=body.trading_class,
        contract_month=body.contract_month,
        contract_expiry=body.contract_expiry,
        multiplier=body.multiplier,
        strike=body.strike,
        right=body.right,
        primary_exchange=body.primary_exchange,
    )
    db.add(inst)
    db.commit()
    db.refresh(inst)
    return to_instrument_response(inst)


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
