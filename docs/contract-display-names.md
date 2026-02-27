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

**Location:** `src/utils/contract_display.py:53`

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

| Helper                            | Location                           | Purpose                           |
| --------------------------------- | ---------------------------------- | --------------------------------- |
| `_format_expiry_month_year()`     | `src/utils/contract_display.py:10` | `"20260915"` → `"Sep'26"`         |
| `_format_expiry_day_month_year()` | `src/utils/contract_display.py:31` | `"20260227"` → `"Feb27'26"`       |
| `_format_right()`                 | `src/utils/contract_display.py:44` | `"C"` → `"CALL"`, `"P"` → `"PUT"` |

### Contract month inference

For positions, `contract_month` is not stored directly. It is inferred from
`local_symbol` via:

**Method:** `infer_contract_month_from_local_symbol()`
**Location:** `src/services/cl_contracts.py`

Parses futures month codes from the local symbol suffix (e.g. `CLU6` →
month code `U` = September → `"2026-09"`). Falls back to `contract_expiry`
if the local symbol pattern doesn't match.

## Where Display Names Are Built

### Positions (`src/api/routers/positions.py:94`)

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

### Orders (`src/api/routers/orders.py:184`)

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

### Watch Lists (`src/api/routers/watch_lists.py:135`)

Uses `contract_display_name()` with fields from `WatchListInstrument`:

**DB fields used:** `watch_list_instruments.symbol`,
`watch_list_instruments.sec_type`, `watch_list_instruments.local_symbol`,
`watch_list_instruments.right`, `watch_list_instruments.strike`,
`watch_list_instruments.contract_expiry`,
`watch_list_instruments.exchange`, `watch_list_instruments.trading_class`

### Trade Executions (`src/api/routers/trades.py:18`)

Uses a separate method `_contract_display_from_raw()` because
`trade_executions` does not have contract columns — the contract info is
stored in the `raw` JSON field.

**Method:** `_contract_display_from_raw()`
**Location:** `src/api/routers/trades.py:18`

```python
def _contract_display_from_raw(raw: dict | None) -> str | None:
    contract = raw.get("contract")
    local_symbol = contract.get("localSymbol")
    sec_type = contract.get("secType")
    symbol = contract.get("symbol")
    # BAG → "CL Combo"
    # Otherwise → localSymbol (e.g. "CLU6") or symbol fallback
```

**Data source:** `trade_executions.raw` → `raw["contract"]["localSymbol"]`,
`raw["contract"]["secType"]`, `raw["contract"]["symbol"]`

This method uses IBKR's `localSymbol` directly rather than building a
display name from components, because `trade_executions` does not persist
the individual contract fields (`strike`, `right`, `trading_class`,
`contract_expiry`) as columns.

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

## Gap: Trade Executions

`trade_executions` does not have dedicated contract columns. Display names
are extracted from the `raw` JSON, which limits formatting to whatever IBKR
puts in `localSymbol`. If `spec-first-class-spread-fields.md` adds
`sec_type` to `trade_executions`, and if `con_id` is also added, the
executions display could join to the `contracts` table and use the full
`contract_display_name()` method for richer output.
