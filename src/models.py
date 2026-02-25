"""SQLAlchemy models for ngtrader."""

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ContractRef(Base):
    __tablename__ = "contracts"
    __table_args__ = (
        Index(
            "ix_contracts_fut_lookup",
            "symbol",
            "sec_type",
            "is_active",
            "contract_expiry",
        ),
        Index(
            "ix_contracts_option_lookup",
            "symbol",
            "sec_type",
            "is_active",
            "strike",
            "right",
            "contract_expiry",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    con_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    sec_type: Mapped[str] = mapped_column(String, nullable=False)
    exchange: Mapped[str] = mapped_column(String, nullable=False)
    currency: Mapped[str] = mapped_column(String, nullable=False)
    local_symbol: Mapped[str | None] = mapped_column(String, nullable=True)
    trading_class: Mapped[str | None] = mapped_column(String, nullable=True)
    contract_month: Mapped[str | None] = mapped_column(String, nullable=True)
    contract_expiry: Mapped[str | None] = mapped_column(String, nullable=True)
    multiplier: Mapped[str | None] = mapped_column(String, nullable=True)
    strike: Mapped[float | None] = mapped_column(Float, nullable=True)
    right: Mapped[str | None] = mapped_column(String, nullable=True)
    primary_exchange: Mapped[str | None] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    alias: Mapped[str | None] = mapped_column(String, nullable=True)


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (UniqueConstraint("account_id", "con_id", name="uq_account_id_con_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(Integer, nullable=False)
    con_id: Mapped[int] = mapped_column(Integer, nullable=False)
    symbol: Mapped[str | None] = mapped_column(String)
    sec_type: Mapped[str | None] = mapped_column(String)
    exchange: Mapped[str | None] = mapped_column(String)
    primary_exchange: Mapped[str | None] = mapped_column(String)
    currency: Mapped[str | None] = mapped_column(String)
    local_symbol: Mapped[str | None] = mapped_column(String)
    trading_class: Mapped[str | None] = mapped_column(String)
    last_trade_date: Mapped[str | None] = mapped_column(String)
    strike: Mapped[float | None] = mapped_column(Float)
    right: Mapped[str | None] = mapped_column(String)
    multiplier: Mapped[str | None] = mapped_column(String)
    position: Mapped[float] = mapped_column(Float, nullable=False)
    avg_cost: Mapped[float] = mapped_column(Float, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(Integer, nullable=False)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    sec_type: Mapped[str] = mapped_column(String, nullable=False, default="FUT")
    exchange: Mapped[str] = mapped_column(String, nullable=False, default="NYMEX")
    currency: Mapped[str] = mapped_column(String, nullable=False, default="USD")
    side: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    order_type: Mapped[str] = mapped_column(String, nullable=False, default="MKT")
    tif: Mapped[str] = mapped_column(String, nullable=False, default="DAY")
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued")
    source: Mapped[str] = mapped_column(String, nullable=False, default="tradebot")
    con_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    local_symbol: Mapped[str | None] = mapped_column(String, nullable=True)
    trading_class: Mapped[str | None] = mapped_column(String, nullable=True)
    contract_month: Mapped[str | None] = mapped_column(String, nullable=True)
    contract_expiry: Mapped[str | None] = mapped_column(String, nullable=True)
    ib_order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ib_perm_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    filled_quantity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    avg_fill_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class OrderEvent(Base):
    __tablename__ = "order_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str | None] = mapped_column(String, nullable=True)
    filled_quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_fill_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    ib_order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_type: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued")
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source: Mapped[str] = mapped_column(String, nullable=False, default="tradebot")
    request_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class WatchList(Base):
    __tablename__ = "watch_lists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class WatchListInstrument(Base):
    __tablename__ = "watch_list_instruments"
    __table_args__ = (
        UniqueConstraint("watch_list_id", "con_id", name="uq_watch_list_id_con_id"),
        Index(
            "ix_watch_list_instruments_lookup",
            "watch_list_id",
            "symbol",
            "sec_type",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    watch_list_id: Mapped[int] = mapped_column(Integer, nullable=False)
    con_id: Mapped[int] = mapped_column(Integer, nullable=False)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    sec_type: Mapped[str] = mapped_column(String, nullable=False)
    exchange: Mapped[str] = mapped_column(String, nullable=False)
    currency: Mapped[str] = mapped_column(String, nullable=False, default="USD")
    local_symbol: Mapped[str | None] = mapped_column(String, nullable=True)
    trading_class: Mapped[str | None] = mapped_column(String, nullable=True)
    contract_month: Mapped[str | None] = mapped_column(String, nullable=True)
    contract_expiry: Mapped[str | None] = mapped_column(String, nullable=True)
    multiplier: Mapped[str | None] = mapped_column(String, nullable=True)
    strike: Mapped[float | None] = mapped_column(Float, nullable=True)
    right: Mapped[str | None] = mapped_column(String, nullable=True)
    primary_exchange: Mapped[str | None] = mapped_column(String, nullable=True)
    bid_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    ask_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    close_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    quote_as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"
    __table_args__ = (UniqueConstraint("worker_type", name="uq_worker_heartbeats_worker_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    worker_type: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="running")
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
