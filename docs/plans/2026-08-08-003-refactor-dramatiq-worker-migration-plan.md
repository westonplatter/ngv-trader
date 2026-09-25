---
title: "refactor: Migrate the background job worker to Dramatiq (dramatiq-pg broker)"
type: refactor
status: proposed
created: 2026-08-08
updated: 2026-09-25
---

# refactor: Migrate the background job worker to Dramatiq (dramatiq-pg broker)

> **Status: PROPOSED.** Design/rationale for moving the `worker:jobs` dispatch
> loop onto Dramatiq with a **Postgres broker (`dramatiq-pg`)**, preserving every
> current job behavior and adding **proactive per-token FlexQuery rate limiting**.
> Nothing here is implemented yet. Current-state reference:
> [docs/workers.md](../workers.md).

## Summary

Today `worker:jobs` is a single-process Postgres-polling loop
(`scripts/work_jobs.py` + `src/workers/jobs.py` + queue primitive
`src/services/jobs.py`). It claims one `jobs` row at a time with **no row-level
lock** (safe only because there is exactly one worker), dispatches by `job_type`
through `get_handler`, and models retries/deferral by mutating the row's
`status`/`available_at`/`attempts`.

This plan moves dispatch onto **Dramatiq** using **`dramatiq-pg` (Postgres as the
broker)** — **no Redis, no new infrastructure.** The wedge: keep `enqueue_job`
writing the `Job` row exactly as today, and add one generic actor
`run_job(job_id)` that loads the row and calls the existing `get_handler`
dispatch table. Dramatiq replaces only the poll/claim/retry loop. The `Job` table
stays the UI/history source of truth.

It also adds a **per-token FlexQuery request budget** (e.g. token 1 = 10 req/min,
token 2 = 100 req/min) enforced in the domain layer against Postgres — same code,
per-token limits driven by data — reusing the existing `JobDeferred` deferral
path.

### Decisions (locked)

- **Broker: `dramatiq-pg`** (Postgres). Redis was considered and declined — the
  only reasons for it (Dramatiq's Prometheus middleware, `dramatiq-dashboard`,
  Redis-backed rate limiter) are out of scope. One datastore.
- **Retry authority stays `fail_or_retry_job`.** Dramatiq's `Retries` middleware
  is set to a no-op; `Job.max_attempts` + `attempts`/`last_error` remain the sole
  retry record. No double-counting.
- **No Prometheus/Grafana, no dashboard.** Observability stays exactly as today:
  `worker_heartbeats` lights + `Job.result`/`last_error` + SSE.
- **Rate limiting is a Postgres domain throttle**, not Dramatiq's rate limiter
  (which has no Postgres backend). Broker-agnostic, transactional with token
  state.

Scope is the **jobs** worker only. `worker:orders` (separate table, persistent
TWS connection, submission disabled) is explicitly out of scope.

---

## Problem Frame

- **No locking on claim.** `claim_next_job` (`src/services/jobs.py:119`) does
  `SELECT ... WHERE status='queued' ... LIMIT 1` then flips to `running` — no
  `FOR UPDATE SKIP LOCKED`. Correct only for a single worker.
- **Hand-rolled delivery.** Retry/backoff, delayed visibility, dedup, and the
  poll loop are all bespoke in `src/services/jobs.py`.
- **No proactive throttle.** FlexQuery back-off is **reactive only**: it pauses a
  token 20 min *after* IBKR returns error `1025` (`pause_token` in
  `src/services/flex_credentials.py`). There is no per-token "N requests/minute"
  budget, so nothing prevents hammering a token into the 1025 lockout.
- **Constraint: keep blast radius small.** 18 registered handlers, a load-bearing
  3-phase FlexQuery flow, the `/jobs` API, SSE topics, and two frontend
  components all depend on current `Job` semantics. The migration must not
  disturb them.

## What must be preserved (behavioral contract)

1. **All 18 registered job types** dispatch identically (`src/workers/jobs.py`
   `get_handler`), the two dormant TWS handlers staying dormant.
2. **The 3-phase FlexQuery flow** — `*.sync.flexquery` fan-out →
   `*.initiate_request` → `*.fetch_report` re-check polling — including token
   pause and rate-limit (1025) handling.
3. **`JobDeferred` semantics**: "not ready, re-check in N seconds" **without
   spending a retry attempt**. Drives the poll loop and the UI's `deferred` badge.
4. **The UI `deferred` state**: `JobsTable.tsx` synthesizes `deferred` from a
   `queued` row whose `available_at` is in the future. That meaning is preserved.
5. **`enqueue_job` / `enqueue_job_if_idle`** call sites keep their signatures.
6. **`/api/v1/jobs`** (list/get/rerun/archive) and **SSE** unchanged.
7. **Worker heartbeat lights** keep working — the Dramatiq worker emits
   heartbeats for `worker_type="jobs"`.
8. **`Job.max_attempts`** per-row retry cap still governs failure→retry→failed.
9. **At-least-once delivery is acceptable** — handlers are idempotent (upserts);
   the actor reloads the row and short-circuits on terminal status.

## Core design: the thin wedge

**One generic actor, `Job` row stays authoritative.**

```
enqueue_job(session, job_type, payload, ...)   # unchanged: writes queued Job row
    └─ after commit: run_job.send(job.id)        # NEW: hand job.id to Dramatiq
```

```python
@dramatiq.actor(queue_name="default", max_retries=0)   # Retries no-op; row owns retry
def run_job(job_id: int) -> None:
    # load Job by id in its own Session
    # if status not in (queued, running): return        # idempotent redelivery guard
    # mark running + heartbeat + SSE                     # existing helpers
    handler = get_handler(job.job_type)
    try:
        result = handler(job, engine, ib_pool)
        complete_job(...)                                # existing helper
    except JobDeferred as d:
        defer_job(...)                                   # re-queue, future available_at, no attempt
        run_job.send_with_options(args=(job_id,), delay=d.retry_after_seconds * 1000)
    except Exception as e:
        fail_or_retry_job(...)                           # increments attempts; failed at cap
        if not terminal: run_job.send_with_options(args=(job_id,), delay=retry_delay * 1000)
    finally:
        fire SSE notify + coarse notify                  # existing _notify_* helpers
```

Why this shape:

- **Handlers, `Job` model, API, SSE, frontend all untouched.** Dramatiq only
  replaces the claim/poll loop in `scripts/work_jobs.py`.
- **Deferral maps cleanly.** `JobDeferred` → ack current message + send a fresh
  delayed message. "Waiting" (new delayed message, no attempt) stays physically
  distinct from "failed attempt". `available_at` still drives the UI badge.
- **Retries stay with the row.** Actor `max_retries=0`; `fail_or_retry_job` is the
  only counter. One owner, no double-count.
- **Idempotent redelivery.** Crash after `send`, before ack → Dramatiq redelivers
  `run_job(job_id)`; the actor reloads, sees terminal/mismatched status, returns.
- **Fan-out is just more sends.** `_fan_out_flexquery` /
  `_initiate_flexquery_request` already `enqueue_job` children; each now also
  `run_job.send`s. No Dramatiq pipelines/groups needed for parity.

## Per-token FlexQuery rate limiting

Goal: same code, per-token budgets driven by data — e.g. token 1 = 10 req/min,
token 2 = 100 req/min — enforced correctly across any number of worker
processes/threads. This is **proactive** (gate before the IBKR call), on top of
the existing **reactive** 1025 pause.

Design — a Postgres domain throttle (not Dramatiq's rate limiter, which is
Redis/Memcached-only):

1. **Limit as data.** Add `max_requests_per_minute` (Integer, nullable = no cap)
   to `flexquery_tokens`. Seed per token (10, 100) via
   `scripts/manage_flex_tokens.py` or the migration.
2. **Shared counter.** A rolling-window table
   `flex_token_request_log(id, token_id, requested_at)` indexed on
   `(token_id, requested_at)`. (Token-bucket columns on the row are an
   alternative; the window log maps most directly to "N per minute".)
3. **Reservation helper** in `src/services/flex_credentials.py`:
   `reserve_token_request(engine, token_id) -> ok | Throttled(retry_after)`. In
   one transaction, `SELECT ... FOR UPDATE` the token row, count log rows newer
   than `now - 60s`; if `>= max_requests_per_minute` return
   `Throttled(retry_after = 60 - age_of_oldest_in_window)`; else insert a log row
   and return `ok`. Prune rows older than the window opportunistically.
4. **Gate the IBKR calls.** In `_initiate_flexquery_request` and the
   `_collect_flexquery_report` re-check, before each outbound Flex call:
   `reserve_token_request`; on `Throttled` → `raise JobDeferred(retry_after)`.
   Coexists with the existing `paused_until` (1025) check.

Notes:
- The Postgres row-lock makes this correct across all Dramatiq workers — exactly
  why `dramatiq-pg` (no Redis) is sufficient. Contention at 10/100 rpm over 2
  tokens is negligible.
- **Open detail:** confirm whether the budget should count only `initiate`
  requests or every outbound Flex call (initiate + each fetch poll). Default:
  count every outbound call, since each consumes IBKR quota.

## Concept mapping

| Today | Dramatiq (`dramatiq-pg`) target |
|---|---|
| `jobs` table poll loop | `run_job` actor on a Postgres broker; `jobs` row = history/UI projection |
| `claim_next_job` (no lock) | Broker delivery — one consumer per message, no manual claim |
| `work_jobs.py` `while True` | `dramatiq src.workers.dramatiq_app` CLI (`--queues`, `--threads`) |
| `fail_or_retry_job` + `available_at` | **Kept as sole retry authority**; Dramatiq `Retries` = no-op |
| `JobDeferred` + `defer_job` | `send_with_options(delay=…)` re-send + `defer_job` row update |
| `enqueue_job_if_idle` dedup | Same DB idle-guard, then conditional `send` |
| Single process ⇒ safe TWS client-ids 31–41 | Dedicated `tws` queue pinned to 1 consumer thread |
| reactive 1025 `pause_token` only | Keep it **and** add proactive per-token `max_requests_per_minute` gate |
| broker infra | **None new** — reuse Postgres via `dramatiq-pg` |

## New / changed files (anticipated)

- `src/workers/dramatiq_app.py` — **new.** `dramatiq-pg` `PostgresBroker`,
  middleware (`Retries` no-op, a `HeartbeatMiddleware`), and the `run_job` actor
  reusing `get_handler` + `IBSessionPool` + existing job/SSE helpers.
- `src/services/jobs.py` — add optional post-commit `run_job.send(job.id)` behind
  a `WORKER_BACKEND` flag (`legacy` | `dramatiq`). No signature changes.
- `src/services/flex_credentials.py` — add `reserve_token_request`; extend
  `FlexCredential` with the per-token limit.
- `scripts/work_jobs.py` — kept for `legacy` during dual-run; retired at cutover.
- `alembic/versions/…` — (a) fold `dramatiq-pg`'s `schema.sql` into a migration
  (do **not** run `dramatiq-pg init`); (b) `max_requests_per_minute` column +
  `flex_token_request_log` table + seed values.
- `pyproject.toml` — add `dramatiq` + `dramatiq-pg` under the 14-day cooldown.
- `Taskfile.yaml` — point `worker:jobs` at the `dramatiq` CLI.
- `docs/workers.md` — rewrite the jobs-worker section for the Dramatiq model.
- `env` files — `WORKER_BACKEND` (broker URL reuses the existing `DB_*`).
- `tests/` — `StubBroker` actor tests + rate-limit throttle tests.

## Phased implementation

**Phase 0 — compat spike + deps (~½ day).**
- Spike the `dramatiq` + `dramatiq-pg` version pairing against a scratch Postgres
  (Dalibo `dramatiq-pg` 0.12.0 historically targets Dramatiq 1.x; a 2.x-capable
  fork exists). Pin the combination that imports and round-trips a message; that
  fixes the Dramatiq major version.
- `uv add dramatiq dramatiq-pg --exclude-newer "$(date -u -d '14 days ago' +%Y-%m-%d)"`;
  note cooldown + release dates in the PR.
- Fold `dramatiq-pg`'s schema into an Alembic migration
  (`task migrate:new -- "add dramatiq-pg broker schema"`).

**Phase 1 — dispatch wedge behind a flag (~1–2 days).**
- Build `src/workers/dramatiq_app.py` + `run_job` actor + heartbeat middleware.
- `enqueue_job` sends to Dramatiq only when `WORKER_BACKEND=dramatiq`; else legacy
  loop runs. Split job types across `default` (scalable) and `tws` (1 consumer).
- `StubBroker` unit tests: dispatch-by-`job_type`, `JobDeferred`→delayed re-send
  (no attempt), exception→`fail_or_retry_job`→cap→`failed`, redelivery guard.
- Dev parity pass over all 18 job types, focus on the 3-phase FlexQuery flow.

**Phase 2 — per-token rate limiting (~1 day).**
- Migration: `max_requests_per_minute` + `flex_token_request_log` + seed (10/100).
- `reserve_token_request` helper; gate `initiate` + fetch re-check with
  `JobDeferred` on throttle.
- Tests with an injected clock: 11th call within a minute defers; per-token
  isolation; window frees after 60s.

**Phase 3 — cutover (~½ day).**
- Point prod `worker:jobs` at `dramatiq src.workers.dramatiq_app`. Start with a
  single `--threads 1` consumer for exact parity, then split into `default`
  (threads>1) + a separate `tws` worker (`--threads 1`) once verified.
- Flip `WORKER_BACKEND=dramatiq`, watch a cycle, retire `scripts/work_jobs.py`
  polling and the flag. Update `docs/workers.md`.

## Cutover & rollback

- **Dual-run flag** (`WORKER_BACKEND`) flips prod to Dramatiq and back with no
  code change. Rollback = set `legacy`, restart the polling worker; the `Job`
  table is unchanged so in-flight rows resume under either backend.
- At cutover, re-`send` any `queued` rows once so Dramatiq picks up the backlog
  (both backends read the same `Job` rows via `run_job(job_id)`).

## Testing

- `dramatiq.brokers.stub.StubBroker` + `dramatiq.testing` for actor unit tests
  (dispatch, deferral, retry-cap, redelivery guard). Broker defaults to Stub under
  pytest — no Postgres broker in CI beyond the existing test DB.
- Rate-limit tests with an injected clock (no real sleeps).
- Existing pytest canary suite (imports, migrations reach head, ORM round-trip,
  API health) still runs; the two new tables are covered by the migration-table
  check.

## Risks

- **`dramatiq-pg` / Dramatiq version fit.** Mitigate: Phase 0 spike pins a working
  pair before any integration code.
- **Broker schema outside Alembic.** `dramatiq-pg init` would create DDL directly,
  violating the migrations-only rule. Mitigate: fold `schema.sql` into a migration.
- **Delivery-vs-row consistency.** `send` after commit can be lost if the process
  dies in between. Mitigate: idempotent actor + a periodic sweeper that re-sends
  orphaned `queued` rows older than N seconds (reuses `available_at`).
- **TWS client-id collision** under concurrency. Mitigate: `tws` queue at 1
  consumer thread.

## Non-goals

- Migrating `worker:orders` or enabling order submission (see
  [docs/spec-worker-order-recovery.md](../spec-worker-order-recovery.md)).
- Adding a scheduler / recurring cron.
- Prometheus/Grafana, `dramatiq-dashboard`, or any Redis-backed feature.
- Changing the `Job` model, `/jobs` API, SSE contract, or frontend.
- Scaling TWS-bound work beyond a single consumer.

## Open questions

1. Rate-limit scope: count only `initiate` calls, or every outbound Flex call
   (initiate + each fetch poll)? (Default: every outbound call.)
2. Window store: rolling-window log table (recommended) vs token-bucket columns
   on the token row?
