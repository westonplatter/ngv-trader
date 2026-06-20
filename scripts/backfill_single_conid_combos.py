"""Backfill: undo synthetic combos that were really single-instrument partial fills.

Background
----------
`_combo_groups` used to treat *any* set of executions sharing a brokerageOrderID as a
multi-leg combo. But a single-instrument order often fills in several executions (e.g.
10 GLD shares as 9 + 1). Those partial fills were grouped as a "combo", and the
synthesized `combo_summary` row got a price of `signed_cash / gcd(qty)` — which for
same-side, same-contract fills degrades to raw notional (10 × 400 = 4000) instead of a
per-unit price. `_recompute_trade_aggregates` then prefers the combo_summary, so the
parent Trade's avg_price inherited the same bogus notional.

The sync detector now requires >=2 distinct conids, so future syncs are correct. This
one-time backfill repairs rows already written:

For every BAG parent trade whose leg executions span <=1 distinct conid:
  1. Delete its combo_summary execution row(s) (cascades trade_group_executions membership).
  2. Revert its leg executions' exec_role to "standalone".
  3. Reset the parent Trade.sec_type from "BAG" to the legs' real sec_type.
  4. Recompute the parent Trade aggregates from the remaining canonical executions.

Genuine multi-conid spreads are left untouched.

Usage
-----
    op run --env-file=.env.prod -- uv run python scripts/backfill_single_conid_combos.py
    op run --env-file=.env.prod -- uv run python scripts/backfill_single_conid_combos.py --apply

Dry-run is the default; pass --apply to commit.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.db import get_engine
from src.models import (
    Trade,
    TradeExecution,
    TradeGroupExecution,
    TradeGroupExecutionEvent,
)
from src.services.sync_common import _recompute_trade_aggregates


def _distinct_leg_conids(legs: list[TradeExecution]) -> set[int]:
    conids = {leg.con_id for leg in legs}
    conids.discard(None)
    return conids


def _real_sec_type(legs: list[TradeExecution]) -> str | None:
    """Most common non-null leg sec_type (the instrument's true assetCategory)."""
    sec_types = [leg.sec_type for leg in legs if leg.sec_type]
    if not sec_types:
        return None
    return Counter(sec_types).most_common(1)[0][0]


def backfill(apply: bool) -> None:
    engine = get_engine()
    now = datetime.now(timezone.utc)

    repaired = 0
    deleted_summaries = 0
    reverted_legs = 0
    skipped_real_combos = 0

    with Session(engine) as session:
        bag_trades = session.execute(select(Trade).where(Trade.sec_type == "BAG")).scalars().all()
        print(f"Scanning {len(bag_trades)} BAG (combo) parent trades...\n")

        for trade in bag_trades:
            execs = session.execute(select(TradeExecution).where(TradeExecution.trade_id == trade.id)).scalars().all()
            legs = [e for e in execs if e.exec_role == "leg"]
            summaries = [e for e in execs if e.exec_role == "combo_summary"]

            if len(_distinct_leg_conids(legs)) >= 2:
                skipped_real_combos += 1
                continue  # genuine multi-leg spread — leave it alone

            new_sec_type = _real_sec_type(legs)
            summary_prices = [round(s.price, 4) for s in summaries]
            print(
                f"  trade={trade.id} {trade.symbol}: "
                f"delete {len(summaries)} summary(price={summary_prices}), "
                f"revert {len(legs)} leg(s) -> standalone, "
                f"sec_type BAG -> {new_sec_type}, "
                f"avg_price {round(trade.avg_price, 4) if trade.avg_price is not None else None} -> recompute"
            )

            if apply:
                # The live DB's FKs are not ON DELETE CASCADE (schema drift vs. the
                # model), so explicitly clear dependent rows before deleting the summary.
                summary_ids = [s.id for s in summaries]
                if summary_ids:
                    session.execute(delete(TradeGroupExecutionEvent).where(TradeGroupExecutionEvent.trade_execution_id.in_(summary_ids)))
                    session.execute(delete(TradeGroupExecution).where(TradeGroupExecution.trade_execution_id.in_(summary_ids)))
                for s in summaries:
                    session.delete(s)
                for leg in legs:
                    leg.exec_role = "standalone"
                    leg.updated_at = now
                trade.sec_type = new_sec_type
                trade.updated_at = now
                session.flush()
                _recompute_trade_aggregates(session, trade.id, now)

            repaired += 1
            deleted_summaries += len(summaries)
            reverted_legs += len(legs)

        if apply:
            session.commit()
            print("\nCOMMITTED.")
        else:
            print("\nDRY RUN — no changes written. Re-run with --apply to commit.")

    print(
        f"\nTrades repaired: {repaired} | summaries deleted: {deleted_summaries} | "
        f"legs reverted: {reverted_legs} | real spreads skipped: {skipped_real_combos}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Commit changes (default: dry run)")
    args = parser.parse_args()
    backfill(apply=args.apply)


if __name__ == "__main__":
    main()
