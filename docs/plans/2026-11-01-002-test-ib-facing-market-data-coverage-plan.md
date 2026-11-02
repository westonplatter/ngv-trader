---
title: Test the IB-Facing Chain and Market-Data Jobs - Plan
type: test
date: 2026-11-01
execution: code
---

# Test the IB-Facing Chain and Market-Data Jobs - Plan

## Goal Capsule

- **Objective:** Put characterization tests under the three IB-facing job entry points that #353 split without test coverage.
- **Means:** Drive each function with a duck-typed IB and a real test Postgres, and assert on the rows written and the dict returned.
- **Authority:** The tests pin today's behavior. If one shows a bug, record it and fix it in a separate change. Do not fold the fix into the test PR.
- **Stop conditions:** Stop and ask if a test needs a live TWS, a schema change, or a change to a public signature.
- **Execution profile:** Tests only. No `src/`, schema, or data changes.

## Background

PR #353 cleared the Ruff complexity findings and added a Ruff job to CI. It split 15 functions into private helpers. It added a 93-test characterization suite (`tests/test_complexity_refactor_characterization.py`) that passed on both the pre-split and the split code.

Three of the largest splits talk to IB and still have no tests. They were checked by reading and Pyright only:

| Function | Module | Job type | Handler |
| --- | --- | --- | --- |
| `sync_futures_chain` | `src/services/contract_sync.py` | `contracts.chain_sync` | `handle_contracts_chain_sync` |
| `fetch_futures_options` | `src/services/market_data.py` | `market_data.futures_options` | `handle_market_data_futures_options` |
| `fetch_snapshot` | `src/services/market_data.py` | `market_data.snapshot`, `contracts.qualify_and_snapshot` | `handle_market_data_snapshot`, `handle_contracts_qualify_and_snapshot` |

A separate reviewer read all three, old against new, and found no divergence in return values, exceptions, side-effect order, or early returns. That review is the only evidence today. A regression in any of them would surface only against a live broker.

Process note: #351 merged while #353 was in review, so main was merged into the #353 branch and the suite and both Ruff commands were re-run before the PR opened. Nothing in this plan depends on that.

## Scope

New test file per module: `tests/test_contract_chain_sync.py` and `tests/test_market_data_jobs.py`.

### `sync_futures_chain`

Helpers now in play: `_ChainSyncRun`, `_sync_index_contract`, `_collect_chain_info`, `_front_future_contracts`, `_sync_front_futures`, `_unexpired_expirations`, `_build_chain_meta_rows`, `_store_chain_meta`.

- Happy path: one index, two front futures, one chain per future. Assert the upserted contracts and the returned dict, `{"symbol", "ind", "fut", "fop", "chain_meta"}`. `fop` is always 0. Metadata is one row per expiration, right (`C` and `P`), and strike.
- The index fails to qualify: raises `RuntimeError` with today's message, and nothing is written.
- No chains returned: the index row is still written and counted. The dict has no `chain_meta` key, and no metadata session is opened.
- Expired expirations are dropped from the metadata rows, and so are ones that do not parse as `YYYYMMDD`. The cutoff is `date.today()`, so build expiries relative to today.
- A chain with no expirations or no strikes adds no rows.
- Front futures beyond `front_n` by expiry are not synced, and their chains add no metadata rows.
- A previously active future not in the front set is deactivated in the same commit. That happens only when at least one front future synced, so cover the case where none did as well.
- `underlyingConId` arrives as a string, and a blank or non-numeric one is ignored.
- Owned versus passed-in IB: a `TimeoutError` on connect becomes `RuntimeError`, an owned connection is disconnected in `finally`, and a passed-in one is left open.

### `fetch_futures_options`

Helpers now in play: `_option_refs_stmt`, `_apply_modulus_filter`, `_fetch_tickers_connected`, `_load_future_prices`, `_option_fields`, `_write_option_row`.

- Happy path: two FOP refs. Assert one `TsFuturesOptions` row and one `LatestFuturesOptions` upsert per ref, and the returned `{"symbol", "contracts", "rows_inserted"}`.
- No matching refs: returns zero counts without connecting to IB.
- The ref filters (`underlying_con_id`, strike bounds, `dte_lte`, `right`) select the expected rows.
- Modulus filter: strikes off the modulus are skipped, and a `None` strike passes through. With no `modulus_eq` argument, the default comes from `get_option_filter`.
- A ticker without `modelGreeks` still writes a row, with greeks null, and logs the warning.
- `und_price` falls back to the underlying's latest futures price, `last` if positive, otherwise `close`.
- A ref with no ticker is skipped and not counted.
- The latest-row guard: seed a `LatestFuturesOptions` row with a later `market_ts` and confirm it is not overwritten.
- Owned versus passed-in IB: an owned connection is disconnected in `finally`, even when a fetch raises. A passed-in one is left open.

### `fetch_snapshot`

Helpers now in play: `_snapshot_option`, `_snapshot_future`, `_write_future_row`, `_write_option_row`.

- FOP ref: the result dict carries `con_id`, `sec_type="FOP"`, `bid`, `ask`, `last`, `iv`, `delta`, `und_price`, and both option rows are written.
- FUT ref, or any non-FOP: the result dict carries `con_id`, `sec_type`, `bid`, `ask`, `last`, and both futures rows are written.
- Empty `con_ids`, or con_ids with no `ContractRef`: returns zero counts without connecting to IB.
- A con_id with no ticker is skipped and not counted.
- A mixed FOP and FUT batch writes each to its own tables in one commit.

## How

- **Fake IB.** Start from `_FakeIB` in `tests/test_ibkr_select_contracts.py`, which returns real `ib_async.Contract` objects.
  - Chain sync needs `qualifyContracts`, `reqContractDetails` returning `ContractDetails`-shaped objects with a `.contract`, and `reqSecDefOptParams` returning chains with `underlyingConId`, `tradingClass`, `expirations`, and `strikes`.
  - Market data needs `reqMarketDataType` and `reqTickers`. Tickers can be `SimpleNamespace` objects with a `.contract.conId` and `bid`, `ask`, `last`, `close`, and `modelGreeks`.
  - All three need `isConnected` and `disconnect`. Pass the fake as `ib=` for the main cases. For the owned-connection cases, patch `market_data._connect`, or `contract_sync.IB` for the chain sync, to return the fake.
- **Database.** These functions take an `Engine` and commit, so the `db_session` rollback fixture does not isolate them. Use an autouse cleanup fixture keyed on a dedicated symbol, as `tests/test_trade_sync_flexquery.py::_clean` does for an account code.
- **Ids.** Conids from the allow-list only (`123456789`, `234567890`, `345678901`, `400000001` through `400000010`). Run the scanner with `--paths` on each new file. See `docs/ibkr-sample-data.md`.
- **Prove it pins something.** Break one helper on purpose and confirm a test fails, then revert. For example, flip the comparison in `_unexpired_expirations` or drop the `market_ts` guard.

## Checks

```bash
uv run --extra mcp pytest tests/test_contract_chain_sync.py tests/test_market_data_jobs.py -o addopts="" -q
uv run --extra mcp pytest -o addopts="" -q
uv run ruff check src tests scripts && uv run ruff format --check src tests scripts
uv run python scripts/ibkr_sensitive_data_check.py --paths tests/test_contract_chain_sync.py tests/test_market_data_jobs.py
```

Ruff now runs in CI, so the new files must pass both Ruff commands.

## Out of scope

- The handlers in `src/workers/jobs.py` beyond what calling the service needs. The two handlers #353 split are covered by the characterization suite.
- `fetch_futures_prices` and `sync_contracts_with_ib`. They were not split.
- Any live-TWS or integration harness.
- Noticed while writing this plan: `_store_chain_meta` builds a `meta_insert` statement it never executes. The chunked upsert below it does the work. Removing the dead statement is a one-line follow-up and changes no behavior.
