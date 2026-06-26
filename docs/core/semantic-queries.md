# Semantic Queries (OSI semantic layer)

> **Status: implemented.** This is the authoritative spec for the semantic layer
> that lets agents answer analytics questions (realized PnL, win rate,
> commissions, …) by selecting **metric and dimension names** — never by writing
> SQL. Read this before changing `osi/ngv_semantic_model.yaml`,
> `src/services/semantic/*`, the fact views, or the `query_metric` surfaces.

## 1. What it is and why

An [Open Semantic Interchange (OSI)](https://github.com/open-semantic-interchange/OSI)
model describes trading metrics and dimensions once; a resolver compiles a chosen
metric + dimensions + filters into a single parameterized, read-only `SELECT`.
Two surfaces drive it: the in-app tradebot `query_metric` tool, and a stdio MCP
server for external agents (e.g. Claude Code). Both share the same model and
resolver, so a metric is defined exactly once.

This is the Postgres analog of a **Snowflake semantic view** / Cortex Analyst
model. Postgres has no native `CREATE SEMANTIC VIEW`, so:

| Snowflake semantic view | Here |
| --- | --- |
| `TABLES` / `FACTS` (physical rows) | the `v_execution_facts` / `v_trade_facts` views + base tables |
| `RELATIONSHIPS` | `relationships:` in the YAML (the join graph) |
| `DIMENSIONS` + `METRICS` + `WITH SYNONYMS` | dataset `fields` with `dimension:`, `metrics:`, `ai_context.synonyms` |
| `SELECT … FROM SEMANTIC_VIEW(… DIMENSIONS … METRICS …)` | `build_metric_query()` in `resolver.py` |
| Cortex Analyst picking names | `query_metric` (tradebot tool + MCP), enumerated to the model |

The non-negotiable property is the same as Snowflake's: **agents reference named
metrics and dimensions; the engine writes the SQL.** Aggregation logic lives in
one place and the agent cannot get it wrong or inject SQL.

## 2. Core design decisions

### 2.1 Facts at their natural grain — never a pre-aggregated cube
Do **not** bake a `GROUP BY` into the fact view. Pre-aggregating freezes the grain
and forces every dimension to be a grouping column (a migration per dimension) —
the opposite of a semantic layer. Facts are defined at their natural grain and the
resolver aggregates at query time:

- **`v_execution_facts`** — one row per canonical execution (base grain). Home of
  additive measures (`realized_pnl`, `commission`).
- **`v_trade_facts`** — one row per trade (trade grain). Home of inherently
  trade-grain metrics (`trade_count`, `win_rate`) that can't be expressed as a
  flat aggregate over executions.

Each metric declares the `fact` (grain) it lives on. A query targets **one
grain**; dimensions come from joins, so adding one is free.

### 2.2 Conformed dimensions via relationships
Attributes are not denormalized into the fact. They live in dimension datasets
(`accounts`, `contracts`, `trade_groups`) reached through the relationship graph.
That's why `account` is the human **alias**, and why `contract_month` / `strike` /
`tag` slicing is possible. The resolver joins in only the datasets a query
references.

### 2.3 Grain enforcement
A dimension is valid for a metric only if its dataset is **reachable from the
metric's fact** in the directed relationship graph. Example: option `strike` lives
on `contracts`, reachable from `execution_facts` (a fill has one `con_id`) but not
from `trade_facts` (a spread trade spans multiple contracts → ambiguous). So
`win_rate by strike` is rejected with a message naming the valid dimensions. This
is intentional — it prevents silently-wrong rollups.

## 3. Components

| Path | Role |
| --- | --- |
| `osi/ngv_semantic_model.yaml` | the model: datasets, relationships, dimensions, metrics, synonyms |
| `alembic/versions/*_semantic_fact_views.py` | creates `v_execution_facts` + `v_trade_facts` |
| `src/services/semantic/loader.py` | parse + validate the model; the **allow-list**; graph helpers |
| `src/services/semantic/resolver.py` | `build_metric_query()` → one parameterized SELECT |
| `src/services/semantic/executor.py` | run read-only (own `READ ONLY` tx + `statement_timeout`), JSON-safe rows |
| `src/services/tradebot_agent.py` | `query_metric` tool (enums generated from the model) |
| `src/mcp/semantic_server.py` | stdio MCP server: `describe_semantic_model` + `query_metric` |

## 4. The resolver algorithm (`build_metric_query`)

```
1. metric  -> validate; fact = metric.fact
2. for each group_by / filter name:
     dim = resolve_dimension(fact, name)         # nearest dataset reachable from fact, fact-first
                                                 # raises (lists valid dims) if out of grain
     used_datasets.add(dim.dataset)
3. joins = minimal LEFT JOINs covering used_datasets, walked from `fact`
           over relationships in BFS order (from-side always emitted first)
4. SELECT <dim exprs [date_trunc if time+grain]>, <metric expr>
   FROM <fact.source> AS <fact>  <joins>
   [WHERE equality filters (bound) AND time-range on the fact's time dim]
   [GROUP BY dim exprs  ORDER BY metric DESC]  LIMIT :limit
```

All SQL fragments come from trusted model expressions (fully qualified with the
dataset name, matched by aliasing each source `AS <dataset>`). Every caller value
is a bound parameter — there is no string interpolation of values.

## 5. Invariants — keep these true

- **No free-form SQL.** The agent only supplies names (validated against the
  model) and values (bound). Never add a tool that accepts a SQL string.
- **Combo safety.** `realized_pnl` is `NULL` on synthetic `combo_summary` rows
  (legs carry the PnL); money metrics over executions must exclude
  `exec_role = 'combo_summary'` (see `total_commissions`, `fill_count`). The
  `trade_group_executions` bridge is **1:1** (`UNIQUE(trade_execution_id)`), so
  joining `tag` does not fan out additive measures — **if that uniqueness ever
  relaxes, additive metrics sliced by `tag` start double-counting.** Guard it.
- **Null/cast safety.** JSON extraction uses `NULLIF(raw ->> 'fifoPnlRealized','')::numeric`
  so one bad row can't fail the whole query.
- **Read-only.** Execution always runs in a `READ ONLY` transaction with a
  `statement_timeout` (5s in `executor.py`) and a hard `LIMIT` (≤500). The
  credentials are the real boundary — see §8.
- **Source of truth.** Realized PnL comes from FlexQuery `fifoPnlRealized` only
  (the active sync path). TWS-sourced fills (dormant) contribute `NULL`.

## 6. How to extend (the common tasks)

**Add a metric:** add an entry under `metrics:` with a `fact:` (which grain),
an ANSI_SQL `expression` qualified with the fact dataset name, a `description`,
and `ai_context.synonyms`. Money metrics over `execution_facts` must add
`FILTER (WHERE execution_facts.exec_role <> 'combo_summary')`. Nothing else to
wire — tool enums, validation, and SQL all derive from the model.

**Add a dimension:** add a field with a `dimension:` block to the dataset that
owns it (qualify the expression with that dataset's name). If it's on a new
table, add the dataset + a relationship from the fact. Reserved SQL words must be
quoted (e.g. `contracts."right"`).

**Add a fact (new grain):** add a view at the natural grain, a dataset pointing at
it, relationships to the conformed dimension datasets, and metrics with
`fact:` set to it. Keep additive measures at the lowest grain; only introduce a
higher-grain fact when a metric genuinely can't be expressed below it (like
`win_rate`).

**Add a relationship:** `from: {dataset, columns}` → `to: {dataset, columns}`,
directed fact → dimension. Multi-hop is fine (the `tag` path is
execution → bridge → group); BFS handles it.

After any change, run the resolver against the model (see §7) to confirm the SQL
and the grain rules.

## 7. Testing expectations

This component computes money — it must have golden-SQL coverage. At minimum:
- every metric × a representative dimension compiles to the expected SQL;
- a known out-of-grain pair (e.g. `win_rate` + `strike`) raises;
- the combo/canonical realized-PnL rule is asserted against a fixture.
Until a suite exists, validate with a `python -c` that calls `load_model()` +
`build_metric_query(...)` for the cases above.

## 8. Using it from an external LLM (Claude Code) over MCP

`src/mcp/semantic_server.py` exposes `describe_semantic_model()` (discover
metrics/dimensions/grain) and `query_metric(...)` (run by name; returns rows +
the compiled SQL for auditing) over stdio.

**Read-only role — the real boundary.** When the LLM holds DB credentials, the
credentials *are* the boundary, not the prompt. Create a least-privilege role:

```sql
CREATE ROLE ngv_analyst LOGIN PASSWORD '<strong-password>';
GRANT CONNECT ON DATABASE ngtrader_prod TO ngv_analyst;
GRANT USAGE ON SCHEMA public TO ngv_analyst;
-- the fact views + the conformed dimension tables they join to:
GRANT SELECT ON v_execution_facts, v_trade_facts, accounts, contracts,
                trade_group_executions, trade_groups TO ngv_analyst;
ALTER ROLE ngv_analyst SET default_transaction_read_only = on;
ALTER ROLE ngv_analyst SET statement_timeout = '10s';
```

The server **fails closed**: it requires `NGV_SEMANTIC_DATABASE_URL` and will not
fall back to the app's read-write credentials.

**Claude Code config.** Copy `.mcp.json.example` → `.mcp.json` (gitignored — it
holds the connection string) and point the URL at `ngv_analyst`:

```json
{
  "mcpServers": {
    "ngv-semantic": {
      "command": "uv",
      "args": ["run", "--extra", "mcp", "python", "-m", "src.mcp.semantic_server"],
      "cwd": "/Users/you/code/ngv-trader",
      "env": { "NGV_SEMANTIC_DATABASE_URL": "postgresql://ngv_analyst:<pw>@host:5432/ngtrader_prod" }
    }
  }
}
```

## 9. Deliberate v1 limitations (not bugs)

- **One grain per query.** Mixing metrics from different facts (e.g. `win_rate` +
  `fill_count`) is not supported — multi-fact symmetric aggregation is out of
  scope. Run two queries.
- **Equality + date-range filters only.** No `IN`, ranges (besides date),
  negation, or metric-level `HAVING` yet.
- **No many-to-many fan-out handling.** Safe today only because the tag bridge is
  1:1 (see §5).
- **Ordering** is fixed to `metric DESC`.

These are documented, not hidden. Lift them deliberately, preserving §5.
