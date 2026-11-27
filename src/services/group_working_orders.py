"""Working broker orders for the contracts a trade group holds.

An order belongs to no group. It is shown under every group that holds one of its
contracts in the same account: a single-leg order by its own con_id, a combo by
any of its legs.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from src.models import (
    Order,
    OrderLeg,
    TradeExecution,
    TradeGroupExecution,
    TradeGroupLiveExecution,
)
from src.services.order_queue import (
    ORDER_STATUS_PARTIALLY_FILLED,
    ORDER_STATUS_RECONCILE_REQUIRED,
    ORDER_STATUS_SUBMITTED,
)
from src.services.trade_group_pnl import GroupLedger, PairKey, load_group_ledgers

WORKING_ORDER_STATUSES = (ORDER_STATUS_SUBMITTED, ORDER_STATUS_PARTIALLY_FILLED, ORDER_STATUS_RECONCILE_REQUIRED)
_HELD_EPSILON = 1e-9


@dataclass(frozen=True)
class GroupWorkingOrder:
    order: Order
    matched_con_ids: list[int]
    shared_with_group_ids: list[int]


def group_open_pairs(ledger: GroupLedger) -> set[PairKey]:
    held = {key for key, quantity in ledger.holdings.total.items() if abs(quantity) > _HELD_EPSILON}
    return held | set(ledger.extra_pairs)


def _order_con_ids(order: Order, legs: list[OrderLeg]) -> list[int]:
    if legs:
        return [leg.con_id for leg in legs]
    return [order.con_id] if order.con_id is not None else []


def _other_holders(session: Session, group_id: int, pairs: set[PairKey]) -> dict[PairKey, list[int]]:
    """Other groups that also hold each pair now."""
    if not pairs:
        return {}
    pair_list = list(pairs)
    settled = select(TradeGroupExecution.trade_group_id).join(TradeExecution, TradeExecution.id == TradeGroupExecution.trade_execution_id)
    settled = settled.where(tuple_(TradeExecution.account_id, TradeExecution.con_id).in_(pair_list), TradeGroupExecution.trade_group_id != group_id)
    live = select(TradeGroupLiveExecution.trade_group_id).where(
        tuple_(TradeGroupLiveExecution.account_id, TradeGroupLiveExecution.con_id).in_(pair_list),
        TradeGroupLiveExecution.trade_group_id != group_id,
    )
    candidates = sorted(set(session.execute(settled).scalars()) | set(session.execute(live).scalars()))
    holders: dict[PairKey, list[int]] = {}
    for other_id, ledger in load_group_ledgers(session, candidates).items():
        for pair in group_open_pairs(ledger) & pairs:
            holders.setdefault(pair, []).append(other_id)
    return holders


def working_orders_for_group(session: Session, group_id: int) -> list[GroupWorkingOrder]:
    pairs = group_open_pairs(load_group_ledgers(session, [group_id])[group_id])
    if not pairs:
        return []
    orders = list(
        session.execute(
            select(Order)
            .where(Order.status.in_(WORKING_ORDER_STATUSES), Order.account_id.in_({account_id for account_id, _ in pairs}))
            .order_by(Order.created_at.desc(), Order.id.desc())
        ).scalars()
    )
    legs_by_order: dict[int, list[OrderLeg]] = {}
    if orders:
        leg_rows = session.execute(select(OrderLeg).where(OrderLeg.order_id.in_([order.id for order in orders])).order_by(OrderLeg.leg_index)).scalars()
        for leg in leg_rows:
            legs_by_order.setdefault(leg.order_id, []).append(leg)

    matched: list[tuple[Order, list[int]]] = []
    for order in orders:
        con_ids = sorted({con_id for con_id in _order_con_ids(order, legs_by_order.get(order.id, [])) if (order.account_id, con_id) in pairs})
        if con_ids:
            matched.append((order, con_ids))

    holders = _other_holders(session, group_id, {(order.account_id, con_id) for order, con_ids in matched for con_id in con_ids})
    return [
        GroupWorkingOrder(
            order=order,
            matched_con_ids=con_ids,
            shared_with_group_ids=sorted({other for con_id in con_ids for other in holders.get((order.account_id, con_id), [])}),
        )
        for order, con_ids in matched
    ]
