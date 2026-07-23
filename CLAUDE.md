# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Governance and telemetry reporting for Microsoft Copilot Studio agents across an M365 tenant. Pulls data from ~12 Azure/M365 APIs plus manual CSV exports, stores everything in a local SQLite database, and outputs a multi-sheet Excel workbook. Also exposes an MCP server (stdio locally, HTTP on Azure Container Apps) so AI agents can query the telemetry conversationally, and a Bot Framework conversational agent (`src/agent/`) that consumes that MCP server.

## Commands

```bash
# Setup
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Fetch all sources + export workbook
python -m src.main all

# Fetch only (no export)
python -m src.main sync

# Export last sync to Excel (no new fetch)
python -m src.main export

# Import Copilot Studio analytics CSVs from a Viva export folder
python -m src.main import-viva <path/to/csv/folder>

# Multi-tenant: point at a different .env (must be the first two args)
python -m src.main --env .env.stryker all

# Deploy MCP server to Azure Container Apps
bash deploy.sh deploy-config/<tenant>.env

# One-time tenant provisioning (run in order)
bash provision/step1_insights.sh   # Log Analytics + App Insights
bash provision/step2_identity.sh   # sync SP permissions + admin consent
bash provision/step3_mcp.sh        # register MCP server app in Entra ID
```

There is no test suite, linter, or type-checker configured in this repo (no `tests/`, `pyproject.toml`, or `pytest.ini`) — don't assume `pytest` or `ruff` commands work.

## Architecture

**Pipeline shape:** `fetchers/` (one module per data source) → `store/sqlite_store.py` (upsert into SQLite, keyed by a stable run_id) → `writers/` (one module per Excel sheet, reads back from the store) → `workbook_writer.py` assembles the final `.xlsx`. `src/main.py` orchestrates `sync` (fetch+store) and `export` (store+write) as separate phases — `all` just runs both.

**Datasource config is declarative.** `config/datasources.py` defines an ordered list (`_DEFS`) of datasources, each mapping an env-var prefix (e.g. `LOG_ANALYTICS`) to its auth requirements and extra config keys. Adding a new live API source means adding an entry there plus a case in `cmd_sync()` in `src/main.py` — not writing new plumbing.

**Auth is centralized and deduplicated in `src/auth.py`.** `AuthManager` hands out one shared credential per unique `(tenant_id, client_id, client_secret)` for service-principal auth, and one shared credential per `(tenant_id, cli_account)` for CLI/interactive auth — so a tenant with 8 datasources using the same SP only authenticates once. `AuthManager.fetch_order()` runs all SP-authenticated sources first (no user interaction), then CLI-authenticated sources grouped by tenant so `az login`/browser prompts happen at most once per tenant.

**CSV imports are a second, parallel input path**, separate from the live-API fetchers. Each `{ENV_VAR}` documented in the README (e.g. `VIVA_REPROT_CS_DIR`, `M365ADMIN_AGENT_INVENTORY`) points at a manually-exported file/folder; when the var is set, the corresponding importer in `src/fetchers/` (e.g. `viva_report.py`, `m365_admin_report.py`, `m365_usage_report.py`, `ppadmin_consumption.py`) runs automatically as part of `sync`/`all`. `config/settings.py` resolves glob patterns in these paths to the most-recently-modified matching file, so wildcarded env values survive the date-suffixed filenames the M365 Admin Center appends on every export.

**Multi-tenant via `--env`.** `--env <file>` must be the first CLI argument pair — `src/main.py` loads it with `override=True` before any `config.*`/`src.*` module is imported, since `config/settings.py` reads env vars at import time. Each tenant gets its own `.env` file (see `.env.mwc`, `.env.stryker` in this repo) and typically its own SQLite DB / output path.

**XLA experience-model scoring** (`src/writers/sheet_xla*.py`) joins session metrics against a manually-maintained `agent_id → journey_name → persona_type` mapping (`imports/agent_journey_persona_map.csv`, loaded via `AGENT_JOURNEY_MAP`) to score agents by persona/journey rather than raw pass/fail. Score formula: `completion_rate × 0.6 + (100 − escalation_rate) × 0.2 + (100 − abandonment_rate) × 0.2`. If you add a new agent or change journey/persona taxonomy, this CSV — not code — is what needs updating.

**Cross-referencing** (`src/crossref.py`) correlates OTel conversation events (Log Analytics) against Azure Monitor dependency failures/exceptions/alerts to flag conversations with backing-service errors — feeds the `AzureMonitor_Health` and `CrossRef_Summary` sheets.

**Writers follow one convention:** each `src/writers/sheet_*.py` exposes a `write(ws: Worksheet, ...) -> None` function taking pre-fetched data lists/dicts; shared styling (header fill/font, autofit) lives in `src/writers/_style.py`. `workbook_writer.py` is the only place that knows the full sheet list and ordering.

**MCP server** (`src/mcp_server/server.py`) is transport-dual: stdio when launched locally via `.mcp.json`, HTTP/SSE when deployed to Azure Container Apps via the Dockerfile CMD. In the deployed case it downloads the SQLite DB from Azure Blob Storage on startup (`_maybe_download_db`) and validates Entra ID Bearer tokens; Microsoft agent platforms (Copilot Studio, M365 Copilot, AI Foundry) send these automatically.

**Bot Framework agent** (`src/agent/`) is a separate conversational front-end: `bot.py` runs a per-turn agentic loop (Azure OpenAI ↔ MCP tool calls) using tools fetched live from the deployed MCP SSE endpoint via `mcp_tools.py`. Conversation history is in-memory per conversation ID (`bot.py` notes this needs a Redis/Cosmos backing store for multi-replica deployments).

## Conventions worth knowing

- Settings (`config/settings.py`) load from `.env` via `python-dotenv` at import time — order of imports matters when a script needs a non-default env file (see `--env` handling above).
- `_resolve_glob` in `config/settings.py` handles the "M365 Admin Center appends a timestamp to every export filename" problem — prefer wildcarding new CSV-import env vars rather than hardcoding filenames.
- Per-datasource auth can be overridden independently (e.g. `LOG_ANALYTICS_CLIENT_ID`) — documented in `config/.env.example`, not the main README table.
- `{PREFIX}_ENABLED=false` skips a datasource entirely during `sync` — checked before auth is even acquired.
