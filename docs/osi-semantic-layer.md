# OSI Semantic Layer (tradebot analytics)

> **Status: implemented.** The tradebot can answer realized-PnL / win-rate /
> trade-count questions by running business-analyst metric definitions as
> read-only SQL. It does **not** write SQL — it selects metrics and dimensions
> by name from a semantic model.

## What this is

A small [Open Semantic Interchange (OSI)](https://github.com/open-semantic-interchange/OSI)
semantic model that describes trading metrics once, plus a resolver that compiles
a chosen metric + dimensions + filters into a single parameterized `SELECT`. The
tradebot drives it through the `query_metric` tool.

This is the Postgres analog of a **Snowflake semantic view** / Cortex Analyst
semantic model. Postgres has no native `CREATE SEMANTIC VIEW`, so the role each
Snowflake piece plays is filled by:

| Snowflake semantic view                                  | Here                                                        |
| -------------------------------------------------------- | ----------------------------------------------------------- |
| `TABLES` / `FACTS` (physical rows)                       | the `v_trade_realized_pnl` Postgres view                    |
| `DIMENSIONS` + `METRICS` + `WITH SYNONYMS`               | `osi/ngv_semantic_model.yaml`                               |
| `SELECT … FROM SEMANTIC_VIEW(view DIMENSIONS … METRICS …)` | `src/services/semantic/resolver.py`                         |
| Cortex Analyst picking metric/dimension names            | the tradebot `query_metric` tool (enumerated to the model)  |

The key property — same as Snowflake — is that the agent references **named**
metrics and dimensions, so the aggregation logic lives in one definition and the
agent cannot get it wrong or invent SQL.

## Pieces

- **`osi/ngv_semantic_model.yaml`** — the semantic model. One dataset
  (`v_trade_realized_pnl`), its dimensions (`symbol`, `sec_type`, `account`,
  `status`, time dim `executed_at`), and its metrics (`realized_pnl`,
  `trade_count`, `win_rate`). `ai_context.synonyms` are the equivalent of
  Snowflake `WITH SYNONYMS` — hints for the model.
- **`v_trade_realized_pnl`** (migration `…_add_trade_realized_pnl_view.py`) — a
  read-only view computing per-trade realized PnL from `fifoPnlRealized` on
  canonical executions. No table columns, data migration, or backfill: realized
  PnL stays computed-on-read, just packaged as a queryable fact source. The rule
  mirrors `trades.py`: `SUM(fifoPnlRealized)` over canonical fills; synthetic
  `combo_summary` rows carry no `fifoPnlRealized`, so `SUM` skips them and there
  is no leg/combo double-counting.
- **`src/services/semantic/loader.py`** — parses + validates the YAML into a
  registry. This registry is the **allow-list**: only names defined here can be
  referenced.
- **`src/services/semantic/resolver.py`** — `build_metric_query()` validates the
  selection and emits one parameterized `SELECT`. All SQL fragments come from the
  trusted model; all caller values are bound parameters. There is no free-form
  SQL path.
- **`src/services/semantic/executor.py`** — runs the query in a `READ ONLY`
  transaction with a `statement_timeout`, always rolled back.
- **`query_metric` tool** in `tradebot_agent.py` — its `metric`/`group_by`/filter
  enums are generated from the model at import, so the LLM physically cannot name
  an undefined metric or dimension.

## Example

User: *"What's my realized PnL by symbol this quarter?"* → the tradebot calls
`query_metric(metric="realized_pnl", group_by=["symbol"], start_date="2026-04-01")`,
which the resolver compiles to roughly:

```sql
SELECT trade_realized_pnl.symbol AS symbol,
       SUM(trade_realized_pnl.realized_pnl) AS realized_pnl
FROM v_trade_realized_pnl AS trade_realized_pnl
WHERE trade_realized_pnl.last_executed_at >= CAST(:date_start AS timestamptz)
GROUP BY trade_realized_pnl.symbol
ORDER BY realized_pnl DESC NULLS LAST
LIMIT :limit
```

The tool returns the rows **and** the compiled `sql` string so the operator can
audit exactly what ran.

## Safety

- The LLM never writes SQL; it picks names from an enum derived from the model.
- The resolver only interpolates trusted model expressions; every value binds.
- Execution is read-only with a statement timeout and a hard row `LIMIT`.

## Extending

Add a metric or dimension by editing `osi/ngv_semantic_model.yaml` only — the
tool enums, validation, and SQL all derive from it. New facts (e.g. commissions,
unrealized PnL) typically mean adding a column to the view (or a new view) and a
matching field/metric in the YAML.

### Caveat

Realized PnL is sourced from the FlexQuery `fifoPnlRealized` field only (the
active sync path). TWS-sourced executions — a dormant path — do not populate it,
so they contribute `NULL`. The view assumes `fifoPnlRealized` is numeric-castable.

## Using it from an external LLM (Claude Code) over MCP

`src/mcp/semantic_server.py` is a stdio MCP server that exposes the same semantic
layer to an external agent (e.g. Claude Code on a Mac). It serves two tools:

- `describe_semantic_model()` — discover metrics/dimensions/synonyms.
- `query_metric(metric, group_by, filters, start_date, end_date, time_grain, limit)`
  — the same name-only interface as the in-app tool. Returns rows + compiled SQL.

The agent picks names; the resolver writes the SQL. There is no raw-SQL path.

### 1. Create a read-only Postgres role (the real boundary)

When the LLM holds DB credentials, the credentials *are* the security boundary —
not the prompt. Give it a least-privilege, read-only role:

```sql
CREATE ROLE ngv_analyst LOGIN PASSWORD '<choose-a-strong-password>';
GRANT CONNECT ON DATABASE ngtrader_prod TO ngv_analyst;
GRANT USAGE ON SCHEMA public TO ngv_analyst;
GRANT SELECT ON v_trade_realized_pnl TO ngv_analyst;        -- only the fact view
ALTER ROLE ngv_analyst SET default_transaction_read_only = on;
ALTER ROLE ngv_analyst SET statement_timeout = '10s';
```

The server also runs every query in its own `READ ONLY` transaction with a
timeout, so this is defense in depth — but the role is what makes leaked or
injected instructions harmless.

### 2. Point Claude Code at the server

Copy `.mcp.json.example` to `.mcp.json` (gitignored — it holds the connection
string) and set the URL to the `ngv_analyst` role:

```json
{
  "mcpServers": {
    "ngv-semantic": {
      "command": "uv",
      "args": ["run", "--extra", "mcp", "python", "-m", "src.mcp.semantic_server"],
      "cwd": "/Users/you/code/ngv-trader",
      "env": {
        "NGV_SEMANTIC_DATABASE_URL": "postgresql://ngv_analyst:<password>@host:5432/ngtrader_prod"
      }
    }
  }
}
```

Then in Claude Code: *"what's my realized PnL by symbol this quarter?"* → it calls
`describe_semantic_model` to learn the names, then `query_metric`. `NGV_SEMANTIC_DATABASE_URL`
falls back to the app's `DB_*` vars if unset.
