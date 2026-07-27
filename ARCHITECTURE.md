# Architecture

This document explains how Copilot & M365 Insights is put together — the pipeline shape, the major components, and the design decisions behind them. For setup and usage instructions, see [README.md](README.md). For contributor-facing conventions, see [CLAUDE.md](CLAUDE.md).

## What problem this solves

An M365 tenant running Copilot Studio agents scatters its telemetry across a dozen places: Application Insights traces, Azure Monitor alerts, Power Platform admin APIs, Dataverse, Microsoft Graph, Viva Insights, and several CSV-only exports from various admin centers (M365 Admin Center, Power Platform Admin Center). No single API gives a governance/ops view across all of it.

This project pulls all of it into one local SQLite database on a schedule, correlates it, and turns it into two consumable outputs:

1. A multi-sheet Excel workbook for humans (governance reviews, adoption reporting, credit/cost tracking).
2. An MCP server so AI agents (Copilot Studio, M365 Copilot, AI Foundry, Claude) can query the same data conversationally.

## High-level pipeline

```
                 ┌─────────────────────────────────────────────────┐
                 │                  config/                        │
                 │  datasources.py (declarative source list)        │
                 │  settings.py (.env loading, glob resolution)     │
                 └───────────────────────┬───────────────────────────┘
                                          │
        ┌──────────────────── src/main.py orchestrates ─────────────────────┐
        │                                                                    │
        ▼                                                                    ▼
┌───────────────────┐                                          ┌──────────────────────┐
│   src/fetchers/    │   live APIs (auth via src/auth.py)       │   src/fetchers/       │
│  log_analytics.py  │   ─────────────────────────────►        │  viva_report.py       │
│  azure_monitor.py  │                                          │  m365_admin_report.py │
│  powerplatform_    │   CSV imports (manual export → file)     │  m365_usage_report.py │
│    admin.py        │   ─────────────────────────────►         │  ppadmin_consumption  │
│  dataverse.py      │                                          │    .py                │
│  graph.py          │                                          │  journey_map_importer │
│  viva.py           │                                          │    .py                │
│  purview.py        │                                          │  usage_agent_override │
│  defender.py       │                                          │    _importer.py       │
│  pp_analytics.py   │                                          │                       │
│  global_discovery  │                                          │                       │
└─────────┬──────────┘                                          └───────────┬───────────┘
          │                                                                  │
          └───────────────────────────┬──────────────────────────────────────┘
                                       ▼
                      ┌───────────────────────────────────┐
                      │      src/store/sqlite_store.py     │
                      │  upsert into SQLite, keyed by       │
                      │  run_id; DDL + idempotent           │
                      │  migrations; compatibility views     │
                      └───────────────────┬─────────────────┘
                                          │
                    ┌─────────────────────┴─────────────────────┐
                    ▼                                             ▼
        ┌────────────────────────┐                  ┌──────────────────────────┐
        │     src/crossref.py     │                  │      src/writers/          │
        │  correlates OTel events │                  │  one sheet_*.py per Excel  │
        │  against Azure Monitor  │                  │  tab; workbook_writer.py   │
        │  failures/exceptions    │                  │  assembles the .xlsx        │
        └────────────┬─────────────┘                  └──────────────┬─────────────┘
                     │                                                 │
                     └───────────────────────┬─────────────────────────┘
                                             ▼
                                  agent_telemetry_<ts>.xlsx


                      ┌───────────────────────────────────────┐
                      │        src/mcp_server/server.py         │
                      │  stdio (local) or HTTP/SSE (Azure)       │
                      │  reads the same SQLite DB directly       │
                      └───────────────────┬───────────────────────┘
                                          │ MCP tool calls
                    ┌──────────────────────┼──────────────────────┐
                    ▼                      ▼                      ▼
             Copilot Studio          M365 Copilot           src/agent/bot.py
             (native MCP)            / AI Foundry           (Bot Framework agent,
                                      (native MCP)           Azure OpenAI + MCP loop)
```

`src/main.py` has two independently runnable phases:

- **`sync`** — fetch from every enabled datasource, upsert into SQLite, tag rows with a `run_id`.
- **`export`** — read the most recent `run_id`'s data back out of SQLite and write the Excel workbook.
- **`all`** runs both in sequence. This split means a workbook can be re-exported (e.g. after fixing a writer bug) without re-hitting every API.

## Core components

### 1. Declarative datasource config (`config/datasources.py`)

Each of the ~8 live-API sources (Log Analytics, Azure Monitor, Power Platform Admin, Global Discovery, Dataverse, Graph, Viva, Purview, Defender) is one entry in an ordered list (`_DEFS`), not a bespoke code path. Each entry maps an env-var prefix to:

- which auth method it needs (service principal vs. CLI/interactive),
- which extra config keys it reads (e.g. `LOG_ANALYTICS_WORKSPACE_ID`),
- whether it's enabled (`{PREFIX}_ENABLED=false` skips it before auth is even acquired).

Adding a new live datasource means adding one entry here plus a matching branch in `cmd_sync()` — there's no separate registration/plumbing step.

### 2. Centralized, deduplicated auth (`src/auth.py`)

`AuthManager` hands out **one shared credential per unique identity**, not per datasource:

- Service-principal auth is cached by `(tenant_id, client_id, client_secret)` — a tenant with 8 datasources on the same SP authenticates once.
- CLI/interactive auth is cached by `(tenant_id, cli_account)` — an `az login` or browser prompt happens at most once per tenant/account pair, even if several datasources use it.

`AuthManager.fetch_order()` sorts datasources so **all SP-authenticated sources run first** (fully unattended), then CLI-authenticated sources grouped by tenant (interactive prompts are batched together instead of scattered through a long run). This matters because `sync` is meant to run unattended in CI/scheduled contexts wherever possible — only the sources that genuinely need interactive login should ever pause execution.

### 3. Fetchers (`src/fetchers/`) — two parallel input paths

**Live API fetchers** (`log_analytics.py`, `azure_monitor.py`, `powerplatform_admin.py`, `dataverse.py`, `graph.py`, `viva.py`, `purview.py`, `defender.py`, `pp_analytics.py`, `global_discovery.py`) each take a credential/client and return plain lists of dicts — no direct DB access.

**CSV importers** (`viva_report.py`, `m365_admin_report.py`, `m365_usage_report.py`, `ppadmin_consumption.py`, `journey_map_importer.py`, `usage_agent_override_importer.py`) are a structurally separate, parallel path: the M365 Admin Center, Power Platform Admin Center, and Viva Insights don't expose everything via API, so these sources are manually exported to CSV and dropped in `imports/`. Each is gated by an env var (documented in the README's CSV import table) that points at a file or folder; `config/settings.py`'s `_resolve_glob` resolves wildcard patterns to the most-recently-modified matching file, because the M365 Admin Center appends a date suffix to every export filename. When the env var is set, `cmd_sync()` runs the importer automatically — no separate CLI invocation needed (except `import-viva`, kept as a standalone command for ad-hoc re-imports).

Both paths converge on the same `SqliteStore.upsert_*` methods, so downstream code (writers, crossref, MCP server) doesn't care whether a row came from a live API or a CSV export.

### 4. Storage (`src/store/sqlite_store.py`)

A single SQLite file is the system of record. `SqliteStore`:

- Owns the full DDL for every table plus idempotent `_migrate()` logic, so schema changes ship as additive migrations rather than requiring a fresh DB.
- Upserts are keyed by a stable identity per row type (not always `run_id` alone — e.g. conversation events dedupe on their own natural key) so re-running `sync` doesn't duplicate rows, while a `run_id` column tags each sync pass for point-in-time export.
- Exposes `compute_kpi_snapshot()` / `upsert_kpi_snapshot()` to persist a tenant-wide KPI rollup on every sync, which is what powers the `KPI History` sheet's trend-over-time view — this is the one piece of derived data computed at sync time rather than at export/read time.
- Maintains compatibility views (e.g. `pva_agents`) so both the workbook export path and the MCP server query the same shapes without duplicating view logic — the MCP server explicitly imports `SqliteStore` itself (rather than hand-rolling schema) specifically to avoid the two drifting apart.
- Optionally syncs the whole DB file to Azure Blob Storage (`src/store/blob_store.py`) after `sync`, which is how the deployed MCP server (running in a container with no persistent local disk) gets a copy of the latest data.

### 5. Cross-referencing (`src/crossref.py`)

Bridges two otherwise-separate signal types: OTel conversation events from Log Analytics (what a user experienced during a conversation) and Azure Monitor dependency failures/exceptions/alerts (what broke in a backing service, e.g. a Power Automate flow or connector). `build_crossref()` correlates them by time window and produces `health_detail` (raw failure rows) and `crossref_summary` (which conversations had a backing-service error during their session) — feeding the `AzureMonitor_Health` and `CrossRef_Summary` sheets. This is what turns "the agent gave a bad answer" into "the agent gave a bad answer *because* a downstream connector was throwing 503s."

### 6. Experience model / XLA scoring (`src/writers/sheet_xla*.py`)

Rather than reporting raw completion/escalation numbers, the workbook scores agents against a persona/journey taxonomy:

- `imports/agent_journey_persona_map.csv` is a manually maintained mapping of `agent_id → journey_name → persona_type` (four journeys: Get Help, Complete Task, Find Info, Automate Work; five personas: end_user, it_support, hr, knowledge_worker, operations).
- Loaded via `AGENT_JOURNEY_MAP` on every sync into `dim_agent_journey_persona`.
- Session metrics are joined against this dimension table to compute a score per persona+journey: `completion_rate × 0.6 + (100 − escalation_rate) × 0.2 + (100 − abandonment_rate) × 0.2`.
- This is a data/config change, not a code change — extending the taxonomy or reclassifying an agent means editing the CSV.

### 7. Usage-to-credit crosswalk

A specific data-quality problem worth calling out: `m365_usage_agents.agent_id` (from the M365 Admin usage report) uses a **different ID scheme** than the Copilot Studio bot GUID used everywhere else (`dim_agent.agent_id`, `m365_admin_agent_inventory.bot_id`, `tokenomics_entitlement_per_agent.agent_id`). The only natural bridge between usage volume and credit consumption is the agent's display name, which is ambiguous when an agent is cloned across dev/test/prod. `resolved_agent_id` is auto-populated only when a name maps to exactly one `bot_id`; ambiguous names are left `NULL` rather than guessed, with a manual override file (`USAGE_AGENT_ID_OVERRIDES`) to force a mapping. This is a deliberate "fail closed" choice — a wrong auto-match would silently corrupt cost-per-agent numbers.

### 8. Writers (`src/writers/`)

One `sheet_*.py` module per Excel tab, each exposing a `write(ws: Worksheet, ...) -> None` function that takes pre-fetched data (lists/dicts already read from SQLite) — writers never query the DB themselves. Shared styling (header fill/font, column autofit) lives in `_style.py`. `workbook_writer.py` is the single place that knows the full sheet list, ordering, and which sheets can be excluded via `EXCLUDE_SHEETS`. This convention keeps each sheet's logic isolated and makes the workbook's composition auditable from one file.

### 9. MCP server (`src/mcp_server/server.py`)

Transport-dual, ~1050 lines, built on the `mcp` package's low-level `Server`:

- **Local**: stdio transport, launched via `.mcp.json` (`python -m src.mcp_server.server`) — used by Claude Code and other local MCP clients.
- **Deployed**: HTTP/SSE transport on Azure Container Apps (via the Dockerfile CMD). On startup it downloads the SQLite DB from Blob Storage (`_maybe_download_db`) and validates Entra ID Bearer tokens (or a static API key for platforms that don't do OAuth) on every request via `_validate_token`.

It exposes ~14 tools (`get_kpi_snapshot`, `get_summary_stats`, `get_agent_activity`, `get_conversations`, `get_conversation_detail`, `get_user_activity`, `get_top_connectors`, `get_connector_calls`, `get_user_prompts`, `search_by_user`, `get_agents`, `get_environments`, `get_viva_insights`, plus an escape-hatch `run_sql`) and one resource (a `Database Schema` doc so a calling model knows the shape before writing SQL). Microsoft agent platforms (Copilot Studio, M365 Copilot, AI Foundry) attach Bearer tokens automatically when calling MCP endpoints, so no manual token-passing is needed from the caller's side.

### 10. Bot Framework agent (`src/agent/`)

A separate, optional conversational front-end (`bot.py`) — not part of the sync/export pipeline. Per turn: fetch the current tool list live from the deployed MCP SSE endpoint (`mcp_tools.py`), then run an agentic loop (Azure OpenAI chat completion ↔ MCP tool execution) until the model stops requesting tools, then reply via Bot Framework `ActivityHandler`. Conversation history is kept in an in-memory dict keyed by conversation ID — explicitly called out in the code as needing a Redis/Cosmos DB backing store before this can run behind more than one replica.

## Multi-tenant support

Each tenant gets its own `.env` file (`.env.mwc`, `.env.stryker`, etc.) and typically its own SQLite DB / output path. `--env <file>` must be the first CLI argument pair (`python -m src.main --env .env.stryker all`) because `src/main.py` loads it with `override=True` *before* importing any `config.*`/`src.*` module — those modules read env vars at import time via `python-dotenv`, so the load order is load-bearing, not cosmetic.

## Why these boundaries

- **Fetchers never touch the DB; writers never touch the network.** Every fetcher returns plain data structures, every writer takes pre-fetched data. This is what makes `sync` and `export` independently runnable, and what let the MCP server reuse `SqliteStore` directly instead of re-deriving schema knowledge.
- **SQLite is the only source of truth between phases.** The Excel workbook, the MCP server, and the Bot Framework agent all read from the same DB (or a Blob-synced copy of it) rather than from each other — there's exactly one place data can go stale.
- **Config is data, not code, wherever it changes independently of the pipeline.** Datasource definitions, the XLA persona/journey taxonomy, and the usage/credit ID crosswalk are all CSV or declarative-list config specifically so tenant-specific tuning doesn't require a code change.
