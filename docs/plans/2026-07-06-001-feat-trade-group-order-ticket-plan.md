---
title: "feat: Trade group order-ticket (Layer 1 storage + Layer 2 contract)"
type: feat
status: active
created: 2026-07-06
depth: standard
target_repo: ngv-trader
related_repos: [ngv]
---

# feat: Trade group order-ticket (Layer 1 storage + Layer 2 contract)

## Summary

Add a durable, back-office record of a **spread trade construction** ("order-ticket")
attached 1:1 to a `trade_group` in **ngv-trader**. The ticket captures _what_ the trade is
— its legs, ratios, direction, and spread kind (intra- vs inter-commodity) — and nothing
about _how_ it gets executed. A separate repo (**ngv**) reads this ticket over the
existing FastAPI surface and stages the actual IBKR combo order; ngv-trader is not
responsible for execution and stores no execution mechanics.

This plan specifies **Layer 1** (the ngv-trader storage + API) in full, and describes
**Layer 2** (the ngv execution consumer) at a high-to-medium level as an _awareness_
section — Layer 2 is out of scope for ngv-trader work but defines the integration contract
ngv-trader must honor.

The end-to-end desk workflow this enables:

1. Research a spread in SeasonAlgo → screenshot.
2. Paste the screenshot to an agent → the agent POSTs a trade group + order-ticket to
   ngv-trader.
3. An ngv notebook pulls the ticket by trade-group id, merges it with ngv-local
   instrument facts, and stages an untransmitted IBKR combo order for the desk to review
   and Transmit.

---

## Problem Frame

The desk currently hand-authors a bespoke Jupyter notebook (or edits a generic one) per
spread idea. There is no shared, queryable record of "the trade we intend to put on."
ngv-trader already models the _fills_ side of a trade group (`trade_group_executions`,
`trade_group_live_executions`) but has **no representation of the trade intent/plan** — a
`trade_group` is a labeling container with `name`, `notes`, `status`, and no legs.

Meanwhile the ngv repo has a working combo-staging engine (`ngv.vol.execution.ibkr_stage`)
that turns a small spec into an untransmitted IBKR BAG order across accounts. What's
missing is the durable, agent-writable, back-office record that seeds that engine — and a
clean seam so the back office never learns execution details.

**Design principle (user directive):** ngv-trader is the system of record for the trade
_idea_; it must not know execution mechanics (tick, point value, exchange routing, limit
price, pricing aggressiveness, accounts, lots). Those belong to the execution layer (ngv).

**Existing spread representation for context:** ngv-trader already reconstructs multi-leg
spreads _after execution_ as IBKR `BAG` combos in `trade_executions`
(`exec_role in {combo_summary, leg}`, migration
`alembic/versions/20260227120000_add_spread_fields_to_trade_executions.py`). The
order-ticket is the _pre-trade_ mirror of that: the plan that later collects those fills
into the same trade group.

---

## Scope Boundaries

**In scope (Layer 1 — ngv-trader):**

- A new `trade_group_orders` table, 1:1 (nullable) with `trade_groups`.
- A `TradeGroupOrder` ORM model + relationship on `TradeGroup`.
- API: embed the `order` in the trade-group read model; upsert it via a sub-resource;
  accept it optionally on trade-group create; delete it.
- Shape validation of the ticket (legs well-formed; `spread_type` consistent with legs).
- The documented cross-repo JSON contract for the `order` object.

**Out of scope / explicitly not stored in ngv-trader (belongs to Layer 2 — ngv):**

- Execution mechanics: `tick`, `point_value`, `exchange`, `currency`, `limit`, `pct`,
  `accounts`, `lots`, market-data type.
- The IBKR combo-staging engine, instrument reference table, and notebooks.
- Deep contract validation (parsing `HEJ27` → symbol/expiry, qualifying conIds against
  IBKR). ngv-trader does light shape validation only.

### Deferred to Follow-Up Work

- **Ticket lifecycle status** (`draft → staged → transmitted`). Deliberately omitted from
  v1 to keep the back office unaware of execution state. If the desk later wants
  visibility that a ticket has been sent to execution, add a minimal `status` column then
  (see Key Technical Decisions #6). `trade_group.status` already covers open/closed.
- **Automatic fill→group assignment in ngv-trader.** ngv already tags every staged order's
  IBKR `orderRef` with `tg-{trade_group_id}` (Key Technical Decision #8), so fills carry the
  correlation on arrival. Having ngv-trader's fill ingestion
  (`src/services/trade_sync_tws.py`) recognize that `orderRef` prefix and auto-populate
  `trade_group_live_executions` / `trade_group_executions` is the natural follow-up; v1
  still supports manual assignment via the existing endpoints. (The `orderRef` _tagging_
  itself is not deferred — it ships with Layer 2.)
- **UI in the ngv-trader frontend** to display/edit tickets. API-first; frontend later.

---

## Key Technical Decisions

1. **Separate 1:1 table (`trade_group_orders`), not columns on `trade_groups` and not
   reusing `saved_structures`.** Keeps the busy `trade_groups` table and its large router
   untouched; mirrors the proven `saved_structures.legs` JSON pattern; avoids conflating
   the option-pricing structure schema (`saved_structures`, whose legs are
   strike/dte/iv-shaped) with a futures order-ticket. One nullable ticket per group.

2. **No execution details stored.** Per the user directive, the ticket omits tick, point
   value, exchange, currency, limit, pct, accounts, and lots. These are resolved in ngv at
   stage time (instrument reference + run params). This is the load-bearing boundary of
   the whole design.

3. **`legs` as a JSON array**, mirroring `saved_structures.legs`
   (`src/models.py` `SavedStructure.legs: Mapped[list] = mapped_column(JSON)`). Documented
   leg schema: `{action, ratio, code, con_id?}`. `code` is the compact SeasonAlgo-style
   contract label (e.g. `HEJ27`); `con_id` is an optional identity link to the existing
   `contracts` table.

4. **`spread_type` stored and validated (intra | inter).** Derivable from the distinct
   alpha-prefix roots of the leg `code`s, but stored for cheap querying/filtering and
   display. Validation extracts the leading letters of each `code` (regex, no month-code
   knowledge) and checks: `intra` ⇒ exactly one distinct root; `inter` ⇒ two or more.

5. **`direction` stored; legs always the "To Buy this spread" side.** Matches how
   SeasonAlgo presents both sides from one definition. ngv flips legs at stage time when
   `direction == "SELL"`, so the stored record always matches the popup's "To Buy" rows.

6. **API shape: order as a sub-resource of a trade group.** `GET /trade-groups/{id}`
   returns `order` (nullable); `PUT /trade-groups/{id}/order` upserts; `POST /trade-groups`
   accepts an optional `order`; `DELETE /trade-groups/{id}/order` removes it. Reuses the
   existing `trade_groups` router and the "attach to trade group" decision.

7. **Light validation only.** ngv-trader validates ticket _shape_ and `spread_type`
   consistency. It does **not** parse contract months, resolve expiries, or qualify conIds
   — that is Layer 2's job. This keeps contract/execution knowledge out of the back office.

8. **Order correlation via IBKR `orderRef`.** When ngv stages an order it sets the IBKR
   `orderRef` to `tg-{trade_group_id}` so the trade-group linkage is recorded **on the IBKR
   order itself** and propagates to every execution report/fill. This is set by **ngv at
   stage time** (an execution action) and is therefore _not_ a stored ticket field — but
   the _convention_ is part of the cross-repo contract, because ngv-trader's fill ingestion
   can parse that `orderRef` to auto-assign fills to the group. The `tg-` prefix is chosen
   to avoid collision with the existing `ngtrader-order-{id}` convention in
   `scripts/work_order_queue.py` (`make_order_ref`). The `trade_group_id` is already known
   to ngv (it is how the ticket was fetched), so no new field crosses the wire.

---

## Integration Contract (the `order` JSON)

> This illustrates the intended cross-repo contract and is directional guidance for review,
> not implementation specification. The implementing agent should treat the field set as
> the contract and the exact serialization as adjustable.

The `order` object embedded in a trade group's read model and accepted by the upsert
endpoint. This is the **only** shared surface between ngv-trader and ngv.

```jsonc
{
  "spread_type": "intra", // "intra" | "inter"
  "direction": "SELL", // "BUY" | "SELL" (which side of the SeasonAlgo popup)
  "legs": [
    // always the "To Buy this spread" definition
    { "action": "BUY", "ratio": 1, "code": "HEJ27", "con_id": 123456789 },
    { "action": "SELL", "ratio": 1, "code": "HEM27", "con_id": 234567890 },
  ],
  "label": "HEJ27-HEM27 Apr/Jun calendar", // human/SeasonAlgo spread name
  "source": "seasonalgo",
  "fnd": "2027-04-14", // first notice day (contract/risk fact), nullable
  "note": "", // optional freeform
}
```

Intra example (butterfly, ratios 1/2/1): three legs, one root (`ZM`). Inter example
(`ZCH27`/`ZWH27`): two legs, two roots (`ZC`, `ZW`), `spread_type: "inter"`. Note there is
**no** `tick`, `point_value`, `exchange`, `limit`, `pct`, or `accounts` anywhere in the
contract — by design.

**Leg schema:** `action ∈ {BUY, SELL}`, `ratio` a positive integer, `code` a non-empty
contract label string, `con_id` an optional integer.

---

## System-Wide Impact

- **Database:** one new table (`trade_group_orders`), FK to `trade_groups` with
  `ON DELETE CASCADE`. No changes to existing tables.
- **API:** additive changes to the `trade_groups` router and its read model. No breaking
  changes to existing trade-group endpoints (the `order` field is nullable/optional).
- **Frontend (ngv-trader):** unaffected in v1 (the React app reads trade groups but will
  simply ignore the new nullable `order` field until a later UI unit).
- **ngv repo (Layer 2):** gains a consumer of the new contract. Not modified by this plan;
  see the awareness section below.
- **Agents:** the screenshot→ticket agent gains a concrete POST target.

---

## Implementation Units (Layer 1 — ngv-trader)

### U1. Migration: `trade_group_orders` table

**Goal:** Create the 1:1 order-ticket table.

**Requirements:** Key Technical Decisions #1, #2, #3.

**Dependencies:** none (current alembic head is `936d0e0f325f`; new revision chains from
it).

**Files:**

- `alembic/versions/<ts>_add_trade_group_orders.py` (new)

**Approach:** Follow the existing migration style
(`alembic/versions/20260623120000_add_trade_group_live_executions.py`). Columns:

| column           | type                                                          | notes                                     |
| ---------------- | ------------------------------------------------------------- | ----------------------------------------- |
| `id`             | Integer PK, autoincrement                                     |                                           |
| `trade_group_id` | Integer, FK→`trade_groups.id` `ON DELETE CASCADE`, **unique** | enforces 1:1                              |
| `spread_type`    | Text, not null                                                | `intra` \| `inter` (CHECK constraint)     |
| `direction`      | Text, not null                                                | `BUY` \| `SELL` (CHECK constraint)        |
| `legs`           | JSON, not null                                                | array of `{action, ratio, code, con_id?}` |
| `label`          | Text, nullable                                                |                                           |
| `source`         | Text, nullable                                                | e.g. `seasonalgo`                         |
| `fnd`            | Date, nullable                                                | first notice day                          |
| `note`           | Text, nullable                                                |                                           |
| `created_at`     | DateTime(tz), not null                                        |                                           |
| `updated_at`     | DateTime(tz), not null                                        |                                           |

Add `UniqueConstraint("trade_group_id", name="uq_trade_group_orders_trade_group_id")` and
an index on `trade_group_id`. Include CHECK constraints for `spread_type` and `direction`
mirroring the `trade_groups.status` CHECK convention. Provide a matching `downgrade()` that
drops the index and table.

**Patterns to follow:** `alembic/versions/20260623120000_add_trade_group_live_executions.py`
(table + FK CASCADE + unique + index + downgrade).

**Test scenarios:**

- Migration `upgrade()` then `downgrade()` round-trips cleanly on a scratch DB (no
  orphaned constraints/indexes). _(verified via the smoke path in U5, not a unit test)_
- Test expectation: none for business logic — this unit is schema only; behavior is
  exercised through U2/U4 tests.

**Verification:** `alembic upgrade head` creates the table with the unique 1:1 constraint
and CHECKs; `alembic downgrade -1` removes it.

---

### U2. ORM model: `TradeGroupOrder` + relationship

**Goal:** Map the table and expose it from `TradeGroup`.

**Requirements:** Key Technical Decisions #1, #3.

**Dependencies:** U1.

**Files:**

- `src/models.py` (add `TradeGroupOrder`, add relationship on `TradeGroup`)

**Approach:** Mirror `SavedStructure` and `TradeGroup` mapping style (`Mapped[...] =
mapped_column(...)`, `JSON` for `legs`, tz-aware `created_at`/`updated_at` with
`default=lambda: datetime.now(timezone.utc)`). Add a `TradeGroup.order` relationship
(`uselist=False`, `cascade="all, delete-orphan"`) so the read model can embed it with one
attribute access. Keep `legs: Mapped[list] = mapped_column(JSON, nullable=False)`.

**Patterns to follow:** `src/models.py` `SavedStructure` (JSON legs) and `TradeGroup`
(timestamps, Text columns).

**Test scenarios:**

- Creating a `TradeGroupOrder` and reading it back through `TradeGroup.order` returns the
  same legs/direction/spread_type (integration scenario, exercised in U5).
- Deleting a `TradeGroup` cascades to its order (no orphan row).
- Test expectation: covered by U5 smoke path (no standalone model unit test needed given
  the repo has no ORM-level test harness).

**Verification:** In a REPL/smoke script, `db.get(TradeGroup, id).order` returns the mapped
ticket; deleting the group removes the ticket row.

---

### U3. Pydantic schemas + validation helpers

**Goal:** Define request/response models for the `order` object and validate shape +
`spread_type` consistency.

**Requirements:** Key Technical Decisions #3, #4, #7; Integration Contract.

**Dependencies:** none (pure schema; can land before U4 wires it).

**Files:**

- `src/api/routers/trade_groups.py` (add `LegModel`, `OrderTicket` request/response models
  and a `validate_ticket` helper), or a small `src/api/schemas/trade_group_order.py` if the
  router prefers separation — follow whatever the existing `trade_groups.py` does for its
  models.

**Approach:** Define:

- `LegModel`: `action: Literal["BUY","SELL"]`, `ratio: PositiveInt`, `code: str`
  (non-empty), `con_id: int | None = None`.
- `OrderTicket`: `spread_type: Literal["intra","inter"]`, `direction:
Literal["BUY","SELL"]`, `legs: list[LegModel]` (min length 1), `label: str | None`,
  `source: str | None`, `fnd: date | None`, `note: str | None`.
- `validate_ticket(ticket)`: derive each leg's root via a leading-alpha regex
  (`^[A-Za-z]+`), then assert `spread_type == "intra"` ⇒ exactly one distinct root, and
  `spread_type == "inter"` ⇒ ≥2 distinct roots. Raise `HTTPException(422)` on mismatch.
  **Do not** parse month codes, expiries, or resolve conIds.

**Patterns to follow:** `src/api/routers/structures.py` (Pydantic `BaseModel`,
`from_attributes`, `response_model`); use `Literal`/`PositiveInt` for cheap validation.

**Technical design (directional, not implementation spec):**

```
root(code)      = re.match(r"^[A-Za-z]+", code).group()      # "HEJ27" -> "HE", "ZCH27" -> "ZC"
roots           = { root(l.code) for l in legs }
intra  valid iff len(roots) == 1
inter  valid iff len(roots) >= 2
```

**Test scenarios:**

- Happy path: a valid intra ticket (all `HE`) and a valid inter ticket (`ZC`+`ZW`) pass
  validation.
- Edge: butterfly with ratios 1/2/1, one root, `spread_type: intra` passes.
- Error: `spread_type: intra` but legs have two roots → 422.
- Error: `spread_type: inter` but legs share one root → 422.
- Error: empty `legs` → 422; `ratio: 0` or negative → 422; `action: "HOLD"` → 422.

**Verification:** Unit-level assertions on `validate_ticket` and Pydantic parsing reject
the malformed cases and accept the valid ones.

---

### U4. Router endpoints: embed / upsert / create-with / delete

**Goal:** Wire the ticket into the trade-groups API.

**Requirements:** Key Technical Decisions #6; Integration Contract; System-Wide Impact.

**Dependencies:** U2, U3.

**Files:**

- `src/api/routers/trade_groups.py` (extend read model + add endpoints)

**Approach:**

- Add `order: OrderTicket | None` to the trade-group **read/response** model so
  `GET /trade-groups/{id}` (and optionally the list endpoint) embeds it.
- `PUT /api/v1/trade-groups/{id}/order`: validate via U3, upsert the single
  `TradeGroupOrder` row (create if absent, else overwrite fields + bump `updated_at`),
  return the stored ticket. 404 if the group doesn't exist.
- `POST /api/v1/trade-groups`: accept an optional `order` in the body; when present,
  validate and create the ticket in the same transaction as the group.
- `DELETE /api/v1/trade-groups/{id}/order`: remove the ticket (204); 404 if absent.
- Preserve all existing trade-group endpoints unchanged; `order` is additive/nullable.

**Patterns to follow:** `src/api/routers/structures.py` for the create/upsert/delete shape
and `get_db` dependency; existing `trade_groups.py` router conventions for response models
and error handling. Register nothing new in `main.py` — the router is already mounted
(`app.include_router(trade_groups.router, ...)`).

**Test scenarios:**

- Happy path: `PUT /trade-groups/{id}/order` on an existing group creates the ticket;
  `GET /trade-groups/{id}` returns it verbatim (legs/direction/spread_type/label/fnd).
- Upsert: a second `PUT` overwrites legs/limit-free fields and bumps `updated_at`, still
  one row (1:1 preserved).
- Create-with: `POST /trade-groups` with an `order` creates group + ticket atomically;
  without `order`, creates a group whose `order` is `null`.
- Delete: `DELETE /trade-groups/{id}/order` removes it; subsequent `GET` shows `order:
null`; deleting again → 404.
- Error: `PUT`/`POST` with an invalid ticket (spread_type/leg errors from U3) → 422 and no
  row written.
- Error: `PUT /trade-groups/{missing}/order` → 404.
- Integration: deleting the trade group cascades and removes the ticket row (no orphan).

**Verification:** The full create→read→update→delete cycle behaves as above against a test
DB; existing trade-group endpoints still pass.

---

### U5. Verification harness (smoke tests)

**Goal:** Provide runnable verification for the new endpoints, matching repo conventions.

**Requirements:** Plan Quality Bar (test coverage); U1–U4.

**Dependencies:** U4.

**Files:**

- `scripts/test_trade_group_orders_api.py` (new smoke script), **or** `tests/api/
test_trade_group_orders.py` if adopting pytest (see Approach)

**Approach:** The repo currently has **no pytest harness** (dev deps are `ruff`, `typer`,
`ipdb`; existing `scripts/test_*.py` are ad-hoc runnable scripts). Two options, pick at
execution time:

- **Preferred (matches convention):** a `scripts/test_trade_group_orders_api.py` that spins
  up `TestClient(app)` against a transactional test DB (or a disposable schema), exercises
  the create→read→update→delete cycle and the 422/404 cases, and prints pass/fail — same
  spirit as `scripts/test_activated_products.py`.
- **If adopting pytest:** add `pytest` + `httpx` to the `dev` dependency group and place the
  same scenarios under `tests/api/`. Slightly more setup; better long-term ergonomics.

Enumerate the U3 and U4 scenarios as the cases. This is the one place the plan introduces a
choice of harness; the _scenarios_ are fixed, the _mechanism_ is an execution-time decision.

**Execution note:** Write the create→read→update→delete happy-path check first so the
endpoints are exercised end-to-end before the error-path cases are filled in.

**Test scenarios:** (the concrete cases enumerated in U3 and U4, run as the smoke suite)

**Verification:** Running the script/suite reports all U3+U4 scenarios passing against a
scratch DB.

---

## Layer 2 — ngv execution consumer (awareness only; NOT ngv-trader's responsibility)

> **Target repo: `ngv` (separate).** This section exists so ngv-trader implementers
> understand the contract's downstream consumer and do not accidentally pull execution
> concerns into the back office. No work here is part of this plan's ngv-trader units.
> Paths below are relative to the `ngv` repo.

**Responsibility split:** ngv-trader answers _"what is the trade?"_ (the ticket). ngv
answers _"how do we stage it?"_ (routing, tick rounding, pricing, accounts, lots).

**High-level flow:**

1. **Fetch** — a notebook calls `GET /api/v1/trade-groups/{id}` on ngv-trader and reads the
   nullable `order` ticket (the Integration Contract JSON).
2. **Merge with instrument facts** — ngv owns a static **instrument reference** keyed by
   root symbol that supplies the execution facts ngv-trader deliberately omits:
   `{exchange, currency, tick, point_value}` for `HE`, `HG`, `ZM`, `KE`, `ZC`, `ZW`, …
   (`src/ngv/vol/execution/instruments.py`, new).
3. **Build a `SpreadSpec`** — `SpreadSpec.from_ticket(ticket, INSTRUMENTS)`
   (`src/ngv/vol/execution/ibkr_stage.py`, existing engine) joins the ticket's
   legs/direction/spread_type with the resolved instrument facts. It asserts intra tickets
   resolve to one instrument and inter tickets to ≥2, and prefers each leg's `con_id` (from
   the ticket) over month-code qualification when present.
4. **Stage** — `stage(ib, spec, trade_group_id, accounts=..., limit=..., pct=...)` places
   one `transmit=False` IBKR BAG order per account for the desk to review and Transmit,
   **setting each order's `orderRef` to `tg-{trade_group_id}`** so the trade-group linkage
   is logged on the IBKR order and every resulting fill. All of `accounts`, `limit`, `pct`
   are ngv-side run params, never stored in ngv-trader; `trade_group_id` is already known
   from the fetch in step 1.

**Medium-level notes ngv-trader implementers should be aware of:**

- **The `order` JSON is the entire contract.** If ngv-trader ever changes leg field names
  or the `spread_type`/`direction` vocabularies, ngv's `from_ticket` breaks. Keep the
  contract in this doc authoritative; version it if it must change.
- **`orderRef = tg-{trade_group_id}` is the fill-side handshake.** ngv stamps it on every
  staged order (Key Technical Decision #8). It rides on the IBKR order and each execution
  report, so ngv-trader's existing fill sync can later parse the `tg-` prefix to
  auto-assign fills to the right group — the pre-trade ticket and the post-trade
  `trade_group_executions` become two ends of the same correlation key. ngv-trader stores
  no execution mechanics to make this work; it only reads a string it already ingests
  (`order_ref` on `trades`). Keep the `tg-` prefix stable and distinct from
  `ngtrader-order-`.
- **`con_id` is the precise handshake.** When the screenshot→ticket agent resolves conIds
  against ngv-trader's `contracts` table and stores them on the legs, ngv can stage the
  exact instrument and skip IBKR re-qualification. When absent, ngv falls back to parsing
  `code` (e.g. `HEJ27` → HE/Apr/2027) via its own month-code map.
- **The punted tick/point-value granularity question lives here, not in the ticket.** For
  inter-commodity spreads whose legs differ per product, ngv's instrument reference resolves
  per-leg facts and picks a single net-limit rounding tick at stage time. ngv-trader stores
  none of it, so the question never touches the back office.
- **Inter-commodity BAGs** may not receive a native IBKR margin offset and can occasionally
  be rejected as a single combo; that is an ngv/TWS execution concern, invisible to the
  ticket.
- **ngv-trader's own order queue is single-leg and disabled** (`scripts/work_order_queue.py`
  raises before `placeOrder`), so there is no duplicate combo-execution path to reconcile —
  ngv is the only combo-staging surface today.

---

## Risks & Mitigations

- **Cross-repo contract drift.** ngv silently breaks if the `order` shape changes.
  _Mitigation:_ this doc is the single source of truth for the contract; treat field
  renames as breaking and coordinate a version bump; U5 asserts the exact serialized shape.
- **Back-office scope creep.** Pressure to add `tick`/`limit`/`accounts` "just to be
  handy" would violate the core boundary. _Mitigation:_ Key Technical Decision #2 and Scope
  Boundaries make the omission explicit and load-bearing; reviewers should reject execution
  fields in the ticket.
- **Validation over-reach.** Parsing month codes/expiries in ngv-trader would import
  contract knowledge the back office shouldn't own. _Mitigation:_ U3 restricts validation to
  shape + root-count; deep validation is Layer 2's job.
- **No existing test harness.** _Mitigation:_ U5 offers a convention-matching smoke script
  with an optional pytest upgrade path; scenarios are fixed regardless of mechanism.
- **1:1 assumption.** A group might later want multiple tickets (e.g. a roll). _Mitigation:_
  the unique constraint is easy to drop later; v1 keeps 1:1 for simplicity and matches the
  "one trade group = one idea" mental model.

---

## Sequencing

`U1 → U2 → {U3 in parallel} → U4 → U5`. U3 (schemas/validation) has no DB dependency and can
be written alongside U1/U2; U4 needs U2 (model) and U3 (schemas); U5 needs U4.
