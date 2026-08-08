---
title: "refactor: Migrate the background job worker to Dramatiq"
type: refactor
status: proposed
created: 2026-08-08
---

# refactor: Migrate the background job worker to Dramatiq

> **Status: PROPOSED.** Design/rationale for moving the `worker:jobs` dispatch
> loop onto Dramatiq while preserving every current job behavior. Nothing here
> is implemented yet. Current-state reference: [docs/workers.md](../workers.md).

## Summary

Today `worker:jobs` is a single-process Postgres-polling loop
(`scripts/work_jobs.py` + `src/workers/jobs.py` + queue primitive
`src/services/jobs.py`). It claims one `jobs` row at a time, dispatches by
`job_type` through `get_handler`, and models retries/deferral by mutating the
row's `status`/`available_at`/`attempts`. It works, but the claim has **no
row-level lock** (safe only because there is exactly one worker), there is **no
metrics surface**, and scaling means hand-rolling everything.

This plan moves dispatch onto **Dramatiq** (actor-based queue, Redis broker,
Prometheus middleware) **without rewriting the handlers, the `Job` model, the
job API, SSE, or the frontend.** The wedge: keep `enqueue_job` writing the
`Job` row exactly as today, and add one generic actor `run_job(job_id)` that
loads the row and calls the existing `get_handler` dispatch table. Dramatiq
replaces only the poll/claim/retry loop. The `Job` table stays the UI/history
source of truth; Dramatiq owns delivery and concurrency; Prometheus +
Grafana (and optionally `dramatiq-dashboard`) provide the metrics view.

Scope is the **jobs** worker only. `worker:orders` (separate table, persistent
TWS connection, submission disabled) is explicitly out of scope.

---

## Problem Frame

- **No locking on claim.** `claim_next_job` (`src/services/jobs.py:119`) does
  `SELECT ... WHERE status='queued' ... LIMIT 1` then flips to `running` — no
  `FOR UPDATE SKIP LOCKED`. Correct only for a single worker. Any horizontal
  scaling double-runs jobs today.
- **No metrics.** Observability is the `worker_heartbeats` row + `Job.result`/
  `last_error` + SSE. No run/queue/duration timing, no Prometheus, nothing to
  put on the dashboard the screenshot shows.
- **Hand-rolled everything.** Retry/backoff, delayed visibility, dedup, and the
  poll loop are all bespoke in `src/services/jobs.py`. A framework gives us
  battle-tested delivery, retries, and a middleware hook for metrics.
- **Constraint: keep blast radius small.** 18 registered handlers, a load-bearing
  3-phase FlexQuery flow, the `/jobs` API, SSE topics, and two frontend
  components all depend on current `Job` semantics. The migration must not
  disturb them.

## What must be preserved (behavioral contract)

1. **All 18 registered job types** dispatch identically (`src/workers/jobs.py`
   `get_handler`), including the two dormant TWS handlers staying dormant.
2. **The 3-phase FlexQuery flow** — `*.sync.flexquery` fan-out →
   `*.initiate_request` → `*.fetch_report` with re-check polling — keeps working,
   including token pause and rate-limit (1025) handling.
3. **`JobDeferred` semantics**: a handler can say "not ready, re-check in N
   seconds" **without spending a retry attempt**. This drives the FlexQuery poll
   loop and the UI's `deferred` badge.
4. **The UI `deferred` state**: `JobsTable.tsx` synthesizes `deferred` from a
   `queued` row whose `available_at` is in the future. Future-dated `available_at`
   must keep meaning "waiting."
5. **`enqueue_job` / `enqueue_job_if_idle`** call sites (API routers, tradebot
   agent, orders worker, internal fan-out) keep their signatures.
6. **`/api/v1/jobs`** (list/get/rerun/archive) and **SSE** (`job.created`,
   `job.updated`, `job.archived`, coarse trades/positions notifies) unchanged.
7. **Worker heartbeat lights** (`worker_heartbeats`, `GET /workers/status`,
   `WorkerStatusLights.tsx`) keep working — the Dramatiq worker must emit
   heartbeats for `worker_type="jobs"`.
8. **`Job.max_attempts`** per-row retry cap still governs failure→retry→failed.
9. **At-least-once is acceptable** because handlers are idempotent (upserts).
   The generic actor reloads the row and short-circuits on terminal status, so
   redelivery is safe.

## Core design: the thin wedge

**One generic actor, `Job` row stays authoritative.**

```
enqueue_job(session, job_type, payload, ...)   # unchanged: writes queued Job row
    └─ after commit: run_job.send(job.id)        # NEW: hand job.id to Dramatiq
```

```python
@dramatiq.actor(queue_name="default", max_retries=…, ...)
def run_job(job_id: int) -> None:
    # load Job by id in its own Session
    # if status != queued/running: return (idempotent redelivery guard)
    # mark running + heartbeat + SSE  (reuse existing helpers)
    handler = get_handler(job.job_type)
    try:
        result = handler(job, engine, ib_pool)
        complete_job(...)              # existing helper
    except JobDeferred as d:
        defer_job(...)                 # existing helper: re-queue, future available_at, no attempt
        run_job.send_with_options(args=(job_id,), delay=d.retry_after_seconds*1000)
    except Exception as e:
        fail_or_retry_job(...)         # existing helper: increments attempts, sets failed at cap
        if not terminal: run_job.send_with_options(args=(job_id,), delay=retry_delay*1000)
    finally:
        fire SSE notify + coarse notify (existing _notify_* helpers)
```

Why this shape:

- **Handlers, `Job` model, API, SSE, frontend all untouched.** Dramatiq only
  replaces the claim/poll loop in `scripts/work_jobs.py`.
- **Deferral maps cleanly.** `JobDeferred` → ack the current message + send a
  fresh delayed message. "Waiting" (new delayed message, no attempt) is
  physically distinct from "failed attempt" (Dramatiq/`fail_or_retry_job`
  backoff). `available_at` on the row still drives the UI badge.
- **Retries map cleanly.** We keep `Job.max_attempts` as the authority by
  driving retries through `fail_or_retry_job` + explicit delayed re-send, and set
  Dramatiq's own `max_retries=0` on the actor (or use it purely as a
  crash-safety net). Single retry owner = no double-counting.
- **Idempotent redelivery.** If the process dies after `send` but before ack,
  Dramatiq redelivers `run_job(job_id)`; the actor reloads the row, sees
  terminal/mismatched status, and returns.
- **Fan-out is just more sends.** `_fan_out_flexquery` and
  `_initiate_flexquery_request` already `enqueue_job` children; each now also
  `run_job.send`s. No Dramatiq pipelines/groups required for parity (they remain
  available later for explicit chaining).

## Concept mapping

| Today | Dramatiq target |
|---|---|
| Postgres `jobs` table poll | Redis broker + `run_job` actor; `jobs` row = history/UI projection |
| `claim_next_job` (no lock) | Broker delivery — exactly-one consumer per message, no manual claim |
| `work_jobs.py` `while True` loop | `dramatiq src.workers.dramatiq_app` CLI (`--processes`/`--threads`/`--queues`) |
| `fail_or_retry_job` + `available_at` | Kept as retry authority; Dramatiq `Retries` set to no-op or crash-net |
| `JobDeferred` + `defer_job` | `send_with_options(delay=…)` re-send + `defer_job` row update |
| `enqueue_job_if_idle` dedup | Same DB idle-guard, then conditional `send` |
| Single process ⇒ safe TWS client-ids 31–41 | Dedicated `tws` queue pinned to 1 worker / 1 thread (see below) |
| `worker_heartbeats` upsert in loop | Dramatiq middleware / periodic actor upserts heartbeat |
| none | Prometheus middleware (`:9191`) → Grafana; optional `dramatiq-dashboard` |

## Key decisions & tradeoffs

### Broker: Redis (recommended)
Matches the stated direction (Prometheus middleware, `dramatiq-dashboard`,
Grafana), is Dramatiq's best-supported broker, and is a single lightweight
service. **Cost: new infra** — Redis is not currently deployed (only Postgres +
TWS). Configure Redis persistence (AOF) so queued/delayed messages survive a
restart; the `Job` row is the durable record of intent regardless.

Alternatives considered:
- **RabbitMQ** — more delivery guarantees, heavier to run for a one-person desk.
  Overkill here.
- **`dramatiq-pg`** (Postgres broker) — zero new infra, reuses the existing DB.
  Viable fallback if adding Redis is unacceptable, but loses `dramatiq-dashboard`
  and is a smaller/less-maintained path. **Recommendation: Redis; keep
  `dramatiq-pg` as the documented no-new-infra escape hatch.**

### TWS concurrency & client-ids
`IBSessionPool` assumes one process owns TWS client-ids 31–41. Multiple Dramatiq
processes/threads would collide and hit TWS connection limits. Plan:
- Route every TWS-touching job type (`*.tws`, `order.fetch_sync`,
  `watchlist.quotes_refresh`, `contracts.*`) to a **`tws` queue** run by a
  worker with `--processes 1 --threads 1` — behavior-identical to today's single
  consumer.
- Route pure-HTTP/DB jobs (FlexQuery initiate/fetch, `market_data.*` via Flex,
  `watchlist.add_instrument`) to a scalable **`default` queue**.
- Derive client-id from worker/thread index if TWS is ever scaled past 1
  (future, out of scope).

### Retry ownership
Keep `Job.max_attempts` + `fail_or_retry_job` as the single retry authority
(preserves per-row caps and the `attempts`/`last_error` columns the UI reads).
Set the actor's Dramatiq `Retries` to not double-count — either `max_retries=0`
with our explicit delayed re-send, or a thin `retry_when` that defers to row
state. Decide during Phase 1; default is explicit re-send.

### Scheduling
None exists today (recurring syncs are UI/worker-chained). **Out of scope.** If
cron-style recurring syncs are wanted later, add `periodiq` or `apscheduler`
alongside Dramatiq — noted, not built here.

### Orders worker
`worker:orders` uses a different table, a persistent single TWS connection, and
startup reconciliation, with submission disabled — a poor fit for stateless
actors and largely dormant. **Left entirely as-is.** Its post-processing
`enqueue_job_if_idle` calls continue to work because `enqueue_job` is unchanged.

## New / changed files (anticipated)

- `src/workers/dramatiq_app.py` — **new.** Broker setup (Redis URL from env),
  middleware stack (`Retries` tuned, `Prometheus`, a `HeartbeatMiddleware`, SSE
  hook), and the `run_job` actor reusing `get_handler` + `IBSessionPool`.
- `src/services/jobs.py` — add an optional post-commit `run_job.send(job.id)`
  hook behind a `WORKER_BACKEND` flag (`legacy` | `dramatiq`). No signature
  changes to `enqueue_job`.
- `scripts/work_jobs.py` — keep for `legacy` backend during dual-run; retire at
  cutover.
- `src/services/worker_heartbeat.py` — reuse; called from Dramatiq middleware.
- `pyproject.toml` — add `dramatiq[redis]`, `prometheus-client` (and Redis
  client) honoring the **14-day cooldown** (`uv add … --exclude-newer`).
- `Taskfile.yaml` — point `worker:jobs` at `dramatiq src.workers.dramatiq_app
  --queues default tws …`; add a local-Redis target / compose note for dev.
- `docs/workers.md` — rewrite the jobs-worker section for the Dramatiq model.
- `env.example` / `.env.*` — `DRAMATIQ_BROKER_URL` / `REDIS_URL`,
  `WORKER_BACKEND`, Prometheus port.
- `tests/` — `StubBroker` actor tests for `run_job` dispatch, deferral→re-send,
  retry→cap, idempotent redelivery.

## Phased implementation

**Phase 0 — infra & deps.** Add `dramatiq[redis]` + `prometheus-client` (cooldown
noted in PR). Stand up Redis in dev (docker/compose snippet + `task` target).
Wire env vars. No behavior change.

**Phase 1 — dual-run behind a flag.** Build `src/workers/dramatiq_app.py` with
the `run_job` actor and middleware (Retries tuned, heartbeat, SSE, Prometheus).
`enqueue_job` sends to Dramatiq only when `WORKER_BACKEND=dramatiq`; otherwise
the legacy loop runs. Verify parity on every job type in dev, with special
attention to the 3-phase FlexQuery flow (initiate → deferred fetch re-checks →
sync), token pause, and rate-limit paths. StubBroker unit tests.

**Phase 2 — cutover.** Point prod `task worker:jobs` at the Dramatiq CLI with
`default` (scalable) + `tws` (concurrency 1) queues. Watch parity for a cycle.
Retire `scripts/work_jobs.py` polling and remove the `legacy` flag. Update
`docs/workers.md`.

**Phase 3 — observability.** Enable the Prometheus middleware endpoint; add a
Grafana dashboard JSON (run/queue/total timing to match the screenshot); wire a
scrape config. Optionally stand up `dramatiq-dashboard` for a queue view.

**Phase 4 — optional, later.** Scheduler (`periodiq`) for recurring syncs;
TWS-queue scale-out with per-worker client-ids; migrate `worker:orders` if/when
submission is productionized (see `docs/spec-worker-order-recovery.md`).

## Cutover & rollback

- **Dual-run flag** (`WORKER_BACKEND`) lets prod flip to Dramatiq and back
  without code changes. Rollback = set `legacy`, restart the polling worker; the
  `Job` table is unchanged so in-flight rows resume under either backend.
- **Draining:** at cutover, let the legacy loop finish queued rows or let
  Dramatiq pick them up (both read the same `Job` rows via `run_job(job_id)` —
  re-send any `queued` rows once on switch).

## Testing

- `dramatiq.brokers.stub.StubBroker` + `dramatiq.testing` for actor unit tests:
  dispatch-by-`job_type`, `JobDeferred`→delayed re-send (no attempt spent),
  exception→`fail_or_retry_job`→cap→`failed`, terminal-status redelivery guard.
- Existing pytest canary suite still runs (imports, migrations, API health) —
  Dramatiq broker defaults to Stub under test; no Redis in CI.
- Manual dev parity checklist across all 18 job types before Phase 2.

## Risks

- **Redis is new infra / a new SPOF.** Mitigate with AOF persistence; the `Job`
  row remains the durable intent record; `dramatiq-pg` is the documented
  fallback.
- **Dual retry owners.** If both Dramatiq `Retries` and `fail_or_retry_job`
  count, attempts double. Mitigate: one owner (explicit re-send), covered by a
  test.
- **TWS client-id collision** under any concurrency. Mitigate: `tws` queue at
  concurrency 1 for phase 1–3.
- **Delivery-vs-row consistency.** `send` after commit can be lost if the
  process dies in between. Mitigate: idempotent actor + a periodic "re-send
  orphaned `queued` rows older than N seconds" sweeper (cheap safety net; can
  reuse the existing `available_at` semantics).

## Non-goals

- Migrating `worker:orders` or enabling order submission.
- Adding a scheduler / recurring cron.
- Changing the `Job` model, `/jobs` API, SSE contract, or frontend.
- Scaling TWS-bound work beyond a single consumer.

## Open questions

1. Redis vs `dramatiq-pg` — confirm appetite for new infra. (Recommendation:
   Redis.)
2. Retry authority — keep `fail_or_retry_job` as sole owner (recommended) vs.
   hand retries to Dramatiq and reduce `Job` to pure history?
3. Do we want `dramatiq-dashboard` in addition to Grafana, or is Grafana enough?
4. Grafana/Prometheus hosting — where does the scrape target live given there is
   no container platform in-repo today?
