---
title: Upgrade ib_async v2 to v3 - Plan
type: chore
date: 2026-11-19
---

# Upgrade ib_async v2 to v3 - Plan

**Status:** NOT STARTED. ib_async v3 is not on PyPI yet (latest is 2.1.0).
**Source:** the upstream [v3 migration guide](https://github.com/ib-api-reloaded/ib_async/blob/next-protobuf/docs/migration/v3.md).
**Scope:** what has to change, or be checked, in this repo and in `ngv-reports-ibkr` before we upgrade.

## Why act before the release

- `pyproject.toml` declares `ib-async>=2.1.0` with no upper bound, and
  `ngv-reports-ibkr` declares `ib-async` unpinned.
- The first lock upgrade or dependency-bot bump after v3 ships would pull it in and
  break the FlexQuery sync (see 1).
- Pin `ib-async>=2.1.0,<3` until the work below lands, then upgrade in one change.

## What does not affect us

We use none of these, so the guide's sections on them need no work: historical bars or
real-time bars built from ticks, market depth, `util.df()`, `HistogramData`,
`ContFuture`, `Client` subclasses, `reqId2Ticker`, the patched methods
(`.dict()`, `.update()`, `dataclassUpdate`), `AccountValue.decimalValue`, and
`isinstance` checks on order types.

## 1. FlexQuery sync: `FlexReport.df()` returns polars (blocking)

This is the active trade path.

- `ngv_reports_ibkr.CustomFlexReport` subclasses `ib_async.flexreport.FlexReport`.
  Every method on it calls `self.df(...)` and then uses pandas (`.query`, `.unique`,
  pandera `pandas` schemas).
- In v3 `df()` returns a polars DataFrame, so `trades_by_account_id`,
  `open_positions_by_account_id` and `account_ids` all fail.
- That breaks `src/services/trade_sync_flexquery.py`,
  `src/services/position_sync_flexquery.py`, and the FlexQuery job in
  `src/workers/jobs.py`.
- Fix it in `ngv-reports-ibkr`: convert at the boundary with
  `self.df(name).to_pandas()` (pyarrow is already a dependency), or port the package
  to polars. Then release it and bump it here.
- Check the dtypes after the switch. Flex numbers come back as polars `Decimal`
  columns, and a `.to_pandas()` conversion can give `object` columns that the
  pandera schemas reject.
- `FlexReport.load()` now raises `FlexError` for a file that is not XML.

## 2. `Decimal` values dropped without an error (data correctness)

In v3, `Execution.shares/price/cumQty/avgPrice`,
`CommissionReport.commissionAndFees/realizedPNL`, `Position.position/avgCost`,
`OrderStatus.*` and `Order.totalQuantity/lmtPrice` become `Decimal | None`.

Several helpers accept only `numbers.Real`. `Decimal` is not a `Real`
(`isinstance(Decimal("1"), Real)` is `False`), so these helpers return `None` for
every value:

| Helper | Effect under v3 |
| --- | --- |
| `src/services/intraday_sync_tws.py` `_safe_float` / `_safe_int` | `live_executions` gets quantity 0.0, price 0.0 and realized_pnl NULL. `_lifecycle_from_live_execution` then labels every unsettled fill "Open". |
| the same helpers, reused by `src/services/option_metrics_sync_tws.py` | Greeks, if `OptionComputation` fields become `Decimal` (to be confirmed) |
| `src/services/market_data.py` `_safe_float` / `_safe_int` | Quotes and volume, if `Ticker` fields become `Decimal` (to be confirmed) |
| `src/services/watchlist_quotes.py` `_safe_price` | The same, for watchlist quotes |
| `src/services/order_keys.py` `_as_int` | None today, since `permId` and `orderId` stay `int` |

- Fix: accept `Decimal` (or `numbers.Number` minus `bool`), convert with
  `float()` at the boundary, and treat `None` as unset. In v3 NaN is no longer the
  unset sentinel.
- Already safe, because they use `float()` and `int()` directly:
  `sync_common._safe_float` / `_safe_int`, `order_sync_tws.parse_float` /
  `parse_int`, and `order_worker.parse_float`.
- `Decimal` written to `Float` columns (`positions`, `live_positions`) goes through
  psycopg without trouble. No change needed.
- Arithmetic that mixes `Decimal` and `float` raises `TypeError`. Look for any
  arithmetic on raw ib_async fields that does not go through a coercion helper first.

## 3. `commission` renamed to `commissionAndFees`

- `src/services/trade_sync_tws.py` reads `commissionReport.commission` in
  `_fill_to_raw` and `tws_fills_to_fills`. This works in v3 with a
  `DeprecationWarning` and is removed in v4. Switch both reads to
  `commissionAndFees`.
- v2.1.0's `CommissionReport` has no `commissionAndFees`, so make this switch in
  the bump change itself. Doing it earlier needs a fallback:
  `getattr(r, "commissionAndFees", None)`, then `commission`.
- The constructor keyword `commission=` raises `TypeError` in v3. We construct none
  in `src/`.
- The fake in `tests/test_trade_sync_tws.py` builds `commissionReport` with
  `commission=`. Update it to match.
- Our own `TradeExecution.commission` column and FlexQuery's `ibCommission` are not
  affected.

## 4. Order types are functions that return `Order`

- `src/services/order_worker.py` `_build_ib_order` uses
  `LimitOrder | MarketOrder` as its return type and as the type of `ib_order`.
  Pyright rejects this once these are functions. Change both to `Order`.
- The calls (`LimitOrder(side, qty, price)`, `MarketOrder(side, qty)`) still work:
  float input becomes `Decimal` via `str()`.
- Construction is now checked and raises `OrderTypeError` on bad input. Confirm the
  worker's error path handles that error.

## 5. JSON serialization of `Decimal`

- `trade_sync_tws._fill_to_raw` puts `shares`, `price`, `cumQty`, `avgPrice` and
  `realizedPNL` into `TradeExecution.raw`, a `JSON` column.
- `json.dumps` raises `TypeError` on a `Decimal`.
- The path is dormant today. Convert those values with `float()` or `str()` before
  re-enabling it.

## 6. Behaviour changes to re-check

- **Early commission reports.** v3 buffers a `commissionReport` that arrives before
  its `execDetails` and replays it when the execution lands. Re-read the docstrings
  of `intraday_sync_tws._fetch_fills` and `_fill_realized_pnl`. Confirm that an
  empty `execId` still marks a report that has not arrived yet, and that
  `reqExecutions` plus reading `ib.fills()` back still keeps the merged report.
- **Unset sentinels become `None`.** `select_mark` already treats −1, 0 and `None`
  as missing. Check any other `math.isnan` guard on ib_async fields (the
  market-data and watchlist helpers above).
- **Frozen records.** `Fill`, `Position` and `PortfolioItem` are frozen slotted
  dataclasses: no indexing, no `_asdict`, no setting attributes. We only read
  attributes, but grep once to make sure. `Contract` is still mutable, so
  `_ensure_market_data_exchange` setting `exchange` is fine.
- **BAG equality.** Bags now compare field by field, not by conId. Our combo
  grouping keys on `permId` / `orderId` and conId values, not on `Contract`
  equality, so nothing should change. Confirm during testing.
- **Server version.** `MaxClientVersion` goes from 178 to 226, and v3 speaks
  protobuf to servers at 201 and above. The error-message decoding that v2
  mis-shifted on newer servers is fixed, so error text and `reqId` routing may
  change. Re-check anything that matches on error strings.
- **Optional:** `ExecutionFilter.lastNDays` could replace the hand-built `time=`
  string in `trade_sync_tws`.

## 7. Tests

- The fakes in `tests/test_trade_sync_tws.py`, `tests/test_option_metrics_write.py`
  and the intraday or market-data tests use plain floats and NaN, so they cannot
  catch section 2.
- Switch these fixtures to `Decimal` values and `None` for unset fields, and add one
  regression test for each helper in section 2.
- Run the suite once with `-W error::DeprecationWarning` to catch any remaining v2
  call sites.
- Before merging, run the intraday overlay, order worker and FlexQuery sync against
  a paper TWS / IB Gateway at server version 213 or later.

## Order of work

1. Pin `ib-async<3` here.
2. Port `ngv-reports-ibkr` (section 1) and release it with a v3-compatible range.
3. Here: sections 2, 4 and 5 and the test fixtures (section 7). These also work
   on v2.
4. Lift the pin, bump to v3, and do the `commissionAndFees` switch (section 3).
   Run the checks and the live TWS check, then update this plan's status.
