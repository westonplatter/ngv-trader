---
title: Trim Overlapping Backend Tests - Plan
type: test
date: 2026-11-01
execution: code
status: implemented
---

# Trim Overlapping Backend Tests - Plan

## Goal Capsule

- **Objective:** Remove backend tests that assert the same behavior as another test, without losing coverage of `src/`.
- **Means:** Delete or merge the tests listed under [Cuts](#cuts), then hoist shared fixtures.
- **Authority:** A cut is only valid if the surviving test asserts the same thing. Line coverage found the candidates; reading the tests confirmed them.
- **Stop conditions:** Stop if a cut would drop a unique assertion, or if `src/` line coverage falls after the change.
- **Execution profile:** Tests only. No `src/`, schema, or data changes.

## Findings

Sweep of `tests/` on 2026-11-01: 24 files, about 3,400 lines, 314 tests, 22 s with a local Postgres. The suite is fast, so the motive is clarity and maintenance, not speed.

Method: ran pytest with per-test coverage contexts (`--cov=src --cov-context=test`), compared covered lines per test and per file, then read the high-overlap files.

- 151 tests have no uniquely covered `src/` line. That is too crude to cut on: shared plumbing dominates.
- Overlap is concentrated around `intraday_overlay.py`, `trade_group_pnl.py` and `execution_pnl.py`.
- File-level share of lines also covered by another test file:

| File | Shared |
| --- | --- |
| `test_trade_group_pnl_batch.py` | 99.8% |
| `test_intraday_overlay.py` | 99.1% |
| `test_trade_group_instruments.py` | 97.8% |
| `test_trade_groups_api.py` | 95.7% |
| `test_execution_pnl.py` | 94.1% |
| `test_trade_group_position_split.py` | 92.9% |
| `test_position_sync_purge.py` | 100% |
| `test_tags_and_tasks.py` | 41.9% (most unique) |

Line coverage cannot tell "same assertion" from "same code path". Mutation testing was not run.

## Cuts

About 11 tests (~3% of the suite).

| Cut | Why it is redundant |
| --- | --- |
| `test_positions_api.py::TestStaleOverlayDefersToSettled` (2 tests) | Same scenario as `test_intraday_overlay.py::test_stale_overlay_defers_to_the_settled_snapshot` and `test_fresh_overlay_still_wins` (2 vs 1 qty, 4-day-old live row). Keep the unit tests. Carry over the `live_fetched_at` assertion. Keep `TestAvgCostUnits`. |
| `test_trade_groups_api.py::test_instrument_filter_applies_before_the_row_limit` | Duplicates `test_trade_group_instruments.py::test_filter_applies_before_the_limit_not_after`. |
| `test_trade_groups_api.py::test_instrument_pattern_selects_only_matching_groups` | Same assertion as `test_pattern_matches_the_groups_instruments`; `test_instrument_and_account_filters_compose` already exercises the route. |
| `test_trade_groups_api.py::test_instrument_filter_populates_instruments_without_the_overlay` | `test_instruments_are_returned_per_row_and_empty_never_null` and `test_default_request_leaves_every_new_field_unset` cover both its assertions. |
| `test_trade_groups_api.py::test_account_filter_scopes_the_figures_not_just_the_row_list` | Same two-account fixture and numbers as `test_account_scoped_row_matches_the_detail_endpoints_per_account_breakdown` and the batch account-scoping tests. Fold its `instruments` assertions into one of them. |
| `test_trade_group_instruments.py::test_instruments_can_be_scoped_to_one_account` | Overlaps the account-scoped API test on `instruments`. Keep one side. |
| `test_flexquery_two_phase.py::test_windows_wider_than_a_week_wait_at_least_a_minute` | Implied by `test_first_check_ladder`. |
| `test_trade_group_pnl_batch.py::test_batch_matches_compute_trade_group_pnl_field_by_field` | Subsumed by `test_batch_matches_per_group_path_across_several_groups`. Move the "not vacuous" asserts into the multi-group test. |
| `test_trade_group_position_split.py::test_batch_and_single_group_paths_apportion_the_same_way` | Same `_split_short` fixture and result as `test_each_group_shows_only_its_own_lot`. Keep one equivalence check. |
| `test_models.py::test_account_round_trip` | Every DB test round-trips ORM rows; `test_database.py` covers wiring. |
| `test_flexquery_tokens_api.py::test_create_stores_ciphertext` | Same assertion as `test_flexquery_tokens.py::test_raw_column_holds_ciphertext`. |

## Consolidation

- Move the `client` fixture (`dependency_overrides[get_db]`) into `tests/conftest.py`. It is duplicated in `test_positions_api.py`, `test_trade_groups_api.py`, `test_trade_group_position_split.py` and `test_tags_and_tasks.py`.
- `test_flexquery_two_phase.py`: fold the fetch-report paused-token test into the parametrized initiate test; they share the same monkeypatch and `_explode` block.
- Merge the pattern-validation tests in `test_trade_group_instruments.py` (blank, valid round-trip, filter-condition) into one parametrized test. Drop their unused `db_session` argument.
- Remove plan-ID references in test comments (`R6`, `KTD1`, `U3`) where the plan has shipped and been folded.
- Optional: split `test_tags_and_tasks.py` (355 lines) by area. This is readability only.

## Keep

- Per-consumer tests of the stale-overlay rule. It is enforced in five places and has regressed before (see the `test_intraday_overlay.py` regression-guard comment).
- List-row vs detail-endpoint agreement tests.
- `test_query_count_*`.
- `test_crypto.py`, `test_flexquery_tokens.py` and `test_flexquery_tokens_api.py`: they cover different layers.

## Verification

1. Baseline: run the suite with `--cov=src` and record per-module line coverage.
2. Apply the cuts and consolidation.
3. Re-run. Per-module coverage must not drop, and the suite must pass.
4. Optional: mutation test `trade_group_pnl.py` and `intraday_overlay.py` (`mutmut` or `cosmic-ray`) before and after, to confirm no regression slips through.
5. `uv run python scripts/docs_check.py` after any doc change.

## Outcome

Implemented on 2026-11-01. 314 tests became 308; suite time 22 s to 12 s. Covered `src/` lines are identical before and after (4,829), and Pyright errors in `tests/` did not increase.

Deviations from the cuts above, found while applying them:

- Kept `test_batch_and_single_group_paths_apportion_the_same_way`. It is the only test of the batch path on the split-lot fixture; the multi-group equivalence test does not use that fixture.
- Kept `test_instruments_can_be_scoped_to_one_account` (the direct test of the account argument) and folded the API-level scoped `instruments` assertions into the per-account breakdown test. The plan said to keep one side; cutting both would have left the argument untested.
- Not done: removing `R6`/`KTD1`/`U3` plan-ID comments. Whether those plans are folded was not verified.
- Not done: the optional mutation-testing check and the `test_tags_and_tasks.py` split.
