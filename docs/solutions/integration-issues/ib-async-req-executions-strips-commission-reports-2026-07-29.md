---
title: ib_async reqExecutions returns fills stripped of their commission reports
date: 2026-07-29
category: integration-issues
module: intraday_sync_tws
problem_type: integration_issue
component: service_object
symptoms:
  - "Fills entered manually in TWS never reach `live_executions`, staying invisible until FlexQuery settles them the next day"
  - "Closing fills display 0.00 realized P&L while opening fills correctly show 0.00, making the two indistinguishable"
  - "Swapping `ib.fills()` for `ib.reqExecutions()` fixes visibility and silently breaks realized P&L"
root_cause: wrong_api
resolution_type: code_fix
severity: high
tags:
  - ib-async
  - ibkr
  - tws
  - executions
  - realized-pnl
  - broker-integration
related_components:
  - background_job
---

# ib_async reqExecutions returns fills stripped of their commission reports

## Problem

`ib.fills()` and `ib.reqExecutions()` look interchangeable — both return `list[Fill]` for the current trading day — but each drops data the other keeps. `fills()` misses executions this client never saw; `reqExecutions()` returns copies with empty commission reports. Picking either one alone silently loses data, and switching between them trades one bug for another.

## Symptoms

- Fills entered manually in TWS never reach `live_executions`, staying invisible until FlexQuery settles them the next day.
- Closing fills display `0.00` realized P&L. Opening trades legitimately report `0.00`, so the broken state looks identical to the correct one.
- The two symptoms appear at different times, because fixing the first causes the second.

## What Didn't Work

**Assuming `ib.fills()` returns everything for the day.** It returns only the _session_ cache: the snapshot `ib_async` takes at connect, plus whatever later arrives on `execDetails`. TWS pushes `execDetails` only to the client that placed the order, and manually-entered orders go to **client id 0** alone. A worker on any other client id (ours uses 40) never receives them. The connection is healthy and the call succeeds — it just returns an incomplete set, so nothing surfaces as an error.

**Then swapping in `ib.reqExecutions()` and using its return value.** This fixed visibility and quietly broke realized P&L. The regression was invisible for a while because `0.00` is a plausible value — every opening trade genuinely reports zero.

## Solution

Call `reqExecutions` for its **side effect** of registering unseen executions into the wrapper cache, then read the cache back:

```python
def _fetch_fills(ib: IB) -> list:
    try:
        ib.reqExecutions()   # discovery: registers fills this client never saw
    except Exception:
        logger.exception("reqExecutions failed; falling back to the session fill cache")
    return ib.fills()        # read back: carries merged commission reports
```

Two supporting changes keep the intermediate state honest, because realized P&L still lands one sync _after_ the fill is discovered:

```python
def _fill_realized_pnl(fill: Any) -> float | None:
    """None when no report has arrived yet — distinct from a report saying zero."""
    report = getattr(fill, "commissionReport", None)
    if report is None or not getattr(report, "execId", ""):
        return None
    return _safe_float(getattr(report, "realizedPNL", None))
```

```python
# A pending None must not overwrite a value already stored; a real value still wins.
updates["realized_pnl"] = func.coalesce(stmt.excluded.realized_pnl, LiveExecution.realized_pnl)
```

## Why This Works

`ib_async` splits execution and commission data across two callbacks, and the `Fill` object is the join point:

1. `execDetails` constructs `Fill(contract, execution, CommissionReport(), time)` — an **empty** report.
2. The separate `commissionReport` callback later looks up `self.fills[execId]` and merges realized P&L into that cached object in place.

The trap is in `wrapper.py`:

```python
fill = Fill(contract, execution, CommissionReport(), time)
if execId not in self.fills:      # cache keeps the enriched object
    self.fills[execId] = fill
if not isLive:
    self._results[reqId].append(fill)   # ...but a stripped copy is returned
```

A fresh `Fill` is built for _every_ reported execution, but it is only stored when the `execId` is new. For an execution already cached, `_results` receives the stripped copy while the enriched one stays in `self.fills`. `reqExecutions()` returns `_results`; `ib.fills()` returns `self.fills.values()`.

So `reqExecutions` is the only call that _discovers_ executions regardless of client id, and `ib.fills()` is the only one that _carries_ commission data. Doing both in that order gets both.

The one-sync lag is inherent: TWS sends `commissionReport` after `execDetailsEnd`, so the report arrives once the call has already returned. It merges into the cached `Fill` in the background and the next sync picks it up. That is why `None` and `0.0` must be distinguishable — a default-constructed `CommissionReport` has `execId == ""`, which is the discriminator.

## Prevention

- **When a broker/library call has both a cache accessor and a request method, assume they return different data, not the same data by different routes.** Read the wrapper source before choosing. `ib_async`'s own docstring on `reqExecutions` says "It is recommended to use `fills` or `executions` instead" without explaining that the reverse direction loses commission data.
- **Treat a zero-valued financial field as suspicious when the "not yet known" state is also zero.** Any field where the library pre-populates a default that collides with a legitimate value needs a separate discriminator. Prefer `None` for unknown and reserve `0.0` for measured zero.
- **Make upserts non-destructive for fields that arrive late.** A blanket `set_={all columns}` on conflict will overwrite good data with a not-yet-populated null on the next pass. Coalesce any column whose source is asynchronous.
- **Verify against a real closing trade, not just any fill.** Opening fills report `0.00` realized P&L correctly, so they cannot distinguish working code from broken code. The bug was only observable on a close.

## Related Issues

- PR #94 (`feat: trade-booking improvements for unsettled fills and tagging`) — commits `5094982` (this fix) and the earlier `_fetch_fills` change it corrects.
- Two adjacent fixes from the same investigation, both in `src/services/intraday_sync_tws.py`:
  - **Trade-date boundary.** The overlay's "today" window started at ET midnight, but CME's trade date opens at 18:00 ET, so evening fills were filed under the wrong date and dropped ~6 hours later — while FlexQuery would not report them for another day.
  - **Combo settle handoff.** TWS reports a combo's BAG summary under an `execId` from a different id family than its legs, while the FlexQuery path synthesizes the settled summary _from_ the legs. The two rows can never share an `ib_exec_id`, so an id-equality purge cannot retire the live one and combos showed twice.
- `docs/core/intraday-tws-overlay.md` — the overlay's sync rules and live/settled two-tier model.
