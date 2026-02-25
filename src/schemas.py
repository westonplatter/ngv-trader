"""Pandera schemas for data validation."""

import pandera.pandas as pa

positions_schema = pa.DataFrameSchema(
    columns={
        "account": pa.Column(str, nullable=False),
        "con_id": pa.Column(int, nullable=False),
        "symbol": pa.Column(str, nullable=True),
        "sec_type": pa.Column(str, nullable=True),
        "exchange": pa.Column(str, nullable=True),
        "primary_exchange": pa.Column(str, nullable=True),
        "currency": pa.Column(str, nullable=True),
        "local_symbol": pa.Column(str, nullable=True),
        "trading_class": pa.Column(str, nullable=True),
        "last_trade_date": pa.Column(str, nullable=True),
        "strike": pa.Column(float, nullable=True),
        "right": pa.Column(str, nullable=True),
        "multiplier": pa.Column(str, nullable=True),
        "position": pa.Column(float, nullable=False),
        "avg_cost": pa.Column(float, nullable=False),
        "fetched_at": pa.Column("datetime64[ns, UTC]", nullable=False),
    },
    name="PositionsSchema",
    strict=False,
)
