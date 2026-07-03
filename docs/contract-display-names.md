# Contract Display Names

## Purpose

Document how human-readable contract labels are built and used across the
ngtrader codebase. IBKR contracts have many raw fields (`symbol`,
`local_symbol`, `sec_type`, `contract_expiry`, `strike`, `right`,
`trading_class`). The display name compresses these into a compact,
TWS-style label an operator can read at a glance.

## Output Examples

| sec_type | Display name               | Notes                                   |
| -------- | -------------------------- | --------------------------------------- |
| STK      | `AAPL`                     | Symbol only                             |
| FUT      | `CL Dec'26`                | Symbol + month/year from expiry         |
| FOP      | `CL (LO) May14'26 65 CALL` | Trading class, day-level expiry, strike |
| OPT      | `CL Feb27'26 62.75 PUT`    | Same as FOP                             |
| BAG      | `CL` or localSymbol        | Combo — uses localSymbol when available |
| IND      | `VIX`                      | Symbol only (same as STK)               |

## Primary Method: `contract_display_name()`

**Location:** `src/utils/contract_display.py`

```python
def contract_display_name(
    symbol, sec_type, *,
    local_symbol=None, right=None, strike=None,
    contract_expiry=None, contract_month=None,
    exchange=None, trading_class=None,
    include_exchange=False,
) -> str
```

### Inputs (DB fields → parameters)

| Parameter          | DB column source                                        | Example value                       |
| ------------------ | ------------------------------------------------------- | ----------------------------------- |
| `symbol`           | `positions.symbol`, `orders.symbol`, etc.               | `"CL"`                              |
| `sec_type`         | `positions.sec_type`, `orders.sec_type`                 | `"FUT"`, `"FOP"`                    |
| `local_symbol`     | `positions.local_symbol`                                | `"CLU6"`, `"LO CL 27FEB26 62.75 P"` |
| `right`            | `positions.right`                                       | `"C"`, `"P"`                        |
| `strike`           | `positions.strike`                                      | `62.75`                             |
| `contract_expiry`  | `positions.last_trade_date`, `orders.contract_expiry`   | `"20260915"`                        |
| `contract_month`   | Inferred via `infer_contract_month_from_local_symbol()` | `"2026-09"`                         |
| `exchange`         | `positions.exchange`                                    | `"NYMEX"`                           |
| `trading_class`    | `positions.trading_class`                               | `"LO"`, `"LO4"`                     |
| `include_exchange` | Caller choice (default `false`)                         | —                                   |

### Formatting rules by sec_type

| sec_type    | Format                                                                                               |
| ----------- | ---------------------------------------------------------------------------------------------------- |
| `BAG`       | `localSymbol` if present, else `symbol`                                                              |
| `STK`/`IND` | `symbol`                                                                                             |
| `FUT`       | `symbol Mon'YY` (e.g. `CL Dec'26`)                                                                   |
| `FOP`/`OPT` | `symbol (tradingClass) MonDD'YY strike RIGHT` — trading class shown only when it differs from symbol |
| Other       | `symbol Mon'YY` fallback                                                                             |

### Internal helpers

| Helper                            | Location                          | Purpose                           |
| --------------------------------- | --------------------------------- | --------------------------------- |
| `_format_expiry_month_year()`     | `src/utils/contract_display.py`   | `"20260915"` → `"Sep'26"`         |
| `_format_expiry_day_month_year()` | `src/utils/contract_display.py`   | `"20260227"` → `"Feb27'26"`       |
| `_format_right()`                 | `src/utils/contract_display.py`   | `"C"` → `"CALL"`, `"P"` → `"PUT"` |

### Contract month inference

For positions, `contract_month` is not stored directly. It is inferred from
`local_symbol` via:

**Method:** `infer_contract_month_from_local_symbol()`
**Location:** `src/services/cl_contracts.py`

Parses futures month codes from the local symbol suffix (e.g. `CLU6` →
month code `U` = September → `"2026-09"`). Falls back to `contract_expiry`
if the local symbol pattern doesn't match.

## Where Display Names Are Built

### Positions (`src/api/routers/positions.py`)

Uses `contract_display_name()` with full field set from the `Position` model:

```python
display_name = contract_display_name(
    symbol=pos.symbol,
    sec_type=pos.sec_type,
    local_symbol=pos.local_symbol,
    right=pos.right,
    strike=pos.strike,
    contract_expiry=pos.last_trade_date,
    contract_month=inferred_month,       # from infer_contract_month_from_local_symbol()
    exchange=pos.exchange,
    trading_class=pos.trading_class,
)
```

**DB fields used:** `positions.symbol`, `positions.sec_type`,
`positions.local_symbol`, `positions.right`, `positions.strike`,
`positions.last_trade_date`, `positions.exchange`, `positions.trading_class`

### Orders (`src/api/routers/orders.py`)

Uses `contract_display_name()` with fields from the `Order` model,
supplemented by contract ref lookups when available:

```python
contract_display_name(
    symbol=effective_symbol,
    sec_type=effective_sec_type,
    local_symbol=effective_local_symbol,
    right=option_right,
    strike=float(option_strike) if option_strike else None,
    contract_expiry=effective_contract_expiry,
    contract_month=effective_contract_month,
    exchange=effective_exchange,
    trading_class=effective_trading_class,
)
```

**DB fields used:** `orders.symbol`, `orders.sec_type`,
`orders.local_symbol`, `orders.contract_expiry`, `orders.trading_class`,
`orders.exchange`, plus `contracts.*` via con_id join for richer metadata.

### Watch Lists (`src/api/routers/watch_lists.py`)

Uses `contract_display_name()` with fields from `WatchListInstrument`:

**DB fields used:** `watch_list_instruments.symbol`,
`watch_list_instruments.sec_type`, `watch_list_instruments.local_symbol`,
`watch_list_instruments.right`, `watch_list_instruments.strike`,
`watch_list_instruments.contract_expiry`,
`watch_list_instruments.exchange`, `watch_list_instruments.trading_class`

### Trade Executions (`src/api/routers/trades.py`)

Uses a separate method `_contract_display_from_raw()` because
`trade_executions` does not have contract columns — the contract info is
read from the `raw` JSON field, enriched with a `ContractRef` looked up via
`con_id` when the raw payload is missing a field (strike, right, trading
class, expiry).

**Method:** `_contract_display_from_raw()` in `src/api/routers/trades.py`

```python
def _contract_display_from_raw(
    raw: dict | None,
    contract_ref: ContractRef | None = None,
) -> str | None:
    # Reads symbol/sec_type/local_symbol/right/strike/trading_class/
    # contract_expiry from raw["contract"], falling back to contract_ref
    # fields (and to parsing the local_symbol) for anything raw is missing,
    # then calls contract_display_name() with the merged fields.
```

**Data source:** `trade_executions.raw` (`raw["contract"]["localSymbol"]`,
`raw["contract"]["secType"]`, `raw["contract"]["symbol"]`, etc.), joined
with `contracts` via `con_id` for richer fallback fields.

## DB Fields That Drive Display Names

| Table                    | Column                                        | IBKR source field                       | Used for             |
| ------------------------ | --------------------------------------------- | --------------------------------------- | -------------------- |
| `positions`              | `symbol`                                      | `contract.symbol`                       | Base symbol          |
| `positions`              | `sec_type`                                    | `contract.secType`                      | Format selection     |
| `positions`              | `local_symbol`                                | `contract.localSymbol`                  | Month inference, BAG |
| `positions`              | `last_trade_date`                             | `contract.lastTradeDateOrContractMonth` | Expiry formatting    |
| `positions`              | `strike`                                      | `contract.strike`                       | Option strike        |
| `positions`              | `right`                                       | `contract.right`                        | CALL/PUT             |
| `positions`              | `trading_class`                               | `contract.tradingClass`                 | Option class prefix  |
| `positions`              | `exchange`                                    | `contract.exchange`                     | Optional suffix      |
| `orders`                 | Same columns as above, plus `contract_expiry` | Same IBKR sources                       | Same purposes        |
| `contracts`              | All of the above                              | IBKR contract details response          | Enrichment via join  |
| `watch_list_instruments` | Same as positions                             | Same IBKR sources                       | Same purposes        |
| `trade_executions`       | `raw` (jsonb)                                 | Full fill object serialized             | localSymbol extract  |

## Gap: Trade-Level Display Names

Per-execution display names already enrich from `raw` JSON via
`_contract_display_from_raw(raw, contract_ref)`, joining `con_id` → `contracts`
for fields missing from `localSymbol` (see "Trade Executions" above). However,
the trade-level aggregate helper `_trade_contract_display_name()` always calls
`_contract_display_from_raw(execution_raw, None)` — it never passes a
`contract_ref`, so trade-level (as opposed to per-execution) display names don't
get the `contracts` enrichment.
