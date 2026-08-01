# Concepts

Shared domain vocabulary for this project — entities, named processes, and status concepts with project-specific meaning. Seeded with core domain vocabulary, then accretes as ce-compound and ce-compound-refresh process learnings; direct edits are fine. Glossary only, not a spec or catch-all.

## Relationships

An Execution is the atomic record; Positions and Trade Groups are both rollups over Executions, along different axes. A Position groups Executions by instrument and account and answers "what do I hold." A Trade Group groups them by the operator's intent and answers "what was I trying to do." Because both are derived, an instrument with no Executions can appear as a Position (the broker reports the holding directly) yet be impossible to place in a Trade Group.

## Trade data

### Execution

A single fill reported by the broker — one instrument, one side, one quantity, at one instant. The atomic unit of trade data; everything else in this domain is a rollup over Executions.
_Avoid:_ fill (when precision matters — see Unsettled Fill)

Every Execution carries a broker-assigned execution id, which is the join key across the Settled and Unsettled tiers. That id is stable for ordinary fills but not universally: the two tiers can describe the same Combo under ids drawn from different families, which is why identity matching exists alongside id matching.

### Settled Execution

An Execution as the broker's official post-trade record reports it, once end-of-day processing has run. Settled data is the authoritative record: wherever a Settled and an Unsettled view of the same fill disagree, Settled wins.

Settled data lags by roughly a business day — it publishes only through the previous trade date. That lag is the entire reason the Overlay exists.

### Unsettled Fill

An Execution observed live from the broker terminal before it has settled. Exists to cover the settlement lag, and is provisional by construction: it is discarded rather than reconciled once its Settled counterpart appears.
_Avoid:_ live execution, real-time fill

An Unsettled Fill can be assigned to a Trade Group before it settles, and that assignment carries over to the Settled Execution during the Settle Handoff, so grouping survives the transition without a gap.

### Overlay

The live tier layered on top of the settled record: current holdings, current marks, and recent Unsettled Fills, read from a broker terminal session. It never replaces settled data — it fills the gap ahead of it, and degrades to settled values when no live session is available.

The Overlay retains a bounded rolling window of recent fills rather than everything since a session or calendar boundary. An anchored window makes the retained span depend on when the sync happens to run; a rolling one does not.

### Settle Handoff

The transition of a fill from the Unsettled tier to the Settled tier. The Unsettled row is retired and any Trade Group assignment on it is carried to the Settled Execution first, so the fill is never both places at once and never loses its grouping.

This is what makes it safe for the Overlay to reach back past the settlement boundary: re-observing a fill that has already settled is a no-op, because the handoff retires it in the same transaction that wrote it.

## Instruments and structure

### Trade Date

The exchange's own calendar day for a fill, which is not the local wall-clock date. Futures trade dates roll in the evening, so a fill placed after the roll belongs to the _next_ trade date.

This routinely makes an evening fill look like it settled a day late when its wall-clock date is shown next to a settlement status governed by trade date. The two disagreeing is expected, not a defect.

### Combo

A multi-leg order placed and filled as a single unit. The broker reports it twice over: once as a summary row for the whole structure, and once per constituent Leg.

The summary row is a display convenience, not an independent fill — its quantities and prices are already accounted for by the Legs. The live and settled tiers derive the summary differently, so the two summaries describe the same event under unrelated ids and must be matched by identity rather than by id.

### Leg

One instrument within a Combo. Legs carry the real economics of the structure; the Combo summary is derived from them.

## Grouping and intent

### Trade Group

A named grouping of Executions representing one trading idea — a spread, a roll, a thesis carried across several instruments and possibly several accounts. The operator's unit of intent, as opposed to the broker's unit of record.

Membership is defined at the Execution level, not the instrument level, so a single instrument's fills can belong to different Trade Groups. Assigning a Position to a Trade Group is shorthand for assigning the Executions behind it — which means an instrument with no Executions yet cannot be grouped at all.

### Position

A current holding in one instrument for one account — the net of its Executions. Distinct from a Trade Group in that it is derived from the instrument, not from intent.

The broker reports current holdings directly, so a Position can exist before any of its Executions have been recorded on either tier.
