"""SQLAlchemy models for ngtrader."""

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
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
    __table_args__ = (
        UniqueConstraint("account_id", "con_id", name="uq_account_id_con_id"),
    )

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
    limit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
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
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
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


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(Integer, nullable=False)
    ib_perm_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    order_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    ib_order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    symbol: Mapped[str | None] = mapped_column(String, nullable=True)
    sec_type: Mapped[str | None] = mapped_column(String, nullable=True)
    side: Mapped[str | None] = mapped_column(String, nullable=True)
    exchange: Mapped[str | None] = mapped_column(String, nullable=True)
    currency: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="unknown")
    total_quantity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    avg_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    first_executed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_executed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
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


class TradeExecution(Base):
    __tablename__ = "trade_executions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("trades.id"), nullable=False
    )
    account_id: Mapped[int] = mapped_column(Integer, nullable=False)
    ib_exec_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    exec_id_base: Mapped[str] = mapped_column(Text, nullable=False)
    exec_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    ib_perm_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ib_order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    order_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    sec_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    con_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exec_role: Mapped[str] = mapped_column(Text, nullable=False, default="standalone")
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    side: Mapped[str | None] = mapped_column(Text, nullable=True)
    exchange: Mapped[str | None] = mapped_column(Text, nullable=True)
    currency: Mapped[str | None] = mapped_column(Text, nullable=True)
    liquidity: Mapped[str | None] = mapped_column(Text, nullable=True)
    commission: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_canonical: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    raw: Mapped[dict] = mapped_column(JSON, nullable=False)
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


class TradeGroup(Base):
    __tablename__ = "trade_groups"
    __table_args__ = (
        Index("ix_trade_groups_account_created_at", "account_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("accounts.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="open")
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    opened_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    closed_by: Mapped[str | None] = mapped_column(Text, nullable=True)
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


class TradeGroupExecution(Base):
    __tablename__ = "trade_group_executions"
    __table_args__ = (
        UniqueConstraint(
            "trade_execution_id", name="uq_trade_group_executions_trade_execution_id"
        ),
        Index(
            "ix_trade_group_executions_group_assigned_at",
            "trade_group_id",
            "assigned_at",
        ),
    )

    trade_group_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("trade_groups.id"), primary_key=True
    )
    trade_execution_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("trade_executions.id"), nullable=False
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class TradeGroupExecutionEvent(Base):
    __tablename__ = "trade_group_execution_events"
    __table_args__ = (
        Index(
            "ix_trade_group_execution_events_execution_event_at",
            "trade_execution_id",
            "event_at",
        ),
        Index(
            "ix_trade_group_execution_events_to_group_event_at",
            "to_trade_group_id",
            "event_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_execution_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("trade_executions.id"), nullable=False
    )
    from_trade_group_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("trade_groups.id"), nullable=True
    )
    to_trade_group_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("trade_groups.id"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (
        UniqueConstraint(
            "tag_type", "normalized_value", name="uq_tags_type_normalized_value"
        ),
        Index("ix_tags_type_normalized_value", "tag_type", "normalized_value"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tag_type: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_value: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class TagLink(Base):
    __tablename__ = "tag_links"
    __table_args__ = (
        UniqueConstraint(
            "entity_type", "entity_id", "tag_id", name="uq_tag_links_entity_tag"
        ),
        Index("ix_tag_links_entity", "entity_type", "entity_id"),
        Index("ix_tag_links_tag_entity", "tag_id", "entity_type"),
        Index(
            "uq_tag_links_primary_strategy_trade_group",
            "entity_id",
            unique=True,
            postgresql_where=text(
                "entity_type = 'trade_groups' AND tag_type = 'strategy' AND is_primary = true"
            ),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    tag_id: Mapped[int] = mapped_column(Integer, ForeignKey("tags.id"), nullable=False)
    tag_type: Mapped[str] = mapped_column(Text, nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class TradeGroupLink(Base):
    __tablename__ = "trade_group_links"
    __table_args__ = (
        UniqueConstraint(
            "parent_trade_group_id",
            "child_trade_group_id",
            "link_type",
            name="uq_trade_group_links_parent_child_type",
        ),
        Index("ix_trade_group_links_parent", "parent_trade_group_id"),
        Index("ix_trade_group_links_child", "child_trade_group_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parent_trade_group_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("trade_groups.id"), nullable=False
    )
    child_trade_group_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("trade_groups.id"), nullable=False
    )
    link_type: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class UserPreference(Base):
    __tablename__ = "user_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    value: Mapped[dict] = mapped_column(JSON, nullable=False)
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


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"
    __table_args__ = (
        UniqueConstraint("worker_type", name="uq_worker_heartbeats_worker_type"),
    )

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
