"""
MCP server — exposes agent telemetry data to Microsoft AI agents.

Transports:
  Local (Claude Code):  stdio   — launched by .mcp.json
  Deployed (Azure):     HTTP/SSE — launched by Dockerfile CMD, protected by Entra ID

Auth (deployed only):
  Validates Bearer tokens issued by Entra ID for MCP_APP_ID_URI.
  Microsoft agent platforms (Copilot Studio, AI Foundry, M365 Copilot) send
  these tokens automatically when they call the MCP endpoint.
"""

import json
import os
import sqlite3
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# ---------------------------------------------------------------------------
# Bootstrap: download db from blob storage when running in Azure
# ---------------------------------------------------------------------------

def _maybe_download_db() -> None:
    from config.settings import settings
    if not settings.azure_storage_account:
        return
    Path(settings.db_path).unlink(missing_ok=True)
    try:
        from src.store.blob_store import download_db
        download_db(
            settings.db_path,
            settings.azure_storage_account,
            settings.azure_storage_container,
            settings.azure_storage_db_blob,
        )
    except Exception as e:
        print(f"Warning: could not download db from blob storage: {e}", file=sys.stderr)


_maybe_download_db()

from config.settings import settings
from mcp.server import Server
from mcp.types import (
    CallToolResult,
    ListResourcesResult,
    ListToolsResult,
    ReadResourceResult,
    Resource,
    TextContent,
    Tool,
)

server = Server("agent-telemetry")

# ---------------------------------------------------------------------------
# Database helper
# ---------------------------------------------------------------------------

# Reuse the real store's schema (DDL + view-based migrations) instead of a
# hand-maintained subset — a hand-copied copy previously drifted out of sync
# with sqlite_store.py (missing columns on pva_agents) and would silently
# create a stale, non-view pva_agents table on a fresh DB that no SqliteStore
# had ever migrated yet.
from src.store.sqlite_store import SqliteStore


def _db() -> sqlite3.Connection:
    # Constructing SqliteStore runs the full DDL + _migrate() (idempotent),
    # guaranteeing compatibility views (pva_agents, etc.) exist even if this
    # is the very first process to touch settings.db_path.
    store = SqliteStore(settings.db_path)
    conn = store._conn
    conn.row_factory = sqlite3.Row
    return conn


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


# ---------------------------------------------------------------------------
# Entra ID token validation
# ---------------------------------------------------------------------------

def _validate_token(request_headers: dict) -> None:
    """Raises ValueError if the API key is missing or invalid."""
    if not settings.mcp_api_key:
        return  # auth not configured — skip (local dev)

    # Check all headers AI Foundry and other platforms may use
    authorization = request_headers.get("authorization") or request_headers.get("Authorization")
    api_key = request_headers.get("api-key") or request_headers.get("x-api-key")

    if api_key:
        token = api_key
    elif authorization:
        token = authorization[7:] if authorization.startswith("Bearer ") else authorization
    else:
        raise ValueError("Missing Authorization header")

    if token != settings.mcp_api_key:
        raise ValueError("Invalid API key")


# ---------------------------------------------------------------------------
# Schema resource
# ---------------------------------------------------------------------------

_SCHEMA_DOC = """
# Agent Telemetry Database Schema

Copilot Studio agent telemetry from Azure Log Analytics / Application Insights.

## Tables

### conversation_events
Every event emitted by the agent — messages in, messages out, topic starts.
- timestamp: When the event occurred (UTC ISO)
- event_name: BotMessageReceived | BotMessageSend | TopicStart | ...
- session_id: Groups events in one browser/channel session
- user_id: Azure AD object ID of the user (source tenant)
- conversation_id: Groups a single conversation end-to-end
- channel_id: pva-studio | msteams | webchat | directline | ...
- design_mode: 1 = test traffic from Copilot Studio, 0 = production
- topic_name: Copilot Studio topic that handled this turn
- text: Message text (BotMessageReceived events only)

### connector_calls
Every time the agent invoked a Power Platform connector.
- timestamp, connector_name, action_target, conversation_id, session_id
- user_id, channel_id, design_mode
- success: 1 = succeeded, 0 = failed
- result_code: HTTP status returned by the connector
- duration_ms: Connector call latency in milliseconds

### sync_runs
One row per data sync run — when data was last refreshed.

### pva_agents
Copilot Studio agents registered in the Power Platform environment.
- agent_id: GUID of the agent
- display_name: Human-readable agent name (use this when reporting agent names)
- schema_name: Internal schema identifier
- environment_id: Power Platform environment GUID (join to pva_environments)
- created_at, modified_at, published_at: ISO timestamps
- created_by, owner_id, created_in: populated from the PP Inventory API

### pva_environments
Power Platform environments where agents are deployed.
- environment_id: GUID — joins to pva_agents.environment_id
- display_name: Human-readable environment name
- type / sku: e.g. Sandbox, Production, Default
- region: Azure region
- state: Ready / Disabled
- dataverse_url: Dataverse org URL for this environment

### pva_agent_solutions
Solution each agent is packaged in (from Dataverse solutioncomponents).
- agent_id: joins to pva_agents.agent_id
- solution_name: Human-readable solution name
- solution_unique: Internal unique name (e.g. "WorkIQAgents")
- version: solution version string
- is_managed: 1 = managed/deployed, 0 = unmanaged/in development

### pva_publishers
Solution publishers registered in the Power Platform environment.
- publisher_id, display_name, unique_name, custom_prefix

### pva_dlp_policies
Data Loss Prevention policies governing which connectors agents can use.
- display_name: Policy name
- environment_type: AllEnvironments | OnlyEnvironments | ExceptEnvironments
- blocked_connectors: comma-separated blocked connector names
- business_connectors: connectors in the Business data group
- non_business_connectors: connectors in the Non-business group
NOTE: Requires Power Platform Admin role to sync — may be empty.

### az_dependency_failures
Failed connector/API calls captured by Azure Monitor Application Insights.
- operation_id: App Insights operation correlation ID
- agent_id, agent_name, env_id: from gen_ai.* properties
- conversation_id: join key back to conversation_events
- dependency_name: name of the failed dependency/connector
- result_code: HTTP or error code
- duration_ms: call duration
- timestamp: when the failure occurred

### az_exceptions
Exceptions logged by the agent runtime in Application Insights.
- operation_id: App Insights operation correlation ID
- agent_id: from gen_ai.agent.id property
- conversation_id: join key back to conversation_events
- exception_type: exception class name
- exception_message: exception detail message
- timestamp: when the exception was logged

### pp_bot_sessions
Per-session outcome log from Power Platform bot analytics APIs — independent of
Application Insights, usually populated even when az_*/conversation_events are empty.
- session_id, bot_id: joins to pva_agents.agent_id
- environment_id, start_time, channel
- outcome: Resolved | Escalated | Abandoned | Unengaged
- duration_sec, topic_id, topic_name, csat_score, turn_count

### pp_bot_topic_analytics
Per-topic daily rollup from Power Platform bot analytics APIs.
- bot_id, topic_id, topic_name, fetch_date, period_from, period_to
- total_sessions, resolved_sessions, escalated_sessions, abandoned_sessions
- trigger_count, success_rate

### viva_reports_cs_session_metrics
Daily per-agent session outcomes + CSAT, imported from the Viva Insights Copilot Studio
report ("CS_" reports). Requires that report to have been imported — check sync_runs /
report_refresh_date if empty.
- agent_id, metric_date (PK)
- total_sessions, resolved_sessions, escalated_sessions, abandoned_sessions, engaged_sessions, unengaged_sessions
- csat_responses, csat_1..csat_5
- avg_duration_all / _unengaged / _engaged / _resolved / _escalated / _abandoned
- ks_engaged / ks_unengaged / ks_resolved / ks_escalated / ks_abandoned (knowledge-source counts)

### viva_reports_cs_topic_metrics
Same outcome breakdown as viva_reports_cs_session_metrics, split per topic.
- agent_id, topic_id, topic_name, metric_date (PK)

### viva_reports_cs_weekly_active_users
Most reliable per-agent activity signal when conversation_events is empty.
- agent_id, start_date (PK), active_user_count

### viva_reports_cs_autonomous_metrics / viva_reports_cs_autonomous_trigger_metrics
Daily autonomous (agentic) run success/failure, overall and per trigger.
- agent_id, metric_date (+ trigger_schema_name for the trigger table)
- total_runs, successful_runs, failed_runs, total/successful/failed_duration
- ks_successful/failed, actions_successful/failed, no_op_successful/failed

### viva_reports_cs_action_metrics
Per-action success rates.
- agent_id, action_schema_name, metric_date
- total_runs, successful_actions_in_runs, actions_in_successful_runs, successful_actions_in_successful_runs

### viva_reports_cs_knowledge_source_metrics
Per-knowledge-source usage and outcome counts.
- agent_id, source_type, metric_date
- count_total, count_unengaged, count_engaged, count_resolved, count_escalated, count_abandoned, count_autonomous, count_successful_autonomous

### viva_reports_cs_copilot_agents
Agent registry as seen by Copilot Analytics — a second, independent agent list.
- agent_id (PK), agent_name, description, surface, mode, categories, agent_type

### viva_reports_cs_extended_metadata
- agent_id (PK), aad_tenant_id, roi_configuration

### m365_admin_agent_inventory
Full Copilot Studio / Copilot agent inventory from the M365 Admin Center (CSV import).
- title_id (PK) — joins to m365_usage_agents.agent_id
- bot_id — joins to pva_agents.agent_id
- name, status, channel, owner, publisher, platform, description
- can_read_od_sp / can_read_sp_sites / can_extend_graph / can_generate_images / can_use_code_interpreter: capability flags

### m365_usage_agents
30-day rolling usage rollup per agent from the M365 Admin Center (CSV import). Coarser
than viva_reports_cs_* (no outcome detail) but always available once imported.
- agent_id (PK), agent_name, creator_type
- active_users_licensed, active_users_unlicensed, responses_sent, last_activity_date

### m365_usage_agent_users
Per-user per-agent usage from the same M365 Admin rollup.
- agent_id, username (PK), agent_name, creator_type, responses_sent, last_activity_date

### dim_agent_journey_persona
Maps agent_id to a journey_name + persona_type for the experience model.
- agent_id, journey_name, persona_type (PK), agent_name

### kpi_snapshots
Pre-aggregated daily KPI row — backs the get_kpi_snapshot tool.
- snapshot_date, lookback_days
- License/adoption: total_licenses, enabled_users, active_users, activation_rate, adoption_rate, power_users, total_prompts, avg_prompts_per_user
- Per-workload prompts: prompts_copilot_chat/teams/outlook/excel/word/powerpoint/onenote/loop
- Agent adoption: agent_adopters, agent_adoption_pct
- Agent inventory: total_agents, active_agents, utilization_rate, production_agents, non_prod_agents, total_conversations
- Environment mix: env_default/developer/teams/production/sandbox/trial

### billing_licences
License inventory per SKU, imported from a CSV export (M365 Admin Center → Billing → Licenses).
- product_title, total_licenses, assigned_licenses, expired_licenses
NOTE: reflects the snapshot date of the most recently imported file, not real-time state.

### m365_usage_active_users_services / _activity / _detail, m365_usage_active_user_counts
Tenant-level and per-user active/inactive counts per M365 service (Exchange, Teams,
OneDrive, SharePoint, Yammer, Office 365), imported from CSV. `_detail` has per-user
license flags (has_exchange, has_teams, ...) and last-activity dates for inactive-user analysis.

### m365_usage_activations_users
Per-user per-product activation status (CSV import).
- user_principal_name, product_type, last_activated_date, windows/mac/ios/android/shared_computer flags

### m365_usage_proplus_counts / _detail / _platforms
Daily active-user counts (and per-user flags) for M365 apps (Outlook, Word, Excel,
PowerPoint, OneNote, Teams) and platforms (Windows, Mac, Mobile, Web). CSV import.

### tokenomics_capacity_consumption / entitlement_consumption / entitlement_per_agent / entitlement_per_user
Power Platform Admin credit/consumption data: daily resource burn, prepaid vs. PAYG per
environment, and billed/non-billed credit per agent and per user.

### viva_person_insights
Per-user weekly Viva Insights activity breakdown (Graph Analytics API).
- user_id: Azure AD object ID — join to conversation_events.user_id
- week_start / week_end: ISO dates bounding the week
- focus_hours: uninterrupted focus blocks
- meeting_hours: scheduled meeting time
- email_hours: Outlook / email time
- chat_hours: Teams chat time
- after_hours: collaboration outside typical working hours
NOTE: requires Analytics.ReadAll app permission + Viva Insights license per user.
      Rows only appear for users who have had production conversations.

### viva_org_insights
Organisation-wide Viva Insights aggregate metrics (Management API — stubbed).
Populated once the Viva Insights Management API access is provisioned.

### az_alerts
Azure Monitor alerts that fired against agent resources.
- alert_id: Azure resource ID of the alert instance
- agent_id: from gen_ai.agent.id tag on the resource
- alert_name: alert rule name
- severity: Sev0–Sev4
- fired_time: when the alert fired
- resource_id: Azure resource that triggered the alert

## Data source priority — read this before reporting "no data"
Application Insights (conversation_events, connector_calls, az_*) is only ONE of four
independent data sources, and the one most likely to be empty (agents are frequently not
yet configured to write to it). The built-in tools (get_kpi_snapshot, get_agent_activity,
get_conversations, get_conversation_detail, get_user_activity, get_top_connectors,
get_connector_calls, get_user_prompts, search_by_user) all read ONLY from
conversation_events/connector_calls. If they return empty or near-zero, that means App
Insights isn't wired up — it does NOT mean there is no usage data. Before concluding there
is no data, query these fallback sources with run_sql, in priority order:
1. pp_bot_sessions / pp_bot_topic_analytics — Power Platform bot analytics, independent of
   App Insights entirely. Usually populated even in a fresh deployment.
2. viva_reports_cs_* tables — richest aggregate (outcomes, CSAT, autonomous runs) but
   requires the Viva Insights Copilot Studio report to have been imported.
3. m365_usage_agents / m365_usage_agent_users — M365 Admin usage rollup (CSV import);
   coarser but always available once imported.
4. conversation_events / connector_calls / az_* — richest per-conversation detail, only
   once App Insights is actually configured.
If all four are empty for the requested period, say so explicitly and name the closest
one to being usable (e.g. "the Copilot Studio usage report hasn't been imported yet").

## Key relationships
conversation_events.conversation_id = connector_calls.conversation_id
conversation_events.conversation_id = az_dependency_failures.conversation_id
conversation_events.conversation_id = az_exceptions.conversation_id
pva_agents.environment_id = pva_environments.environment_id
pva_agents.agent_id = pva_agent_solutions.agent_id
pva_agents.agent_id = az_dependency_failures.agent_id (approximate — depends on agent config)
pva_agents.agent_id = pp_bot_sessions.bot_id = pp_bot_topic_analytics.bot_id
pva_agents.agent_id = viva_reports_cs_copilot_agents.agent_id = viva_reports_cs_session_metrics.agent_id
pva_agents.agent_id = m365_admin_agent_inventory.bot_id
m365_admin_agent_inventory.title_id = m365_usage_agents.agent_id = m365_usage_agent_users.agent_id
dim_agent_journey_persona.agent_id joins any of the agent_id columns above for persona/journey context

## Cross-reference pattern
To find conversations with both OTel failures AND Azure Monitor signals:
  SELECT e.conversation_id, d.dependency_name, d.result_code, ex.exception_type
  FROM conversation_events e
  JOIN connector_calls c ON c.conversation_id = e.conversation_id AND c.success = 0
  LEFT JOIN az_dependency_failures d ON d.conversation_id = e.conversation_id
  LEFT JOIN az_exceptions ex ON ex.conversation_id = e.conversation_id
  WHERE d.row_id IS NOT NULL OR ex.row_id IS NOT NULL
  GROUP BY e.conversation_id

## Notes
- Filter design_mode = 0 for production traffic only
- user_id is an Azure AD object ID (Graph API lookup needed for email)
- There is NO agent_name column in conversation_events or connector_calls — use pva_agents for agent names
- az_*, conversation_events, connector_calls will be empty until agents are configured to write
  to Application Insights — see "Data source priority" above before reporting no data
- viva_reports_cs_* tables require the Copilot Studio usage report to have been imported
- billing_licences, m365_usage_*, m365_admin_agent_inventory are populated from manual CSV
  exports from the M365 Admin Center and reflect the snapshot date of the last import, not
  real-time state — check report_refresh_date/report_date when recency matters
"""


@server.list_resources()
async def list_resources() -> ListResourcesResult:
    return ListResourcesResult(resources=[
        Resource(
            uri="schema://tables",
            name="Database Schema",
            description="Schema documentation for all tables in agent_telemetry.db",
            mimeType="text/markdown",
        )
    ])


@server.read_resource()
async def read_resource(uri: str) -> ReadResourceResult:
    if str(uri) == "schema://tables":
        return ReadResourceResult(contents=[TextContent(type="text", text=_SCHEMA_DOC)])
    raise ValueError(f"Unknown resource: {uri}")


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@server.list_tools()
async def list_tools() -> ListToolsResult:
    return ListToolsResult(tools=[
        Tool(
            name="get_kpi_snapshot",
            description="Pre-aggregated KPI summary (conversations, active users, connector health, token usage). Call this first for overview questions.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="get_summary_stats",
            description="Counts: total/production conversations, events, connector calls, top-5 connectors, date range.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="get_agent_activity",
            description="Per-agent conversation counts (total/production/test) and last activity.",
            inputSchema={
                "type": "object",
                "properties": {
                    "design_mode": {"type": "boolean", "description": "true=test, false=production, omit=both"},
                },
                "required": [],
            },
        ),
        Tool(
            name="get_conversations",
            description="List conversations with message counts and topics. Filter by channel or design_mode.",
            inputSchema={
                "type": "object",
                "properties": {
                    "channel_id": {"type": "string"},
                    "design_mode": {"type": "boolean"},
                    "limit": {"type": "integer", "default": 25, "maximum": 50},
                },
                "required": [],
            },
        ),
        Tool(
            name="get_conversation_detail",
            description="Event timeline for one conversation. Requires conversation_id from get_conversations.",
            inputSchema={
                "type": "object",
                "properties": {"conversation_id": {"type": "string"}},
                "required": ["conversation_id"],
            },
        ),
        Tool(
            name="get_user_activity",
            description="Per-user conversation and message counts, channels, and last activity.",
            inputSchema={
                "type": "object",
                "properties": {
                    "design_mode": {"type": "boolean"},
                    "limit": {"type": "integer", "default": 25, "maximum": 50},
                },
                "required": [],
            },
        ),
        Tool(
            name="get_top_connectors",
            description="Connectors ranked by call count with success rate and avg latency.",
            inputSchema={
                "type": "object",
                "properties": {
                    "design_mode": {"type": "boolean"},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": [],
            },
        ),
        Tool(
            name="get_connector_calls",
            description="Raw connector call log. Filter by connector name, action, or success.",
            inputSchema={
                "type": "object",
                "properties": {
                    "connector_name": {"type": "string"},
                    "action_target": {"type": "string"},
                    "success": {"type": "boolean"},
                    "design_mode": {"type": "boolean"},
                    "limit": {"type": "integer", "default": 25, "maximum": 50},
                },
                "required": [],
            },
        ),
        Tool(
            name="get_user_prompts",
            description="User messages sent to agents. Supports keyword search and conversation filter.",
            inputSchema={
                "type": "object",
                "properties": {
                    "search": {"type": "string"},
                    "conversation_id": {"type": "string"},
                    "design_mode": {"type": "boolean"},
                    "limit": {"type": "integer", "default": 25, "maximum": 50},
                },
                "required": [],
            },
        ),
        Tool(
            name="search_by_user",
            description="Conversations and connector calls for a specific Azure AD user_id.",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "limit": {"type": "integer", "default": 25, "maximum": 50},
                },
                "required": ["user_id"],
            },
        ),
        Tool(
            name="get_agents",
            description="Copilot Studio agents with environment and solution info.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="get_environments",
            description="Power Platform environments with agent list and DLP policies.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="get_viva_insights",
            description="Per-user Viva Insights weekly hours (focus, meetings, chat, email). Filter by user_id or week_start.",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id":    {"type": "string"},
                    "week_start": {"type": "string", "description": "ISO date e.g. 2026-05-19"},
                    "limit":      {"type": "integer", "default": 25, "maximum": 50},
                },
                "required": [],
            },
        ),
        Tool(
            name="run_sql",
            description="Read-only SELECT query for custom analysis. Results capped at 50 rows.",
            inputSchema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        ),
    ])


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> CallToolResult:
    try:
        result = _dispatch(name, arguments)
        text = _render(name, result)
        return CallToolResult(content=[TextContent(type="text", text=text)])
    except Exception as e:
        return CallToolResult(content=[TextContent(type="text", text=f"Error: {e}")], isError=True)


def _render(name: str, result: object) -> str:
    """Convert tool results to compact text. Much cheaper than JSON for LLM callers."""
    if isinstance(result, dict):
        return "\n".join(f"{k}: {v}" for k, v in result.items() if v is not None)
    if not isinstance(result, list):
        return str(result)
    if not result:
        return "No results."

    formatters = {
        "get_kpi_snapshot":    _fmt_kpi,
        "get_agent_activity":  _fmt_agent_activity,
        "get_conversations":   _fmt_conversations,
        "get_top_connectors":  _fmt_connectors,
        "get_user_activity":   _fmt_user_activity,
        "get_agents":          _fmt_agents,
    }
    fmt = formatters.get(name)
    if fmt:
        return fmt(result)
    # Generic fallback: TSV-style — one row per line, tab-separated values (no repeated keys)
    if isinstance(result[0], dict):
        keys = list(result[0].keys())
        header = "\t".join(keys)
        rows = "\n".join("\t".join(str(r.get(k, "")) for k in keys) for r in result)
        return f"{header}\n{rows}"
    return "\n".join(str(r) for r in result)


def _fmt_kpi(rows: list) -> str:
    r = rows[0] if isinstance(rows, list) else rows
    if not isinstance(r, dict):
        return str(r)
    lines = [f"KPI Snapshot — {r.get('snapshot_date','')[:10]} (last {r.get('lookback_days','')}d)"]
    for k, v in r.items():
        if k not in ("snapshot_date", "lookback_days") and v is not None:
            lines.append(f"  {k}: {v}")
    return "\n".join(lines)


def _fmt_agent_activity(rows: list) -> str:
    lines = [f"{len(rows)} agent(s):"]
    for r in rows:
        lines.append(
            f"  {r.get('agent_name','')} | {r.get('environment','')} | "
            f"total={r.get('total_conversations',0)} prod={r.get('production_conversations',0)} "
            f"test={r.get('test_conversations',0)} last={str(r.get('last_activity',''))[:10]}"
        )
    return "\n".join(lines)


def _fmt_conversations(rows: list) -> str:
    lines = [f"{len(rows)} conversation(s):"]
    for r in rows:
        lines.append(
            f"  {r.get('conversation_id','')[:12]}… {r.get('channel','')} "
            f"recv={r.get('recv',0)} sent={r.get('sent',0)} "
            f"connectors={r.get('connector_calls',0)} {str(r.get('first_event',''))[:16]}"
        )
    return "\n".join(lines)


def _fmt_connectors(rows: list) -> str:
    lines = [f"{len(rows)} connector(s):"]
    for r in rows:
        ok = r.get('successful', 0)
        total = r.get('total_calls', 0)
        pct = round(ok * 100 / total, 1) if total else 0
        lines.append(
            f"  {r.get('connector_name','')} / {r.get('action_target','')} "
            f"calls={total} ok={pct}% avg={r.get('avg_duration_ms','')}ms"
        )
    return "\n".join(lines)


def _fmt_user_activity(rows: list) -> str:
    lines = [f"{len(rows)} user(s):"]
    for r in rows:
        lines.append(
            f"  {r.get('user_id','')[:12]}… convs={r.get('total_conversations',0)} "
            f"msgs={r.get('messages_sent',0)} last={str(r.get('last_activity',''))[:10]}"
        )
    return "\n".join(lines)


def _fmt_agents(rows: list) -> str:
    lines = [f"{len(rows)} agent(s):"]
    for r in rows:
        lines.append(
            f"  {r.get('display_name','')} | {r.get('environment','')} | "
            f"solution={r.get('solution_name','')} managed={r.get('is_managed','')} "
            f"published={str(r.get('published_at',''))[:10]}"
        )
    return "\n".join(lines)


_MAX_ROWS = 50  # hard ceiling for all list-returning tools


def _cap_limit(args: dict, default: int = 25) -> int:
    return min(int(args.get("limit", default)), _MAX_ROWS)


def _dispatch(name: str, args: dict) -> object:
    conn = _db()
    try:
        if name == "get_kpi_snapshot":        return _get_kpi_snapshot(conn)
        if name == "get_summary_stats":       return _get_summary_stats(conn)
        if name == "get_conversations":       return _get_conversations(conn, args)
        if name == "get_conversation_detail": return _get_conversation_detail(conn, args["conversation_id"])
        if name == "get_user_prompts":        return _get_user_prompts(conn, args)
        if name == "get_connector_calls":     return _get_connector_calls(conn, args)
        if name == "get_top_connectors":      return _get_top_connectors(conn, args)
        if name == "search_by_user":          return _search_by_user(conn, args)
        if name == "run_sql":                 return _run_sql(conn, args["query"])
        if name == "get_agents":              return _get_agents(conn)
        if name == "get_environments":        return _get_environments(conn)
        if name == "get_viva_insights":       return _get_viva_insights(conn, args)
        if name == "get_agent_activity":      return _get_agent_activity(conn, args)
        if name == "get_user_activity":       return _get_user_activity(conn, args)
        raise ValueError(f"Unknown tool: {name}")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _get_kpi_snapshot(conn: sqlite3.Connection) -> dict:
    """Return the most recent pre-aggregated KPI snapshot, falling back to live counts."""
    row = conn.execute("""
        SELECT snapshot_date, lookback_days,
               total_licenses, enabled_users, active_users,
               activation_rate, adoption_rate, power_users,
               total_prompts, avg_prompts_per_user,
               total_agents, active_agents, utilization_rate,
               production_agents, non_prod_agents,
               total_conversations, agent_adopters, agent_adoption_pct
        FROM kpi_snapshots ORDER BY snapshot_date DESC LIMIT 1
    """).fetchone()
    if row:
        return dict(row)
    # Fallback to live aggregation if no snapshot exists
    return _get_summary_stats(conn)


def _get_summary_stats(conn: sqlite3.Connection) -> dict:
    stats = {}
    stats["total_conversations"] = conn.execute("SELECT COUNT(DISTINCT conversation_id) FROM conversation_events").fetchone()[0]
    stats["production_conversations"] = conn.execute("SELECT COUNT(DISTINCT conversation_id) FROM conversation_events WHERE design_mode=0").fetchone()[0]
    stats["design_mode_conversations"] = conn.execute("SELECT COUNT(DISTINCT conversation_id) FROM conversation_events WHERE design_mode=1").fetchone()[0]
    stats["total_events"] = conn.execute("SELECT COUNT(*) FROM conversation_events").fetchone()[0]
    stats["total_connector_calls"] = conn.execute("SELECT COUNT(*) FROM connector_calls").fetchone()[0]
    stats["failed_connector_calls"] = conn.execute("SELECT COUNT(*) FROM connector_calls WHERE success=0").fetchone()[0]
    row = conn.execute("SELECT MIN(timestamp), MAX(timestamp) FROM conversation_events").fetchone()
    stats["earliest_event"] = row[0]
    stats["latest_event"] = row[1]
    row = conn.execute("SELECT started_at FROM sync_runs ORDER BY started_at DESC LIMIT 1").fetchone()
    stats["last_synced"] = row[0] if row else None
    stats["top_5_connectors"] = _rows(conn, "SELECT connector_name, COUNT(*) AS calls FROM connector_calls GROUP BY connector_name ORDER BY calls DESC LIMIT 5")
    return stats


def _get_conversations(conn: sqlite3.Connection, args: dict) -> list[dict]:
    limit = _cap_limit(args)
    filters, params = [], []
    if "channel_id" in args:
        filters.append("e.channel_id = ?"); params.append(args["channel_id"])
    if "design_mode" in args:
        filters.append("e.design_mode = ?"); params.append(1 if args["design_mode"] else 0)
    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    return _rows(conn, f"""
        SELECT e.conversation_id,
               MIN(e.user_id) AS user_id,
               MIN(e.channel_id) AS channel,
               MIN(e.timestamp) AS first_event,
               MAX(e.timestamp) AS last_event,
               SUM(CASE WHEN e.event_name='BotMessageReceived' THEN 1 ELSE 0 END) AS recv,
               SUM(CASE WHEN e.event_name='BotMessageSend' THEN 1 ELSE 0 END) AS sent,
               substr(GROUP_CONCAT(DISTINCT NULLIF(e.topic_name,'')), 1, 150) AS topics,
               COUNT(DISTINCT c.row_id) AS connector_calls
        FROM conversation_events e
        LEFT JOIN connector_calls c ON c.conversation_id = e.conversation_id
        {where}
        GROUP BY e.conversation_id ORDER BY first_event DESC LIMIT ?
    """, (*params, limit))


def _get_conversation_detail(conn: sqlite3.Connection, conversation_id: str) -> dict:
    return {
        "conversation_id": conversation_id,
        "events": _rows(conn, "SELECT timestamp, event_name, topic_name, substr(text,1,200) AS text FROM conversation_events WHERE conversation_id=? ORDER BY timestamp LIMIT 50", (conversation_id,)),
        "connector_calls": _rows(conn, "SELECT timestamp, connector_name, action_target, success, result_code, ROUND(duration_ms) AS ms FROM connector_calls WHERE conversation_id=? ORDER BY timestamp LIMIT 30", (conversation_id,)),
    }


def _get_user_prompts(conn: sqlite3.Connection, args: dict) -> list[dict]:
    limit = _cap_limit(args)
    filters = ["event_name = 'BotMessageReceived'", "text != ''", "text IS NOT NULL"]
    params: list = []
    if "search" in args:
        filters.append("text LIKE ?")
        params.append(f"%{args['search']}%")
    if "conversation_id" in args:
        filters.append("conversation_id = ?")
        params.append(args["conversation_id"])
    if "design_mode" in args:
        filters.append("design_mode = ?")
        params.append(1 if args["design_mode"] else 0)
    where = f"WHERE {' AND '.join(filters)}"
    return _rows(conn, f"""
        SELECT timestamp, conversation_id, user_id,
               substr(text, 1, 200) AS text
        FROM conversation_events
        {where}
        ORDER BY timestamp DESC LIMIT ?
    """, (*params, limit))


def _get_connector_calls(conn: sqlite3.Connection, args: dict) -> list[dict]:
    limit = _cap_limit(args)
    filters, params = [], []
    if "connector_name" in args: filters.append("connector_name=?"); params.append(args["connector_name"])
    if "action_target" in args: filters.append("action_target LIKE ?"); params.append(f"%{args['action_target']}%")
    if "success" in args: filters.append("success=?"); params.append(1 if args["success"] else 0)
    if "design_mode" in args: filters.append("design_mode=?"); params.append(1 if args["design_mode"] else 0)
    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    return _rows(conn, f"SELECT timestamp, connector_name, action_target, conversation_id, success, result_code, ROUND(duration_ms) AS ms FROM connector_calls {where} ORDER BY timestamp DESC LIMIT ?", (*params, limit))


def _get_top_connectors(conn: sqlite3.Connection, args: dict) -> list[dict]:
    limit = _cap_limit(args, default=10)
    filters, params = [], []
    if "design_mode" in args: filters.append("design_mode=?"); params.append(1 if args["design_mode"] else 0)
    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    return _rows(conn, f"""
        SELECT connector_name, action_target,
               COUNT(*) AS total_calls, SUM(success) AS successful,
               SUM(CASE WHEN success=0 THEN 1 ELSE 0 END) AS failed,
               ROUND(AVG(duration_ms),1) AS avg_duration_ms,
               ROUND(MAX(duration_ms),1) AS max_duration_ms
        FROM connector_calls {where}
        GROUP BY connector_name, action_target ORDER BY total_calls DESC LIMIT ?
    """, (*params, limit))


def _search_by_user(conn: sqlite3.Connection, args: dict) -> dict:
    uid, limit = args["user_id"], _cap_limit(args)
    return {
        "user_id": uid,
        "conversations": _rows(conn, "SELECT DISTINCT conversation_id, channel_id, design_mode, MIN(timestamp) AS first_seen FROM conversation_events WHERE user_id=? GROUP BY conversation_id ORDER BY first_seen DESC LIMIT ?", (uid, limit)),
        "connector_calls": _rows(conn, "SELECT timestamp, connector_name, action_target, success, duration_ms FROM connector_calls WHERE user_id=? ORDER BY timestamp DESC LIMIT ?", (uid, limit)),
    }


def _run_sql(conn: sqlite3.Connection, query: str) -> list[dict]:
    if not query.strip().upper().startswith("SELECT"):
        raise ValueError("Only SELECT statements are allowed.")
    # Wrap in a subquery to enforce a hard row cap without modifying the caller's SQL
    capped = f"SELECT * FROM ({query}) _q LIMIT {_MAX_ROWS}"
    return _rows(conn, capped)


def _get_agents(conn: sqlite3.Connection) -> list[dict]:
    return _rows(conn, """
        SELECT
            b.agent_id,
            b.display_name,
            e.display_name   AS environment,
            b.published_at,
            s.solution_name,
            s.is_managed
        FROM pva_agents b
        LEFT JOIN pva_environments e ON e.environment_id = b.environment_id
        LEFT JOIN pva_agent_solutions s ON s.agent_id = b.agent_id
        ORDER BY b.display_name
    """)


def _get_environments(conn: sqlite3.Connection) -> list[dict]:
    envs = _rows(conn, "SELECT * FROM pva_environments ORDER BY display_name")
    agents_by_env = {}
    for r in _rows(conn, "SELECT environment_id, display_name FROM pva_agents"):
        agents_by_env.setdefault(r["environment_id"], []).append(r["display_name"])

    dlp_all = _rows(conn, """
        SELECT display_name, environment_type,
               substr(blocked_connectors,     1, 300) AS blocked_connectors,
               substr(business_connectors,    1, 300) AS business_connectors,
               substr(non_business_connectors,1, 300) AS non_business_connectors
        FROM pva_dlp_policies
    """)
    policies_all_envs = [p for p in dlp_all if p["environment_type"] == "AllEnvironments"]

    result = []
    for env in envs:
        eid = env["environment_id"]
        policies_specific = [p for p in dlp_all if p["environment_type"] == "OnlyEnvironments"]
        result.append({
            **env,
            "agents": agents_by_env.get(eid, []),
            "dlp_policies": policies_all_envs + policies_specific,
        })
    return result


def _get_viva_insights(conn: sqlite3.Connection, args: dict) -> list[dict]:
    filters, params = [], []
    if "user_id" in args:
        filters.append("v.user_id = ?"); params.append(args["user_id"])
    if "week_start" in args:
        filters.append("v.week_start = ?"); params.append(args["week_start"])
    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    limit = _cap_limit(args)

    return _rows(conn, f"""
        SELECT
            v.user_id,
            v.week_start,
            v.week_end,
            ROUND(v.focus_hours,   2) AS focus_hours,
            ROUND(v.meeting_hours, 2) AS meeting_hours,
            ROUND(v.email_hours,   2) AS email_hours,
            ROUND(v.chat_hours,    2) AS chat_hours,
            ROUND(v.after_hours,   2) AS after_hours,
            ROUND(v.focus_hours + v.meeting_hours + v.email_hours + v.chat_hours, 2)
                AS total_collaboration_hours,
            COUNT(DISTINCT e.conversation_id) AS agent_conversations_that_week
        FROM viva_person_insights v
        LEFT JOIN conversation_events e
            ON e.user_id = v.user_id
            AND date(e.timestamp) BETWEEN v.week_start AND v.week_end
            AND e.design_mode = 0
        {where}
        GROUP BY v.row_id
        ORDER BY v.week_start DESC, v.user_id
        LIMIT ?
    """, (*params, limit))


def _get_agent_activity(conn: sqlite3.Connection, args: dict) -> list[dict]:
    dm_filter = ""
    params: list = []
    if "design_mode" in args:
        dm_filter = "AND e.design_mode = ?"
        params.append(1 if args["design_mode"] else 0)

    return _rows(conn, f"""
        SELECT
            b.display_name          AS agent_name,
            b.schema_name,
            b.published_at,
            env.display_name        AS environment,
            COUNT(DISTINCT e.conversation_id)                                       AS total_conversations,
            COUNT(DISTINCT CASE WHEN e.design_mode = 0 THEN e.conversation_id END)  AS production_conversations,
            COUNT(DISTINCT CASE WHEN e.design_mode = 1 THEN e.conversation_id END)  AS test_conversations,
            MAX(e.timestamp)        AS last_activity
        FROM pva_agents b
        LEFT JOIN pva_environments env ON env.environment_id = b.environment_id
        LEFT JOIN conversation_events e
            ON e.topic_name LIKE b.schema_name || '.topic.%' {dm_filter}
        GROUP BY b.agent_id, b.display_name, b.schema_name, b.published_at, env.display_name
        ORDER BY last_activity DESC NULLS LAST
    """, tuple(params))


def _get_user_activity(conn: sqlite3.Connection, args: dict) -> list[dict]:
    limit = _cap_limit(args)
    filters = ["user_id IS NOT NULL", "user_id != ''"]
    params: list = []
    if "design_mode" in args:
        filters.append("design_mode = ?")
        params.append(1 if args["design_mode"] else 0)
    where = "WHERE " + " AND ".join(filters)

    return _rows(conn, f"""
        SELECT
            e.user_id,
            COUNT(DISTINCT e.conversation_id)   AS total_conversations,
            SUM(CASE WHEN e.event_name = 'BotMessageReceived' THEN 1 ELSE 0 END) AS messages_sent,
            substr(GROUP_CONCAT(DISTINCT e.channel_id), 1, 100) AS channels,
            substr(GROUP_CONCAT(DISTINCT
                CASE WHEN e.topic_name LIKE '%.topic.%'
                THEN substr(e.topic_name, 1, instr(e.topic_name, '.topic.') - 1)
                END
            ), 1, 200)                          AS agents_interacted,
            MIN(e.timestamp)                    AS first_seen,
            MAX(e.timestamp)                    AS last_activity
        FROM conversation_events e
        {where}
        GROUP BY e.user_id
        ORDER BY last_activity DESC
        LIMIT ?
    """, (*params, limit))


# ---------------------------------------------------------------------------
# Entry points: stdio (local) or HTTP/SSE (deployed)
# ---------------------------------------------------------------------------

async def _run_stdio() -> None:
    from mcp.server.stdio import stdio_server
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def _run_http() -> None:
    import contextlib
    from mcp.server.sse import SseServerTransport
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from starlette.applications import Starlette
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import JSONResponse, Response
    from starlette.routing import Mount, Route
    import uvicorn

    class EntraAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            if request.method == "OPTIONS" or request.url.path in ("/health", "/"):
                return await call_next(request)
            try:
                _validate_token(dict(request.headers))
            except ValueError as e:
                print(f"AUTH FAIL [{request.method} {request.url.path}] headers: {dict(request.headers)}", file=sys.stderr)
                return JSONResponse({"error": str(e)}, status_code=401)
            return await call_next(request)

    # Legacy SSE transport (Claude Code, older clients)
    sse = SseServerTransport("/messages/")

    async def handle_sse(request: Request):
        async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
            await server.run(streams[0], streams[1], server.create_initialization_options())

    # Streamable HTTP transport (Copilot Studio, AI Foundry, newer MCP clients)
    session_manager = StreamableHTTPSessionManager(
        app=server,
        event_store=None,
        json_response=True,
        stateless=True,   # stateless = no session pinning required; simplest for agent platforms
    )

    @contextlib.asynccontextmanager
    async def lifespan(app):
        async with session_manager.run():
            yield

    starlette_app = Starlette(
        lifespan=lifespan,
        routes=[
            Route("/",          endpoint=lambda r: JSONResponse({"status": "ok"})),
            Route("/health",    endpoint=lambda r: JSONResponse({"status": "ok"})),
            Route("/sse",       endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ]
    )
    starlette_app.add_middleware(EntraAuthMiddleware)

    # Route /mcp* to the StreamableHTTP session manager directly (no prefix stripping)
    # and everything else to Starlette. This avoids Starlette's Mount stripping the
    # path before passing to the ASGI handler.
    async def root_app(scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            path = scope.get("path", "")
            if path == "/mcp" or path.startswith("/mcp/"):
                await session_manager.handle_request(scope, receive, send)
                return
        await starlette_app(scope, receive, send)

    uvicorn.run(root_app, host="0.0.0.0", port=settings.port)


if __name__ == "__main__":
    import asyncio
    mode = os.getenv("MCP_TRANSPORT", "stdio")
    if mode == "http":
        _run_http()
    else:
        asyncio.run(_run_stdio())
